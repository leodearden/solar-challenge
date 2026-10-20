# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fixture the web_jobs test modules share: blocking_simulation, a BlockingSimulation released at teardown.

Nothing here imports Flask, the optional web extra, when the module loads: without
it, each test module's ``pytest.importorskip("flask")`` skips that module, whereas
an import error in this conftest would abort the run.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.unit.web_jobs._fakes import BlockingSimulation


@pytest.fixture
def blocking_simulation() -> Iterator[BlockingSimulation]:
    """A BlockingSimulation released at teardown, before tests/conftest.py drains the job managers."""
    simulation = BlockingSimulation()
    yield simulation
    simulation.release()
