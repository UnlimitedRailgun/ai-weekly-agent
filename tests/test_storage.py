import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
import re

import pytest

import ai_weekly_agent.storage as storage_module
from ai_weekly_agent.models import DateRange, ResearchRun
from ai_weekly_agent.storage import (
    AttemptExistsError,
    AttemptIncompleteError,
    InvalidPublicationError,
    PublicationCommitError,
    PublicationCommitInterrupted,
    PublicationExistsError,
    PublicationLock,
    PublicationLockError,
    PublicationStorage,
    StorageError,
    UnsafeStoragePathError,
    generate_run_id,
)


DATE_RANGE = DateRange(start=date(2026, 9, 13), end=date(2026, 9, 19))
SAME_WEEK_RANGE = DateRange(
    start=date(2026, 9, 12),
    end=date(2026, 9, 18),
)
PUBLISHED_AT = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
RUN_ID_1 = "1" * 32
RUN_ID_2 = "2" * 32


def make_run(date_range: DateRange = DATE_RANGE) -> ResearchRun:
    return ResearchRun(date_range=date_range, categories=[])


def create_complete_attempt(
    storage: PublicationStorage,
    date_range: DateRange,
    run_id: str,
    *,
    lock: PublicationLock,
    markdown: str | None = None,
):
    attempt = storage.allocate_attempt(
        date_range,
        lock=lock,
        run_id=run_id,
    )
    storage.write_raw(attempt, make_run(date_range), lock=lock)
    storage.write_report(
        attempt,
        markdown or f"report for {run_id}\n",
        lock=lock,
    )
    return attempt


def publish_attempt(
    storage: PublicationStorage,
    date_range: DateRange,
    run_id: str,
    *,
    overwrite: bool = False,
    markdown: str | None = None,
):
    with storage.acquire_lock(date_range) as lock:
        attempt = create_complete_attempt(
            storage,
            date_range,
            run_id,
            lock=lock,
            markdown=markdown,
        )
        result = storage.publish(
            attempt,
            application_version="0.5.0",
            lock=lock,
            overwrite=overwrite,
            published_at=PUBLISHED_AT,
        )
    return attempt, result


def manifest_path(root: Path, date_range: DateRange = DATE_RANGE) -> Path:
    identity = f"{date_range.start.isoformat()}_to_{date_range.end.isoformat()}"
    return root / "data" / "runs" / "published" / f"{identity}.json"


def test_generated_run_id_is_strict_lowercase_hex() -> None:
    first = generate_run_id()
    second = generate_run_id()

    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert re.fullmatch(r"[0-9a-f]{32}", second)
    assert first != second


@pytest.mark.parametrize(
    "run_id",
    [
        "",
        "a" * 31,
        "a" * 33,
        "A" * 32,
        "g" * 32,
        "../" + "a" * 29,
        "/" + "a" * 31,
    ],
)
def test_attempt_rejects_noncanonical_run_id(
    tmp_path: Path,
    run_id: str,
) -> None:
    storage = PublicationStorage(tmp_path)

    with storage.acquire_lock(DATE_RANGE) as lock:
        with pytest.raises(ValueError, match="run_id"):
            storage.allocate_attempt(DATE_RANGE, lock=lock, run_id=run_id)


def test_attempt_identity_cannot_be_reused(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)

    with storage.acquire_lock(DATE_RANGE) as lock:
        storage.allocate_attempt(DATE_RANGE, lock=lock, run_id=RUN_ID_1)
        with pytest.raises(AttemptExistsError, match="already exists"):
            storage.allocate_attempt(DATE_RANGE, lock=lock, run_id=RUN_ID_1)


def test_raw_and_report_are_immutable(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)

    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = create_complete_attempt(
            storage,
            DATE_RANGE,
            RUN_ID_1,
            lock=lock,
        )
        raw_before = attempt.raw_path.read_bytes()
        report_before = attempt.report_path.read_bytes()

        with pytest.raises(AttemptExistsError):
            storage.write_raw(attempt, make_run(), lock=lock)
        with pytest.raises(AttemptExistsError):
            storage.write_report(attempt, "replacement", lock=lock)

    assert attempt.raw_path.read_bytes() == raw_before
    assert attempt.report_path.read_bytes() == report_before


def test_attempt_run_record_is_canonical_exclusive_and_lock_bound(
    tmp_path: Path,
) -> None:
    storage = PublicationStorage(tmp_path)
    content = b'{"schema_version": 1}\n'

    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = storage.allocate_attempt(
            DATE_RANGE,
            lock=lock,
            run_id=RUN_ID_1,
        )
        expected = attempt.attempt_dir / "run.json"
        assert storage.attempt_run_record_path(attempt, lock=lock) == expected
        target = storage.write_attempt_run_record(
            attempt,
            content,
            lock=lock,
        )
        assert target == expected
        assert target.read_bytes() == content
        with pytest.raises(AttemptExistsError):
            storage.write_attempt_run_record(
                attempt,
                b"replacement",
                lock=lock,
            )

    assert target.read_bytes() == content


def test_attempt_run_record_failure_cleans_only_file_created_by_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = PublicationStorage(tmp_path)
    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = storage.allocate_attempt(
            DATE_RANGE,
            lock=lock,
            run_id=RUN_ID_1,
        )
        target = attempt.attempt_dir / "run.json"

        def fail_sync(_descriptor: int) -> None:
            raise OSError("telemetry sync failed")

        monkeypatch.setattr(storage_module.os, "fsync", fail_sync)
        with pytest.raises(StorageError, match="RunRecord"):
            storage.write_attempt_run_record(
                attempt,
                b"new telemetry",
                lock=lock,
            )
        assert not target.exists()

        target.write_bytes(b"existing telemetry")
        with pytest.raises(AttemptExistsError):
            storage.write_attempt_run_record(
                attempt,
                b"replacement",
                lock=lock,
            )
        assert target.read_bytes() == b"existing telemetry"


def test_raw_must_match_reserved_date_range(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)
    other = DateRange(start=date(2026, 9, 1), end=date(2026, 9, 7))

    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = storage.allocate_attempt(
            DATE_RANGE,
            lock=lock,
            run_id=RUN_ID_1,
        )
        with pytest.raises(StorageError, match="date range"):
            storage.write_raw(attempt, make_run(other), lock=lock)

    assert not attempt.raw_path.exists()


def test_different_ranges_in_same_iso_week_publish_independently(
    tmp_path: Path,
) -> None:
    storage = PublicationStorage(tmp_path)
    first_attempt, _ = publish_attempt(
        storage,
        DATE_RANGE,
        RUN_ID_1,
    )
    second_attempt, _ = publish_attempt(
        storage,
        SAME_WEEK_RANGE,
        RUN_ID_1,
    )

    first = storage.read_publication(DATE_RANGE)
    second = storage.read_publication(SAME_WEEK_RANGE)

    assert first is not None
    assert second is not None
    assert first.manifest_path != second.manifest_path
    assert first_attempt.raw_path != second_attempt.raw_path
    assert first_attempt.report_path != second_attempt.report_path
    assert first.manifest.date_range.to_date_range() == DATE_RANGE
    assert second.manifest.date_range.to_date_range() == SAME_WEEK_RANGE


def test_first_publication_returns_authenticated_snapshot(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)
    attempt, result = publish_attempt(storage, DATE_RANGE, RUN_ID_1)

    assert result.state == "published"
    assert result.durability == "confirmed"
    assert result.publication.manifest.run_id == RUN_ID_1
    assert result.publication.raw_bytes == attempt.raw_path.read_bytes()
    assert result.publication.report_bytes == attempt.report_path.read_bytes()
    assert result.publication.manifest.raw.byte_length == len(
        result.publication.raw_bytes
    )


def test_no_overwrite_rejects_second_publication_without_changes(
    tmp_path: Path,
) -> None:
    storage = PublicationStorage(tmp_path)
    first_attempt, first_result = publish_attempt(
        storage,
        DATE_RANGE,
        RUN_ID_1,
    )
    old_manifest = first_result.publication.manifest_bytes
    old_raw = first_attempt.raw_path.read_bytes()
    old_report = first_attempt.report_path.read_bytes()

    with storage.acquire_lock(DATE_RANGE) as lock:
        second_attempt = create_complete_attempt(
            storage,
            DATE_RANGE,
            RUN_ID_2,
            lock=lock,
        )
        with pytest.raises(PublicationExistsError):
            storage.publish(
                second_attempt,
                application_version="0.5.0",
                lock=lock,
                published_at=PUBLISHED_AT,
            )

    visible = storage.read_publication(DATE_RANGE)
    assert visible is not None
    assert visible.manifest_bytes == old_manifest
    assert first_attempt.raw_path.read_bytes() == old_raw
    assert first_attempt.report_path.read_bytes() == old_report


def test_overwrite_advances_manifest_and_preserves_old_attempt_bytes(
    tmp_path: Path,
) -> None:
    storage = PublicationStorage(tmp_path)
    first_attempt, _ = publish_attempt(storage, DATE_RANGE, RUN_ID_1)
    old_raw = first_attempt.raw_path.read_bytes()
    old_report = first_attempt.report_path.read_bytes()

    second_attempt, result = publish_attempt(
        storage,
        DATE_RANGE,
        RUN_ID_2,
        overwrite=True,
        markdown="new report\n",
    )

    assert result.publication.manifest.run_id == RUN_ID_2
    assert result.publication.raw_path == second_attempt.raw_path
    assert result.publication.report_path == second_attempt.report_path
    assert first_attempt.raw_path.read_bytes() == old_raw
    assert first_attempt.report_path.read_bytes() == old_report


def test_reader_keeps_one_manifest_snapshot_across_overwrite(
    tmp_path: Path,
) -> None:
    storage = PublicationStorage(tmp_path)
    first_attempt, _ = publish_attempt(
        storage,
        DATE_RANGE,
        RUN_ID_1,
        markdown="old report\n",
    )
    old_snapshot = storage.read_publication(DATE_RANGE)
    assert old_snapshot is not None

    publish_attempt(
        storage,
        DATE_RANGE,
        RUN_ID_2,
        overwrite=True,
        markdown="new report\n",
    )
    new_snapshot = storage.read_publication(DATE_RANGE)

    assert new_snapshot is not None
    assert old_snapshot.manifest.run_id == RUN_ID_1
    assert old_snapshot.raw_path == first_attempt.raw_path
    assert old_snapshot.report_bytes == b"old report\n"
    assert new_snapshot.manifest.run_id == RUN_ID_2
    assert new_snapshot.report_bytes == b"new report\n"


@pytest.mark.parametrize("artifact", ["raw", "report"])
def test_attempt_write_failure_does_not_change_existing_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    storage = PublicationStorage(tmp_path)
    _, first = publish_attempt(storage, DATE_RANGE, RUN_ID_1)

    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = storage.allocate_attempt(
            DATE_RANGE,
            lock=lock,
            run_id=RUN_ID_2,
        )
        original_fsync = storage_module.os.fsync
        injected = False

        def fail_first_sync(descriptor: int) -> None:
            nonlocal injected
            if not injected:
                injected = True
                raise OSError("injected write failure")
            original_fsync(descriptor)

        monkeypatch.setattr(storage_module.os, "fsync", fail_first_sync)
        with pytest.raises(StorageError, match="Could not write"):
            if artifact == "raw":
                storage.write_raw(attempt, make_run(), lock=lock)
            else:
                storage.write_report(attempt, "report\n", lock=lock)

    visible = storage.read_publication(DATE_RANGE)
    assert visible is not None
    assert visible.manifest_bytes == first.publication.manifest_bytes


def test_incomplete_attempt_cannot_be_published(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)

    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = storage.allocate_attempt(
            DATE_RANGE,
            lock=lock,
            run_id=RUN_ID_1,
        )
        storage.write_raw(attempt, make_run(), lock=lock)
        with pytest.raises(AttemptIncompleteError):
            storage.publish(
                attempt,
                application_version="0.5.0",
                lock=lock,
                published_at=PUBLISHED_AT,
            )

    assert storage.read_publication(DATE_RANGE) is None


@pytest.mark.parametrize("failure", ["temp_write", "replace", "interrupt"])
def test_precommit_failure_preserves_old_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    storage = PublicationStorage(tmp_path)
    first_attempt, first = publish_attempt(storage, DATE_RANGE, RUN_ID_1)
    old_manifest = first.publication.manifest_bytes
    old_raw = first_attempt.raw_path.read_bytes()
    old_report = first_attempt.report_path.read_bytes()

    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = create_complete_attempt(
            storage,
            DATE_RANGE,
            RUN_ID_2,
            lock=lock,
        )
        if failure == "temp_write":
            original_fsync = storage_module.os.fsync
            injected = False

            def fail_temp_sync(descriptor: int) -> None:
                nonlocal injected
                if not injected:
                    injected = True
                    raise OSError("temp file sync failed")
                original_fsync(descriptor)

            monkeypatch.setattr(
                storage_module.os,
                "fsync",
                fail_temp_sync,
            )
        elif failure == "replace":
            monkeypatch.setattr(
                storage_module.os,
                "replace",
                lambda *args: (_ for _ in ()).throw(OSError("replace failed")),
            )
        else:
            monkeypatch.setattr(
                storage_module.os,
                "replace",
                lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()),
            )

        expected_error = (
            PublicationCommitInterrupted
            if failure == "interrupt"
            else PublicationCommitError
        )
        with pytest.raises(expected_error) as exc_info:
            storage.publish(
                attempt,
                application_version="0.5.0",
                lock=lock,
                overwrite=True,
                published_at=PUBLISHED_AT,
            )
        assert exc_info.value.state == "not_published"
        assert exc_info.value.durability == "not_applicable"

    visible = storage.read_publication(DATE_RANGE)
    assert visible is not None
    assert visible.manifest_bytes == old_manifest
    assert first_attempt.raw_path.read_bytes() == old_raw
    assert first_attempt.report_path.read_bytes() == old_report


def test_precommit_failure_without_old_publication_leaves_no_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = PublicationStorage(tmp_path)

    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = create_complete_attempt(
            storage,
            DATE_RANGE,
            RUN_ID_1,
            lock=lock,
        )
        monkeypatch.setattr(
            storage_module.os,
            "replace",
            lambda *args: (_ for _ in ()).throw(OSError("replace failed")),
        )
        with pytest.raises(PublicationCommitError) as exc_info:
            storage.publish(
                attempt,
                application_version="0.5.0",
                lock=lock,
                published_at=PUBLISHED_AT,
            )

    assert exc_info.value.state == "not_published"
    assert storage.read_publication(DATE_RANGE) is None


@pytest.mark.parametrize("failure", ["replace_then_error", "directory_sync"])
def test_post_replace_failure_reports_visible_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    storage = PublicationStorage(tmp_path)
    publish_attempt(storage, DATE_RANGE, RUN_ID_1)

    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = create_complete_attempt(
            storage,
            DATE_RANGE,
            RUN_ID_2,
            lock=lock,
        )
        if failure == "replace_then_error":
            original_replace = storage_module.os.replace

            def replace_then_error(source: Path, target: Path) -> None:
                original_replace(source, target)
                raise OSError("failure after replace")

            monkeypatch.setattr(storage_module.os, "replace", replace_then_error)
        else:
            original_fsync = storage_module.os.fsync

            def fail_directory_sync(descriptor: int) -> None:
                if storage_module.stat.S_ISDIR(
                    storage_module.os.fstat(descriptor).st_mode
                ):
                    raise OSError("directory sync failed")
                original_fsync(descriptor)

            monkeypatch.setattr(
                storage_module.os,
                "fsync",
                fail_directory_sync,
            )

        with pytest.raises(PublicationCommitError) as exc_info:
            storage.publish(
                attempt,
                application_version="0.5.0",
                lock=lock,
                overwrite=True,
                published_at=PUBLISHED_AT,
            )

        assert exc_info.value.state == "published"
        assert exc_info.value.durability == "unconfirmed"
        assert exc_info.value.publication is not None
        assert exc_info.value.publication.manifest.run_id == RUN_ID_2

    visible = storage.read_publication(DATE_RANGE)
    assert visible is not None
    assert visible.manifest.run_id == RUN_ID_2


def test_keyboard_interrupt_after_replace_reports_visible_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = PublicationStorage(tmp_path)
    publish_attempt(storage, DATE_RANGE, RUN_ID_1)

    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = create_complete_attempt(
            storage,
            DATE_RANGE,
            RUN_ID_2,
            lock=lock,
        )
        original_replace = storage_module.os.replace

        def replace_then_interrupt(source: Path, target: Path) -> None:
            original_replace(source, target)
            raise KeyboardInterrupt

        monkeypatch.setattr(storage_module.os, "replace", replace_then_interrupt)
        with pytest.raises(PublicationCommitInterrupted) as exc_info:
            storage.publish(
                attempt,
                application_version="0.5.0",
                lock=lock,
                overwrite=True,
                published_at=PUBLISHED_AT,
            )

        assert exc_info.value.state == "published"
        assert exc_info.value.publication is not None
        assert exc_info.value.publication.manifest.run_id == RUN_ID_2


def test_ambiguous_post_failure_manifest_is_reported_as_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = PublicationStorage(tmp_path)
    publish_attempt(storage, DATE_RANGE, RUN_ID_1)

    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = create_complete_attempt(
            storage,
            DATE_RANGE,
            RUN_ID_2,
            lock=lock,
        )

        def replace_with_invalid_then_error(source: Path, target: Path) -> None:
            target.write_text("indeterminate", encoding="utf-8")
            source.unlink()
            raise OSError("ambiguous replacement failure")

        monkeypatch.setattr(
            storage_module.os,
            "replace",
            replace_with_invalid_then_error,
        )
        with pytest.raises(PublicationCommitError) as exc_info:
            storage.publish(
                attempt,
                application_version="0.5.0",
                lock=lock,
                overwrite=True,
                published_at=PUBLISHED_AT,
            )

        assert exc_info.value.state == "unknown"
        assert exc_info.value.durability == "unconfirmed"
        assert exc_info.value.publication is None

    with pytest.raises(InvalidPublicationError):
        storage.read_publication(DATE_RANGE)


def test_missing_and_invalid_manifest_are_distinct(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)
    assert storage.read_publication(DATE_RANGE) is None

    target = manifest_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text("not json", encoding="utf-8")

    with pytest.raises(InvalidPublicationError, match="malformed"):
        storage.read_publication(DATE_RANGE)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update(schema_version=2), "malformed"),
        (lambda data: data.update(schema_version="1"), "malformed"),
        (lambda data: data.update(extra_field=True), "malformed"),
        (lambda data: data.pop("run_id"), "malformed"),
        (
            lambda data: data["date_range"].update(extra=True),
            "malformed",
        ),
        (
            lambda data: data["raw"].update(sha256="ABC"),
            "malformed",
        ),
        (
            lambda data: data["raw"].update(filename=f"{RUN_ID_2}.json"),
            "malformed",
        ),
    ],
)
def test_manifest_strictly_rejects_unsupported_or_ambiguous_fields(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    storage = PublicationStorage(tmp_path)
    _, result = publish_attempt(storage, DATE_RANGE, RUN_ID_1)
    payload = json.loads(result.publication.manifest_bytes)
    mutation(payload)
    result.publication.manifest_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(InvalidPublicationError, match=message):
        storage.read_publication(DATE_RANGE)


def test_manifest_range_must_match_manifest_filename(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)
    _, result = publish_attempt(storage, DATE_RANGE, RUN_ID_1)
    wrong_path = manifest_path(tmp_path, SAME_WEEK_RANGE)
    wrong_path.parent.mkdir(parents=True, exist_ok=True)
    wrong_path.write_bytes(result.publication.manifest_bytes)

    with pytest.raises(InvalidPublicationError, match="date range"):
        storage.read_publication(SAME_WEEK_RANGE)


@pytest.mark.parametrize("artifact", ["raw", "report"])
@pytest.mark.parametrize("damage", ["missing", "tampered"])
def test_reader_rejects_missing_or_tampered_artifact(
    tmp_path: Path,
    artifact: str,
    damage: str,
) -> None:
    storage = PublicationStorage(tmp_path)
    _, result = publish_attempt(storage, DATE_RANGE, RUN_ID_1)
    path = (
        result.publication.raw_path
        if artifact == "raw"
        else result.publication.report_path
    )
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"tampered")

    with pytest.raises(InvalidPublicationError):
        storage.read_publication(DATE_RANGE)


def test_reader_returns_the_same_bytes_that_were_digest_checked(
    tmp_path: Path,
) -> None:
    storage = PublicationStorage(tmp_path)
    _, result = publish_attempt(
        storage,
        DATE_RANGE,
        RUN_ID_1,
        markdown="authenticated bytes\n",
    )
    snapshot = storage.read_publication(DATE_RANGE)
    assert snapshot is not None

    snapshot.report_path.write_text("changed later\n", encoding="utf-8")

    assert snapshot.report_bytes == b"authenticated bytes\n"
    with pytest.raises(InvalidPublicationError):
        storage.read_publication(DATE_RANGE)


def test_manifest_symlink_is_rejected_not_treated_as_missing(
    tmp_path: Path,
) -> None:
    storage = PublicationStorage(tmp_path)
    target = manifest_path(tmp_path)
    target.parent.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    target.symlink_to(outside)

    with pytest.raises(InvalidPublicationError):
        storage.read_publication(DATE_RANGE)


def test_artifact_symlink_is_rejected(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)
    _, result = publish_attempt(storage, DATE_RANGE, RUN_ID_1)
    report_path = result.publication.report_path
    report_bytes = report_path.read_bytes()
    report_path.unlink()
    outside = tmp_path / "outside.md"
    outside.write_bytes(report_bytes)
    report_path.symlink_to(outside)

    with pytest.raises(InvalidPublicationError):
        storage.read_publication(DATE_RANGE)


def test_managed_subdirectory_symlink_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    storage = PublicationStorage(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    raw_parent = root / "data" / "raw"
    raw_parent.parent.mkdir(parents=True)
    raw_parent.symlink_to(outside, target_is_directory=True)

    with storage.acquire_lock(DATE_RANGE) as lock:
        with pytest.raises(UnsafeStoragePathError, match="symbolic link"):
            storage.allocate_attempt(
                DATE_RANGE,
                lock=lock,
                run_id=RUN_ID_1,
            )


def test_storage_root_symlink_is_rejected(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    with pytest.raises(UnsafeStoragePathError, match="root"):
        PublicationStorage(linked)


def test_nonregular_artifact_is_rejected(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)

    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = storage.allocate_attempt(
            DATE_RANGE,
            lock=lock,
            run_id=RUN_ID_1,
        )
        attempt.raw_path.mkdir()
        storage.write_report(attempt, "report\n", lock=lock)
        with pytest.raises(AttemptIncompleteError):
            storage.publish(
                attempt,
                application_version="0.5.0",
                lock=lock,
                published_at=PUBLISHED_AT,
            )


def test_forged_attempt_paths_are_rejected(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)

    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = storage.allocate_attempt(
            DATE_RANGE,
            lock=lock,
            run_id=RUN_ID_1,
        )
        forged = replace(attempt, raw_path=tmp_path.parent / "outside.json")
        with pytest.raises(UnsafeStoragePathError, match="derived layout"):
            storage.write_raw(forged, make_run(), lock=lock)


def test_mutating_methods_require_matching_held_lock(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)
    other_range = DateRange(start=date(2026, 9, 1), end=date(2026, 9, 7))

    with storage.acquire_lock(other_range) as wrong_lock:
        with pytest.raises(PublicationLockError, match="exact date range"):
            storage.allocate_attempt(
                DATE_RANGE,
                lock=wrong_lock,
                run_id=RUN_ID_1,
            )

    released = storage.acquire_lock(DATE_RANGE)
    released.release()
    with pytest.raises(PublicationLockError, match="held lock"):
        storage.allocate_attempt(
            DATE_RANGE,
            lock=released,
            run_id=RUN_ID_1,
        )


def test_lock_from_different_normalized_root_is_rejected(tmp_path: Path) -> None:
    first = PublicationStorage(tmp_path / "first")
    second = PublicationStorage(tmp_path / "second")

    with first.acquire_lock(DATE_RANGE) as lock:
        with pytest.raises(PublicationLockError):
            second.allocate_attempt(
                DATE_RANGE,
                lock=lock,
                run_id=RUN_ID_1,
            )


def test_invalid_existing_manifest_is_not_repaired_by_overwrite(
    tmp_path: Path,
) -> None:
    storage = PublicationStorage(tmp_path)
    target = manifest_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text("invalid", encoding="utf-8")

    with storage.acquire_lock(DATE_RANGE) as lock:
        attempt = create_complete_attempt(
            storage,
            DATE_RANGE,
            RUN_ID_1,
            lock=lock,
        )
        with pytest.raises(InvalidPublicationError):
            storage.publish(
                attempt,
                application_version="0.5.0",
                lock=lock,
                overwrite=True,
                published_at=PUBLISHED_AT,
            )

    assert target.read_text(encoding="utf-8") == "invalid"
