# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.store_lock: one process at a time holds a dashboard store, through an fcntl.flock on <DATA_DIR>/dashboard.lock."""

import fcntl
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from solar_challenge.web.store_lock import (
    StoreLock,
    StoreLocked,
    StoreLockError,
    StoreLockUnsupported,
    acquire_store_lock,
)

HOLD = """
import sys
from pathlib import Path

from solar_challenge.web.store_lock import acquire_store_lock

acquire_store_lock(Path(sys.argv[1]))
print("held", flush=True)
sys.stdin.read()
"""


def _names_pid(message: str, lock_path: Path, pid: int) -> bool:
    """Whether *message* holds *pid* as a whole number outside the text of *lock_path*, whose tmp directory names hold digits too."""
    return re.search(rf"(?<!\d){pid}(?!\d)", message.replace(str(lock_path), "")) is not None


@pytest.fixture
def held(tmp_path: Path) -> Iterator[StoreLock]:
    """This process's lock on the store in tmp_path, released after the test."""
    lock = acquire_store_lock(tmp_path)
    yield lock
    lock.release()


def test_taking_a_stores_lock_records_this_process(held: StoreLock, tmp_path: Path) -> None:
    assert held.path == tmp_path / "dashboard.lock"
    assert held.path.read_text().strip() == str(os.getpid())


@pytest.mark.usefixtures("held")
def test_a_second_take_of_a_held_store_in_this_process_is_refused_naming_the_lock_file_and_this_process(
    tmp_path: Path,
) -> None:
    """What a second create_app on the store in this process meets."""
    lock_path = tmp_path / "dashboard.lock"

    with pytest.raises(StoreLocked) as refused:
        acquire_store_lock(tmp_path)

    assert refused.value.path == lock_path
    assert refused.value.holder_pid == os.getpid()
    assert str(lock_path) in str(refused.value)
    assert _names_pid(str(refused.value), lock_path, os.getpid())


def test_a_store_another_process_holds_is_refused_naming_that_process_and_is_free_once_it_ends(
    tmp_path: Path,
) -> None:
    """The flock ends with its process, although the lock file still names that process."""
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD, str(tmp_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout is not None and holder.stdin is not None
        assert holder.stdout.readline() == "held\n"

        with pytest.raises(StoreLocked) as refused:
            acquire_store_lock(tmp_path)
        assert refused.value.holder_pid == holder.pid

        holder.stdin.close()
        assert holder.wait(timeout=60) == 0
    finally:
        holder.kill()
        holder.wait()

    assert (tmp_path / "dashboard.lock").read_text().strip() == str(holder.pid)
    acquire_store_lock(tmp_path).release()


def test_a_lock_file_a_process_left_behind_does_not_hold_the_store_and_is_overwritten(tmp_path: Path) -> None:
    """The pid left behind is longer than any real pid, so a lock file that kept its tail would show it."""
    (tmp_path / "dashboard.lock").write_text("4194304999\n")

    lock = acquire_store_lock(tmp_path)
    try:
        assert (tmp_path / "dashboard.lock").read_text() == f"{os.getpid()}\n"
    finally:
        lock.release()


def test_a_released_store_can_be_locked_again(tmp_path: Path) -> None:
    acquire_store_lock(tmp_path).release()

    acquire_store_lock(tmp_path).release()


def test_releasing_twice_is_harmless_and_never_closes_a_descriptor_reused_since(tmp_path: Path) -> None:
    """The second store's lock reuses the descriptor number the first released, so a second close of it would free the second store."""
    first = acquire_store_lock(tmp_path / "one")
    first.release()
    second = acquire_store_lock(tmp_path / "two")
    try:
        first.release()

        with pytest.raises(StoreLocked):
            acquire_store_lock(tmp_path / "two")
    finally:
        second.release()


def test_a_missing_store_directory_is_created_and_holds_the_lock_file(tmp_path: Path) -> None:
    store = tmp_path / "home" / ".solar-challenge"

    lock = acquire_store_lock(store)
    try:
        assert lock.path == store / "dashboard.lock"
        assert lock.path.is_file()
    finally:
        lock.release()


@pytest.mark.parametrize("recorded", ["", "not a pid\n"], ids=["empty", "not_a_number"])
def test_a_holder_that_recorded_no_readable_pid_is_refused_naming_the_lock_file(
    recorded: str, tmp_path: Path
) -> None:
    """A holder that has not written its pid yet, or a foreign holder that writes none."""
    lock_path = tmp_path / "dashboard.lock"
    lock_path.write_text(recorded)

    with lock_path.open("r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(StoreLocked) as refused:
            acquire_store_lock(tmp_path)

    assert refused.value.holder_pid is None
    assert str(lock_path) in str(refused.value)


def test_without_fcntl_a_take_is_refused_naming_the_platform_before_it_touches_the_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """As on Windows, which has no fcntl module. The refusal is a StoreLockError, as StoreLocked is: the one type `web start` reports."""
    monkeypatch.setitem(sys.modules, "fcntl", None)
    store = tmp_path / "store"

    with pytest.raises(StoreLockUnsupported) as refused:
        acquire_store_lock(store)

    assert refused.value.platform == sys.platform
    assert sys.platform in str(refused.value)
    assert not store.exists()
    assert isinstance(refused.value, StoreLockError)
    assert issubclass(StoreLocked, StoreLockError)
