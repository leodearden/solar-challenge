# SPDX-License-Identifier: AGPL-3.0-or-later
"""The heap frozen once per process, after the first pytest session's collection, so the run's full collections skip it.

gc.freeze() moves every object the collector tracks into a permanent generation, which no
collection scans or frees. A session nested in a running one, such as an in-process pytester
session under a copy of the root conftest, collects in the same process mid-run. Freezing
again there would freeze the running tests' objects, and the garbage they become would never
be freed. The once is kept here, not in the conftest, since each copy of the conftest is a
module of its own.

Usage::

    from tests._heap_freeze import freeze_the_heap_once

    def pytest_collection_finish(session: pytest.Session) -> None:
        freeze_the_heap_once()
"""

from __future__ import annotations

import functools
import gc


@functools.cache
def freeze_the_heap_once() -> None:
    """Collect the garbage, then freeze every object left, the first time this process calls this; later calls do nothing."""
    gc.collect()
    gc.freeze()
