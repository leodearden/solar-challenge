# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures both web_jobs test modules request: the Flask test app, and a BlockingSimulation released at teardown.

Nothing here imports Flask, the optional web extra, when the module loads: without
it, each test module's ``pytest.importorskip("flask")`` skips that module, whereas
an import error in this conftest would abort the run.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests._web_app import build_test_app
from tests.unit.web_jobs._fakes import BlockingSimulation

if TYPE_CHECKING:
    from flask import Flask


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with temporary database."""
    return build_test_app(tmp_path)


@pytest.fixture
def blocking_simulation() -> Iterator[BlockingSimulation]:
    """A BlockingSimulation released at teardown, before tests/conftest.py drains the job managers."""
    simulation = BlockingSimulation()
    yield simulation
    simulation.release()
