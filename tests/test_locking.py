from datetime import date
import errno
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
from typing import Any

import pytest

import ai_weekly_agent.main as main_module
import ai_weekly_agent.storage as storage_module
from ai_weekly_agent.config import AppConfig
from ai_weekly_agent.models import DateRange
from ai_weekly_agent.research import ResearchError
from ai_weekly_agent.storage import (
    PublicationLockBusyError,
    PublicationLockError,
    PublicationLockUnsupportedError,
    PublicationStorage,
)


DATE_RANGE = DateRange(start=date(2026, 9, 13), end=date(2026, 9, 19))
OTHER_RANGE = DateRange(start=date(2026, 9, 6), end=date(2026, 9, 12))


def _date_range(start: str, end: str) -> DateRange:
    return DateRange(start=date.fromisoformat(start), end=date.fromisoformat(end))


def _lock_worker(
    root: str,
    start: str,
    end: str,
    connection: Connection,
    release_event: Any | None,
) -> None:
    storage = PublicationStorage(root)
    try:
        lock = storage.acquire_lock(_date_range(start, end))
    except PublicationLockBusyError:
        connection.send("busy")
        connection.close()
        return
    except BaseException as exc:
        connection.send(f"error:{type(exc).__name__}")
        connection.close()
        return

    with lock:
        connection.send("acquired")
        if release_event is not None:
            if not release_event.wait(timeout=10):
                connection.send("release-timeout")
    connection.close()


def _abrupt_exit_worker(
    root: str,
    start: str,
    end: str,
    connection: Connection,
    exit_event: Any,
) -> None:
    storage = PublicationStorage(root)
    storage.acquire_lock(_date_range(start, end))
    connection.send("acquired")
    if not exit_event.wait(timeout=10):
        connection.send("exit-timeout")
        connection.close()
        return
    connection.close()
    os._exit(0)


def _cli_worker(root: str, connection: Connection) -> None:
    os.chdir(root)
    try:
        result = main_module.main([
            "--start",
            DATE_RANGE.start.isoformat(),
            "--end",
            DATE_RANGE.end.isoformat(),
        ])
        connection.send(("result", result))
    except BaseException as exc:
        connection.send(("error", type(exc).__name__))
    finally:
        connection.close()


def _receive(connection: Connection) -> Any:
    assert connection.poll(10), "child process did not respond before timeout"
    return connection.recv()


def _join_or_terminate(process: multiprocessing.Process) -> None:
    process.join(timeout=10)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        pytest.fail("child process did not exit before timeout")


def test_two_processes_competing_for_same_range_only_one_acquires(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("fork")
    release_event = context.Event()
    holder_parent, holder_child = context.Pipe(duplex=False)
    contender_parent, contender_child = context.Pipe(duplex=False)
    holder = context.Process(
        target=_lock_worker,
        args=(
            str(tmp_path),
            DATE_RANGE.start.isoformat(),
            DATE_RANGE.end.isoformat(),
            holder_child,
            release_event,
        ),
    )
    contender = context.Process(
        target=_lock_worker,
        args=(
            str(tmp_path),
            DATE_RANGE.start.isoformat(),
            DATE_RANGE.end.isoformat(),
            contender_child,
            None,
        ),
    )
    try:
        holder.start()
        holder_child.close()
        assert _receive(holder_parent) == "acquired"

        contender.start()
        contender_child.close()
        assert _receive(contender_parent) == "busy"
    finally:
        release_event.set()
        if holder.pid is not None:
            _join_or_terminate(holder)
        if contender.pid is not None:
            _join_or_terminate(contender)
        holder_parent.close()
        contender_parent.close()

    assert holder.exitcode == 0
    assert contender.exitcode == 0


def test_two_real_cli_processes_contend_before_configuration_or_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = multiprocessing.get_context("fork")
    release_client = context.Event()
    client_entered = context.Event()
    config_calls = context.Value("i", 0)
    client_calls = context.Value("i", 0)
    pipeline_calls = context.Value("i", 0)

    def fake_load_config() -> AppConfig:
        with config_calls.get_lock():
            config_calls.value += 1
        return AppConfig(
            openai_api_key="offline-test-key",
            openai_model="offline-test-model",
        )

    def blocking_fake_client(_config: AppConfig) -> object:
        with client_calls.get_lock():
            client_calls.value += 1
        client_entered.set()
        if not release_client.wait(timeout=10):
            raise RuntimeError("test client barrier timed out")
        return object()

    def fail_at_fake_pipeline(*_args: object, **_kwargs: object) -> None:
        with pipeline_calls.get_lock():
            pipeline_calls.value += 1
        raise ResearchError("offline controlled stop")

    monkeypatch.setattr(main_module, "load_config", fake_load_config)
    monkeypatch.setattr(main_module, "create_openai_client", blocking_fake_client)
    monkeypatch.setattr(
        main_module,
        "research_all_categories",
        fail_at_fake_pipeline,
    )

    first_parent, first_child = context.Pipe(duplex=False)
    second_parent, second_child = context.Pipe(duplex=False)
    first = context.Process(target=_cli_worker, args=(str(tmp_path), first_child))
    second = context.Process(target=_cli_worker, args=(str(tmp_path), second_child))
    try:
        first.start()
        first_child.close()
        assert client_entered.wait(timeout=10), "first CLI never reached fake client"

        second.start()
        second_child.close()
        assert _receive(second_parent) == ("result", 1)
        _join_or_terminate(second)
        assert second.exitcode == 0
        assert config_calls.value == 1
        assert client_calls.value == 1
        assert pipeline_calls.value == 0

        release_client.set()
        assert _receive(first_parent) == ("result", 1)
    finally:
        release_client.set()
        if first.pid is not None:
            _join_or_terminate(first)
        if second.pid is not None and second.is_alive():
            _join_or_terminate(second)
        first_parent.close()
        second_parent.close()

    assert first.exitcode == 0
    assert config_calls.value == 1
    assert client_calls.value == 1
    assert pipeline_calls.value == 1
    attempts = list(
        (
            tmp_path
            / "data"
            / "runs"
            / "attempts"
            / "2026-09-13_to_2026-09-19"
        ).glob("*")
    )
    assert len(attempts) == 1
    with PublicationStorage(tmp_path).acquire_lock(DATE_RANGE):
        pass


def test_different_ranges_can_be_locked_independently(tmp_path: Path) -> None:
    context = multiprocessing.get_context("fork")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_lock_worker,
        args=(
            str(tmp_path),
            OTHER_RANGE.start.isoformat(),
            OTHER_RANGE.end.isoformat(),
            child,
            None,
        ),
    )
    storage = PublicationStorage(tmp_path)

    try:
        with storage.acquire_lock(DATE_RANGE):
            process.start()
            child.close()
            assert _receive(parent) == "acquired"
    finally:
        if process.pid is not None:
            _join_or_terminate(process)
        parent.close()

    assert process.exitcode == 0


def test_lock_releases_after_normal_and_exceptional_exit(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)

    with storage.acquire_lock(DATE_RANGE):
        pass
    with storage.acquire_lock(DATE_RANGE):
        with pytest.raises(RuntimeError, match="primary"):
            with storage.acquire_lock(OTHER_RANGE):
                raise RuntimeError("primary")
    with storage.acquire_lock(OTHER_RANGE):
        pass


def test_controlled_process_termination_releases_kernel_lock(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("fork")
    release_event = context.Event()
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_abrupt_exit_worker,
        args=(
            str(tmp_path),
            DATE_RANGE.start.isoformat(),
            DATE_RANGE.end.isoformat(),
            child,
            release_event,
        ),
    )
    try:
        process.start()
        child.close()
        assert _receive(parent) == "acquired"
        release_event.set()
        process.join(timeout=10)
        assert not process.is_alive()
        assert process.exitcode == 0

        storage = PublicationStorage(tmp_path)
        with storage.acquire_lock(DATE_RANGE):
            pass
    finally:
        release_event.set()
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)
        parent.close()


def test_lock_file_persists_and_does_not_mean_lock_is_held(
    tmp_path: Path,
) -> None:
    storage = PublicationStorage(tmp_path)
    lock = storage.acquire_lock(DATE_RANGE)
    path = lock.path
    lock.release()

    assert path.is_file()
    with storage.acquire_lock(DATE_RANGE) as reacquired:
        assert reacquired.path == path
        assert path.is_file()
    assert path.is_file()


def test_unsupported_fcntl_fails_without_unlocked_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = PublicationStorage(tmp_path)

    def unsupported():
        raise PublicationLockUnsupportedError("unsupported")

    monkeypatch.setattr(storage_module, "_import_fcntl", unsupported)

    with pytest.raises(PublicationLockUnsupportedError, match="unsupported"):
        storage.acquire_lock(DATE_RANGE)


@pytest.mark.parametrize("error_number", [errno.EIO, errno.EACCES])
def test_noncontention_lock_open_error_is_not_reported_as_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_number: int,
) -> None:
    storage = PublicationStorage(tmp_path)

    def fail_open(path: Path) -> int:
        raise OSError(error_number, "injected lock-open failure")

    monkeypatch.setattr(storage_module, "_open_lock_file", fail_open)

    with pytest.raises(PublicationLockError, match="Could not open") as exc_info:
        storage.acquire_lock(DATE_RANGE)

    assert not isinstance(exc_info.value, PublicationLockBusyError)


def test_importing_storage_does_not_require_fcntl_at_import_time() -> None:
    assert callable(storage_module._import_fcntl)
