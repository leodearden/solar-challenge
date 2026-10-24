# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fixtures the web_jobs test modules share: blocking_simulation, a BlockingSimulation released at teardown, and save_gate, a SaveGate opened at teardown.

Nothing here imports Flask, the optional web extra, when the module loads: without
it, each test module's ``pytest.importorskip("flask")`` skips that module, whereas
an import error in this conftest would abort the run.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.unit.web_jobs._fakes import BlockingSimulation, SaveGate


@pytest.fixture
def blocking_simulation() -> Iterator[BlockingSimulation]:
    """A BlockingSimulation released at teardown, before tests/conftest.py drains the job managers."""
    simulation = BlockingSimulation()
    yield simulation
    simulation.release()


@pytest.fixture
def save_gate() -> Iterator[SaveGate]:
    """A SaveGate opened at teardown, before tests/conftest.py drains the job managers, as blocking_simulation is released."""
    gate = SaveGate()
    yield gate
    gate.open()
