# SPDX-License-Identifier: AGPL-3.0-or-later
"""A directory the processes of one pytest run share, built once by whichever asks for it first, however the run spreads its tests over xdist workers.

Usage::

    from tests._once_per_run import built_once, run_shared_path

    def _build_the_wheel(out_dir: Path) -> None: ...

    @pytest.fixture(scope="session")
    def wheel_dir(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Path:
        return built_once(run_shared_path(request, tmp_path_factory, "wheel"), _build_the_wheel)  # built by the first worker that asks
"""

import fcntl
import shutil
from collections.abc import Callable
from pathlib import Path


def built_once(directory: Path, build: Callable[[Path], object]) -> Path:
    """Return *directory* once *build* has built it, calling build only if no call, in this process or another, has yet.

    Callers take turns under a flock on a lock file beside *directory*, which the kernel frees when
    its holder closes it or dies, and a marker beside it records that a build returned. *directory*
    is returned only once its marker exists, and the marker is written only after build returned. So
    a build that raised, or whose process was killed, is never handed out: the next call empties
    *directory* and builds it afresh. build must not itself wait on a built_once, in this process or
    another, since that call could be waiting for the lock this one holds.
    """
    directory.parent.mkdir(parents=True, exist_ok=True)
    with open(directory.parent / f"{directory.name}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        built = directory.parent / f"{directory.name}.built"
        if not built.exists():
            if directory.exists():
                shutil.rmtree(directory)
            directory.mkdir()
            build(directory)
            built.touch()
    return directory
