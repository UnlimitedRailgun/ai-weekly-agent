"""Immutable attempt artifacts and atomic publication manifests.

The normal CLI uses this module as its single local persistence boundary. It
keeps attempt artifacts immutable and makes one exact-range manifest the
publication authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import errno
import hashlib
import hmac
import importlib
import os
from pathlib import Path
import re
import stat
from types import ModuleType
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from ai_weekly_agent.models import DateRange, ResearchRun


MANIFEST_SCHEMA_VERSION = 1
_RUN_ID_PATTERN = r"^[0-9a-f]{32}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_MAX_MANIFEST_BYTES = 64 * 1024
_PUBLICATION_MANIFEST_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})\.json$"
)

RunId = Annotated[str, Field(pattern=_RUN_ID_PATTERN)]
Sha256Digest = Annotated[str, Field(pattern=_SHA256_PATTERN)]
CommitState = Literal["published", "not_published", "unknown"]
DurabilityState = Literal["confirmed", "unconfirmed", "not_applicable"]


class StorageError(RuntimeError):
    """Base error for the v0.6 persistence core."""


class UnsafeStoragePathError(StorageError):
    """Raised when a managed path is unsafe or has an unsupported type."""


class AttemptExistsError(StorageError):
    """Raised when an attempt identity or immutable artifact already exists."""


class AttemptIncompleteError(StorageError):
    """Raised when an attempt does not have a complete raw/report pair."""


class PublicationExistsError(StorageError):
    """Raised when no-overwrite publication finds an existing publication."""


class InvalidPublicationError(StorageError):
    """Raised when a publication manifest or one of its artifacts is invalid."""


class PublicationLockError(StorageError):
    """Base error for exact-range publication locking."""


class PublicationLockBusyError(PublicationLockError):
    """Raised when another cooperating writer holds the exact-range lock."""


class PublicationLockUnsupportedError(PublicationLockError):
    """Raised when the platform cannot provide the required lock semantics."""


class PublicationCommitError(StorageError):
    """A failed commit with an observed post-failure publication state."""

    def __init__(
        self,
        message: str,
        *,
        state: CommitState,
        durability: DurabilityState,
        publication: PublishedArtifactSet | None,
    ) -> None:
        super().__init__(message)
        self.state = state
        self.durability = durability
        self.publication = publication


class PublicationCommitInterrupted(KeyboardInterrupt):
    """A keyboard interruption classified against the visible manifest."""

    def __init__(
        self,
        message: str,
        *,
        state: CommitState,
        durability: DurabilityState,
        publication: PublishedArtifactSet | None,
    ) -> None:
        super().__init__(message)
        self.state = state
        self.durability = durability
        self.publication = publication


class ManifestDateRange(BaseModel):
    """Strict date-range representation owned by the manifest schema."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    start: date
    end: date

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.start > self.end:
            raise ValueError("start must not be after end")
        return self

    @classmethod
    def from_date_range(cls, date_range: DateRange) -> ManifestDateRange:
        return cls(start=date_range.start, end=date_range.end)

    def to_date_range(self) -> DateRange:
        return DateRange(start=self.start, end=self.end)


class PublishedArtifactReference(BaseModel):
    """Content-free identity and byte integrity for one published artifact."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    filename: str = Field(min_length=1, max_length=128)
    sha256: Sha256Digest
    byte_length: int = Field(ge=0)


class PublicationManifest(BaseModel):
    """The independently versioned commit record for one exact date range."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[MANIFEST_SCHEMA_VERSION] = MANIFEST_SCHEMA_VERSION
    date_range: ManifestDateRange
    run_id: RunId
    application_version: str = Field(min_length=1, max_length=128)
    published_at: AwareDatetime
    raw: PublishedArtifactReference
    report: PublishedArtifactReference

    @field_validator("application_version")
    @classmethod
    def validate_application_version(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("application_version must not have outer whitespace")
        return value

    @field_validator("published_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("published_at must use UTC")
        return value

    @model_validator(mode="after")
    def validate_artifact_names(self) -> Self:
        if self.raw.filename != f"{self.run_id}.json":
            raise ValueError("raw filename does not match run_id")
        if self.report.filename != f"{self.run_id}.md":
            raise ValueError("report filename does not match run_id")
        return self


@dataclass(frozen=True)
class AttemptPaths:
    """Strictly derived locations reserved for one immutable attempt."""

    date_range: DateRange
    run_id: str
    attempt_dir: Path
    raw_path: Path
    report_path: Path


@dataclass(frozen=True)
class StoredArtifact:
    """Metadata calculated from the exact bytes written to one artifact."""

    path: Path
    sha256: str
    byte_length: int


@dataclass(frozen=True)
class PublishedArtifactSet:
    """One manifest snapshot and the exact artifact bytes it authenticated."""

    manifest: PublicationManifest
    manifest_path: Path
    manifest_bytes: bytes
    raw_path: Path
    raw_bytes: bytes
    report_path: Path
    report_bytes: bytes


@dataclass(frozen=True)
class PublicationDiscovery:
    """Read-only inventory of canonical manifests under one trusted root."""

    directory_exists: bool
    date_ranges: tuple[DateRange, ...]
    unexpected_entries: tuple[Path, ...]


@dataclass(frozen=True)
class PublicationCommitResult:
    """A fully visible publication whose directory sync also succeeded."""

    state: Literal["published"]
    durability: Literal["confirmed"]
    publication: PublishedArtifactSet


class PublicationLock:
    """A held, non-blocking advisory lock for one exact date range."""

    def __init__(
        self,
        *,
        storage_identity: str,
        range_identity: str,
        path: Path,
        descriptor: int,
        fcntl_module: ModuleType,
    ) -> None:
        self._storage_identity = storage_identity
        self._range_identity = range_identity
        self.path = path
        self._descriptor = descriptor
        self._fcntl = fcntl_module
        self._held = True

    @property
    def held(self) -> bool:
        return self._held

    def release(self) -> None:
        """Release and close the descriptor without deleting the lock file."""
        if not self._held:
            return
        descriptor = self._descriptor
        self._held = False
        unlock_error: OSError | None = None
        try:
            self._fcntl.flock(descriptor, self._fcntl.LOCK_UN)
        except OSError as exc:
            unlock_error = exc
        finally:
            os.close(descriptor)
        if unlock_error is not None:
            raise PublicationLockError(
                f"Could not release publication lock: {self.path}"
            ) from unlock_error

    def __enter__(self) -> PublicationLock:
        if not self._held:
            raise PublicationLockError("Publication lock is no longer held")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is None:
            self.release()
        else:
            try:
                self.release()
            except PublicationLockError:
                # Never replace the primary pipeline error during unwinding.
                pass
        return False


class PublicationStorage:
    """Manage immutable attempts under one trusted local storage root."""

    def __init__(self, root: str | Path) -> None:
        self.root = _normalized_absolute_path(root)
        self._storage_identity = os.fspath(self.root)
        if self.root.is_symlink():
            raise UnsafeStoragePathError(
                f"Storage root must not be a symbolic link: {self.root}"
            )
        if self.root.exists():
            _require_safe_directory(self.root, create=False)

    def acquire_lock(self, date_range: DateRange) -> PublicationLock:
        """Acquire the required non-blocking Linux/WSL exact-range lock."""
        fcntl_module = _import_fcntl()
        lock_directory = self.root / "data" / "runs" / "locks"
        _require_managed_directory(self.root, lock_directory, create=True)
        lock_path = lock_directory / f"{_range_identity(date_range)}.lock"
        descriptor: int | None = None
        try:
            descriptor = _open_lock_file(lock_path)
            file_status = os.fstat(descriptor)
            if not stat.S_ISREG(file_status.st_mode):
                raise UnsafeStoragePathError(
                    f"Publication lock is not a regular file: {lock_path}"
                )
        except OSError as exc:
            if descriptor is not None:
                os.close(descriptor)
            raise PublicationLockError(
                f"Could not open publication lock: {lock_path}"
            ) from exc
        except BaseException:
            if descriptor is not None:
                os.close(descriptor)
            raise

        try:
            fcntl_module.flock(
                descriptor,
                fcntl_module.LOCK_EX | fcntl_module.LOCK_NB,
            )
        except BlockingIOError as exc:
            os.close(descriptor)
            raise PublicationLockBusyError(
                f"Publication lock is already held: {lock_path}"
            ) from exc
        except OSError as exc:
            os.close(descriptor)
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                raise PublicationLockBusyError(
                    f"Publication lock is already held: {lock_path}"
                ) from exc
            raise PublicationLockError(
                f"Could not acquire publication lock: {lock_path}"
            ) from exc
        return PublicationLock(
            storage_identity=self._storage_identity,
            range_identity=_range_identity(date_range),
            path=lock_path,
            descriptor=descriptor,
            fcntl_module=fcntl_module,
        )

    def allocate_attempt(
        self,
        date_range: DateRange,
        *,
        lock: PublicationLock,
        run_id: str | None = None,
    ) -> AttemptPaths:
        """Reserve one unique attempt directory without reusing any target."""
        self._require_lock(lock, date_range)
        selected_run_id = run_id if run_id is not None else generate_run_id()
        _validate_run_id(selected_run_id)
        attempt = self._derive_attempt(date_range, selected_run_id)

        for directory in (attempt.raw_path.parent, attempt.report_path.parent):
            _require_managed_directory(self.root, directory, create=True)
        _require_managed_directory(
            self.root,
            attempt.attempt_dir.parent,
            create=True,
        )
        for target in (attempt.raw_path, attempt.report_path):
            if _path_entry_exists(target):
                raise AttemptExistsError(
                    f"Attempt artifact already exists: {target}"
                )

        try:
            attempt.attempt_dir.mkdir(mode=0o700, exist_ok=False)
            _fsync_directory(attempt.attempt_dir.parent)
        except FileExistsError as exc:
            raise AttemptExistsError(
                f"Attempt identity already exists: {selected_run_id}"
            ) from exc
        except OSError as exc:
            try:
                attempt.attempt_dir.rmdir()
            except OSError:
                pass
            raise StorageError(
                f"Could not reserve attempt identity: {selected_run_id}"
            ) from exc
        return attempt

    def write_raw(
        self,
        attempt: AttemptPaths,
        research_run: ResearchRun,
        *,
        lock: PublicationLock,
    ) -> StoredArtifact:
        """Write the original ResearchRun once as the attempt audit artifact."""
        self._validate_attempt(attempt, lock)
        if research_run.date_range != attempt.date_range:
            raise StorageError(
                "ResearchRun date range does not match the reserved attempt"
            )
        content = (research_run.model_dump_json(indent=2) + "\n").encode("utf-8")
        return self._write_attempt_artifact(attempt.raw_path, content)

    def write_report(
        self,
        attempt: AttemptPaths,
        markdown: str,
        *,
        lock: PublicationLock,
    ) -> StoredArtifact:
        """Write one final Markdown byte sequence without later replacement."""
        self._validate_attempt(attempt, lock)
        return self._write_attempt_artifact(
            attempt.report_path,
            markdown.encode("utf-8"),
        )

    def attempt_run_record_path(
        self,
        attempt: AttemptPaths,
        *,
        lock: PublicationLock,
    ) -> Path:
        """Return the canonical telemetry path for a reserved attempt."""
        self._validate_attempt(attempt, lock)
        target = attempt.attempt_dir / "run.json"
        _require_within_root(self.root, target)
        return target

    def write_attempt_run_record(
        self,
        attempt: AttemptPaths,
        content: bytes,
        *,
        lock: PublicationLock,
    ) -> Path:
        """Exclusively create one final serialized RunRecord for an attempt."""
        target = self.attempt_run_record_path(attempt, lock=lock)
        try:
            _write_new_file(target, content, sync_directory=True)
        except FileExistsError as exc:
            raise AttemptExistsError(
                f"Attempt RunRecord already exists: {target}"
            ) from exc
        except OSError as exc:
            raise StorageError(
                f"Could not write attempt RunRecord: {target}"
            ) from exc
        return target

    def read_publication(
        self,
        date_range: DateRange,
    ) -> PublishedArtifactSet | None:
        """Read one manifest snapshot and its authenticated artifact bytes.

        A missing manifest returns ``None``. Any present but malformed,
        unsupported, unsafe, unreadable, incomplete, or mismatched publication
        raises :class:`InvalidPublicationError`.
        """
        manifest_directory = self.root / "data" / "runs" / "published"
        try:
            directory_exists = _require_managed_directory(
                self.root,
                manifest_directory,
                create=False,
            )
        except UnsafeStoragePathError as exc:
            raise InvalidPublicationError(
                "Publication manifest directory is unsafe"
            ) from exc
        if not directory_exists:
            return None

        manifest_path = manifest_directory / (
            f"{_range_identity(date_range)}.json"
        )
        try:
            manifest_bytes = _read_regular_file(
                manifest_path,
                missing_ok=True,
                maximum_bytes=_MAX_MANIFEST_BYTES,
            )
        except (OSError, UnsafeStoragePathError) as exc:
            raise InvalidPublicationError(
                f"Could not safely read publication manifest: {manifest_path}"
            ) from exc
        if manifest_bytes is None:
            return None

        try:
            manifest = PublicationManifest.model_validate_json(manifest_bytes)
        except (ValidationError, ValueError) as exc:
            raise InvalidPublicationError(
                f"Publication manifest is malformed or unsupported: {manifest_path}"
            ) from exc
        if manifest.date_range.to_date_range() != date_range:
            raise InvalidPublicationError(
                "Publication manifest date range does not match its filename"
            )

        attempt = self._derive_attempt(date_range, manifest.run_id)
        if (
            manifest.raw.filename != attempt.raw_path.name
            or manifest.report.filename != attempt.report_path.name
        ):
            raise InvalidPublicationError(
                "Publication manifest artifact names are not canonical"
            )

        try:
            raw_bytes = _read_required_artifact(attempt.raw_path)
            report_bytes = _read_required_artifact(attempt.report_path)
        except (OSError, UnsafeStoragePathError) as exc:
            raise InvalidPublicationError(
                "Published artifact is missing, unsafe, or unreadable"
            ) from exc
        _validate_artifact_bytes("raw", raw_bytes, manifest.raw)
        _validate_artifact_bytes("report", report_bytes, manifest.report)

        return PublishedArtifactSet(
            manifest=manifest,
            manifest_path=manifest_path,
            manifest_bytes=manifest_bytes,
            raw_path=attempt.raw_path,
            raw_bytes=raw_bytes,
            report_path=attempt.report_path,
            report_bytes=report_bytes,
        )

    def discover_publications(self) -> PublicationDiscovery:
        """Discover canonical publication identities without reading content.

        A canonical filename establishes the exact range whose manifest must
        later be validated by :meth:`read_publication`. Temporary files are
        ignored, while other non-canonical entries are reported to the caller.
        This operation never creates or modifies storage paths.
        """
        manifest_directory = self.root / "data" / "runs" / "published"
        try:
            directory_exists = _require_managed_directory(
                self.root,
                manifest_directory,
                create=False,
            )
        except UnsafeStoragePathError as exc:
            raise InvalidPublicationError(
                "Publication manifest directory is unsafe"
            ) from exc
        if not directory_exists:
            return PublicationDiscovery(False, (), ())

        try:
            entries = sorted(manifest_directory.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise InvalidPublicationError(
                "Could not enumerate the publication manifest directory"
            ) from exc

        date_ranges: list[DateRange] = []
        unexpected_entries: list[Path] = []
        for entry in entries:
            match = _PUBLICATION_MANIFEST_RE.fullmatch(entry.name)
            if match is not None:
                try:
                    date_range = DateRange(
                        start=date.fromisoformat(match.group(1)),
                        end=date.fromisoformat(match.group(2)),
                    )
                except (ValidationError, ValueError):
                    unexpected_entries.append(entry)
                else:
                    date_ranges.append(date_range)
                continue
            if entry.name.startswith(".") and entry.name.endswith(".tmp"):
                continue
            unexpected_entries.append(entry)

        date_ranges.sort(key=lambda value: (value.start, value.end))
        return PublicationDiscovery(
            True,
            tuple(date_ranges),
            tuple(unexpected_entries),
        )

    def publish(
        self,
        attempt: AttemptPaths,
        *,
        application_version: str,
        lock: PublicationLock,
        overwrite: bool = False,
        published_at: datetime | None = None,
    ) -> PublicationCommitResult:
        """Commit a complete attempt by atomically replacing its manifest."""
        self._validate_attempt(attempt, lock)
        previous = self.read_publication(attempt.date_range)
        if previous is not None and not overwrite:
            raise PublicationExistsError(
                "A publication already exists for this exact date range"
            )
        if previous is not None and previous.manifest.run_id == attempt.run_id:
            raise PublicationExistsError(
                "The current attempt is already the published attempt"
            )

        try:
            raw_bytes = _read_required_artifact(attempt.raw_path)
            report_bytes = _read_required_artifact(attempt.report_path)
        except (OSError, UnsafeStoragePathError) as exc:
            raise AttemptIncompleteError(
                "Attempt must contain safe, complete raw and report artifacts"
            ) from exc

        manifest = PublicationManifest(
            date_range=ManifestDateRange.from_date_range(attempt.date_range),
            run_id=attempt.run_id,
            application_version=application_version,
            published_at=published_at or datetime.now(UTC),
            raw=_artifact_reference(attempt.raw_path, raw_bytes),
            report=_artifact_reference(attempt.report_path, report_bytes),
        )
        manifest_bytes = (manifest.model_dump_json(indent=2) + "\n").encode(
            "utf-8"
        )
        manifest_directory = self.root / "data" / "runs" / "published"
        _require_managed_directory(
            self.root,
            manifest_directory,
            create=True,
        )
        manifest_path = manifest_directory / (
            f"{_range_identity(attempt.date_range)}.json"
        )
        temporary_path = manifest_directory / (
            f".{manifest_path.name}.{generate_run_id()}.tmp"
        )

        try:
            _write_new_file(temporary_path, manifest_bytes, sync_directory=False)
            os.replace(temporary_path, manifest_path)
            _fsync_directory(manifest_directory)
        except KeyboardInterrupt as exc:
            _unlink_temporary(temporary_path)
            state, durability, visible = self._classify_commit(
                attempt.date_range,
                proposed=manifest,
                previous=previous,
            )
            raise PublicationCommitInterrupted(
                "Publication commit was interrupted",
                state=state,
                durability=durability,
                publication=visible,
            ) from exc
        except Exception as exc:
            _unlink_temporary(temporary_path)
            state, durability, visible = self._classify_commit(
                attempt.date_range,
                proposed=manifest,
                previous=previous,
            )
            raise PublicationCommitError(
                "Publication commit failed",
                state=state,
                durability=durability,
                publication=visible,
            ) from exc

        publication = self.read_publication(attempt.date_range)
        if publication is None:  # pragma: no cover - defensive invariant
            raise PublicationCommitError(
                "Publication disappeared after a successful commit",
                state="unknown",
                durability="unconfirmed",
                publication=None,
            )
        if publication.manifest != manifest:
            raise PublicationCommitError(
                "Publication changed after a successful commit",
                state="unknown",
                durability="unconfirmed",
                publication=publication,
            )
        return PublicationCommitResult(
            state="published",
            durability="confirmed",
            publication=publication,
        )

    def _derive_attempt(
        self,
        date_range: DateRange,
        run_id: str,
    ) -> AttemptPaths:
        _validate_run_id(run_id)
        range_identity = _range_identity(date_range)
        attempt = AttemptPaths(
            date_range=date_range.model_copy(deep=True),
            run_id=run_id,
            attempt_dir=(
                self.root
                / "data"
                / "runs"
                / "attempts"
                / range_identity
                / run_id
            ),
            raw_path=self.root / "data" / "raw" / range_identity / f"{run_id}.json",
            report_path=self.root / "reports" / range_identity / f"{run_id}.md",
        )
        for path in (attempt.attempt_dir, attempt.raw_path, attempt.report_path):
            _require_within_root(self.root, path)
        return attempt

    def _validate_attempt(
        self,
        attempt: AttemptPaths,
        lock: PublicationLock,
    ) -> None:
        self._require_lock(lock, attempt.date_range)
        expected = self._derive_attempt(attempt.date_range, attempt.run_id)
        if attempt != expected:
            raise UnsafeStoragePathError(
                "Attempt paths do not match the trusted derived layout"
            )
        try:
            _require_managed_directory(
                self.root,
                attempt.attempt_dir,
                create=False,
            )
        except UnsafeStoragePathError:
            raise
        if not attempt.attempt_dir.is_dir():
            raise StorageError("Attempt identity has not been reserved")

    def _require_lock(
        self,
        lock: PublicationLock,
        date_range: DateRange,
    ) -> None:
        if (
            not isinstance(lock, PublicationLock)
            or not lock.held
            or lock._storage_identity != self._storage_identity
            or lock._range_identity != _range_identity(date_range)
        ):
            raise PublicationLockError(
                "A held lock for this storage root and exact date range is required"
            )

    def _write_attempt_artifact(
        self,
        path: Path,
        content: bytes,
    ) -> StoredArtifact:
        try:
            _write_new_file(path, content, sync_directory=True)
        except FileExistsError as exc:
            raise AttemptExistsError(
                f"Immutable attempt artifact already exists: {path}"
            ) from exc
        except OSError as exc:
            raise StorageError(f"Could not write attempt artifact: {path}") from exc
        return StoredArtifact(
            path=path,
            sha256=_sha256(content),
            byte_length=len(content),
        )

    def _classify_commit(
        self,
        date_range: DateRange,
        *,
        proposed: PublicationManifest,
        previous: PublishedArtifactSet | None,
    ) -> tuple[CommitState, DurabilityState, PublishedArtifactSet | None]:
        try:
            visible = self.read_publication(date_range)
        except (InvalidPublicationError, OSError):
            return "unknown", "unconfirmed", None
        if visible is not None and visible.manifest == proposed:
            return "published", "unconfirmed", visible
        if visible is None and previous is None:
            return "not_published", "not_applicable", None
        if (
            visible is not None
            and previous is not None
            and visible.manifest_bytes == previous.manifest_bytes
        ):
            return "not_published", "not_applicable", visible
        return "unknown", "unconfirmed", visible


def generate_run_id() -> str:
    """Return a lowercase, path-safe standard-library attempt identity."""
    return uuid4().hex


def _range_identity(date_range: DateRange) -> str:
    return f"{date_range.start.isoformat()}_to_{date_range.end.isoformat()}"


def _validate_run_id(run_id: str) -> None:
    if (
        not isinstance(run_id, str)
        or len(run_id) != 32
        or any(character not in "0123456789abcdef" for character in run_id)
    ):
        raise ValueError("run_id must be exactly 32 lowercase hexadecimal characters")


def _artifact_reference(path: Path, content: bytes) -> PublishedArtifactReference:
    return PublishedArtifactReference(
        filename=path.name,
        sha256=_sha256(content),
        byte_length=len(content),
    )


def _validate_artifact_bytes(
    kind: str,
    content: bytes,
    reference: PublishedArtifactReference,
) -> None:
    if len(content) != reference.byte_length or not hmac.compare_digest(
        _sha256(content),
        reference.sha256,
    ):
        raise InvalidPublicationError(
            f"Published {kind} artifact does not match its manifest digest"
        )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalized_absolute_path(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _require_within_root(root: Path, candidate: Path) -> None:
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeStoragePathError(
            f"Managed path is outside the storage root: {candidate}"
        ) from exc


def _require_managed_directory(
    root: Path,
    directory: Path,
    *,
    create: bool,
) -> bool:
    _require_within_root(root, directory)
    root_exists = _require_safe_directory(root, create=create)
    if not root_exists:
        return False
    return _require_safe_directory(directory, create=create)


def _require_safe_directory(path: Path, *, create: bool) -> bool:
    """Reject symlinks/non-directories in an absolute directory chain."""
    if not path.is_absolute():
        raise UnsafeStoragePathError(f"Managed directory is not absolute: {path}")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            entry_status = current.lstat()
        except FileNotFoundError:
            if not create:
                return False
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
            entry_status = current.lstat()
        if stat.S_ISLNK(entry_status.st_mode):
            raise UnsafeStoragePathError(
                f"Managed directory must not traverse a symbolic link: {current}"
            )
        if not stat.S_ISDIR(entry_status.st_mode):
            raise UnsafeStoragePathError(
                f"Managed directory component is not a directory: {current}"
            )
    return True


def _path_entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _require_linux_file_flags() -> tuple[int, int]:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory is None:
        raise PublicationLockUnsupportedError(
            "Required Linux/WSL no-follow filesystem flags are unavailable"
        )
    return no_follow, directory


def _open_lock_file(path: Path) -> int:
    no_follow, _ = _require_linux_file_flags()
    return os.open(
        path,
        os.O_RDWR | os.O_CREAT | no_follow | os.O_NONBLOCK,
        0o600,
    )


def _write_new_file(path: Path, content: bytes, *, sync_directory: bool) -> None:
    no_follow, _ = _require_linux_file_flags()
    descriptor: int | None = None
    created = False
    completed = False
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow,
            0o600,
        )
        created = True
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            descriptor = None
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if sync_directory:
            _fsync_directory(path.parent)
        completed = True
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created and not completed:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _read_required_artifact(path: Path) -> bytes:
    content = _read_regular_file(path, missing_ok=False)
    if content is None:  # pragma: no cover - typed defensive invariant
        raise FileNotFoundError(path)
    return content


def _read_regular_file(
    path: Path,
    *,
    missing_ok: bool,
    maximum_bytes: int | None = None,
) -> bytes | None:
    _require_safe_directory(path.parent, create=False)
    no_follow, _ = _require_linux_file_flags()
    try:
        descriptor = os.open(path, os.O_RDONLY | no_follow | os.O_NONBLOCK)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    try:
        entry_status = os.fstat(descriptor)
        if not stat.S_ISREG(entry_status.st_mode):
            raise UnsafeStoragePathError(
                f"Managed artifact is not a regular file: {path}"
            )
        with os.fdopen(descriptor, "rb", closefd=True) as source:
            descriptor = -1
            if maximum_bytes is None:
                return source.read()
            content = source.read(maximum_bytes + 1)
            if len(content) > maximum_bytes:
                raise UnsafeStoragePathError(
                    f"Managed file exceeds its size limit: {path}"
                )
            return content
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    no_follow, directory = _require_linux_file_flags()
    descriptor = os.open(path, os.O_RDONLY | directory | no_follow)
    try:
        entry_status = os.fstat(descriptor)
        if not stat.S_ISDIR(entry_status.st_mode):
            raise UnsafeStoragePathError(
                f"Managed path is not a directory: {path}"
            )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _unlink_temporary(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _import_fcntl() -> ModuleType:
    try:
        return importlib.import_module("fcntl")
    except (ImportError, OSError) as exc:
        raise PublicationLockUnsupportedError(
            "Exact-range publication locking requires fcntl.flock"
        ) from exc
