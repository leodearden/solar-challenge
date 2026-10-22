# SPDX-License-Identifier: AGPL-3.0-or-later
"""One process at a time may use a dashboard store, the database and run files under its DATA_DIR.

The lock is a POSIX flock on <DATA_DIR>/dashboard.lock. A flock conflicts across open file
descriptions even within one process, so a second create_app on a store in this process is
refused too (docs/prds/run-store-one-owner.md §3.8, D-S19-10).
"""

import os
import sys
from pathlib import Path

LOCK_FILE_NAME = "dashboard.lock"


class StoreLockError(Exception):
    """This process cannot take a dashboard store's lock; the message says why.

    It is not a ValueError: no request causes it, so it is a start-up refusal, never a refused request.
    """


class StoreLocked(StoreLockError):
    """Another app, in this process or another, holds the store's lock; the message names the lock file and the holder."""

    def __init__(self, path: Path, holder_pid: int | None) -> None:
        holder = "a process that recorded no pid in it" if holder_pid is None else f"process {holder_pid}"
        super().__init__(
            f"The dashboard store is in use: its lock file {path} is held by {holder}. "
            "One process at a time may use a store."
        )
        self.path = path
        self.holder_pid = holder_pid


class StoreLockUnsupported(StoreLockError):
    """This platform has no POSIX flock, so no store lock can be taken on it; the message names the platform."""

    def __init__(self, platform: str) -> None:
        super().__init__(
            f"The dashboard cannot lock its store on platform {platform}: it needs POSIX flock "
            "(Python's fcntl module), which this platform lacks."
        )
        self.platform = platform


class StoreLock:
    """This process's hold on a dashboard store, as acquire_store_lock takes it.

    The hold lasts until release() or the end of the process. Dropping the object does not end it.
    """

    def __init__(self, path: Path, fd: int) -> None:
        self._path = path
        self._fd: int | None = fd

    @property
    def path(self) -> Path:
        """The lock file this process holds."""
        return self._path

    def release(self) -> None:
        """Free the store for another app or process.

        Call it only once this process can no longer write the store: another process's
        recovery would fail a run that a still-running job of this one writes (contract C9).
        Only the first call closes the lock's descriptor, so a later one never closes a
        descriptor number reused since.
        """
        fd, self._fd = self._fd, None
        if fd is not None:
            os.close(fd)


def acquire_store_lock(data_dir: Path) -> StoreLock:
    """Take the lock on the store in *data_dir* for this process, creating the directory if need be, and record this process's pid in the lock file.

    Raises:
        StoreLocked: If an app, in this process or another, holds the store's lock.
        StoreLockUnsupported: If this platform has no fcntl module, before the store is touched.
    """
    try:
        import fcntl
    except ModuleNotFoundError as missing:
        raise StoreLockUnsupported(sys.platform) from missing

    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / LOCK_FILE_NAME
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as held:
            raise StoreLocked(path, _recorded_pid(path)) from held
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{os.getpid()}\n".encode(), 0)
    except BaseException:
        os.close(fd)
        raise
    return StoreLock(path, fd)


def _recorded_pid(lock_path: Path) -> int | None:
    """The pid the lock file at *lock_path* records: its text as a positive whole number, or None when it is unreadable, empty or not one."""
    try:
        pid = int(lock_path.read_bytes())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None
