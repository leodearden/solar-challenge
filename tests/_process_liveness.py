# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whether processes a test expects ended, such as those a killed command started, are gone, ended and reaped."""

import os
import time
from collections.abc import Iterable


def not_gone_within(pids: Iterable[int], seconds: float) -> list[int]:
    """Return those of *pids* whose process is not gone, ended and reaped, within *seconds* of this call."""
    deadline = time.monotonic() + seconds
    existing = [pid for pid in pids if _process_exists(pid)]
    while existing and time.monotonic() < deadline:
        time.sleep(0.01)
        existing = [pid for pid in existing if _process_exists(pid)]
    return existing


def _process_exists(pid: int) -> bool:
    """Return whether a process *pid* exists, a zombie included."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
