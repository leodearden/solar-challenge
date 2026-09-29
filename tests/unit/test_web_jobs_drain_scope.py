"""Pins that the per-test JobManager drain (tests/conftest.py) stops only the managers a test created.

These tests run in definition order and share module-scoped state on purpose:
each one observes what an earlier test's teardown did.
"""

from collections.abc import Generator
from pathlib import Path

import pytest
pytest.importorskip("flask")
from flask import Flask

from solar_challenge.web.app import create_app
from solar_challenge.web.shared import get_job_manager

HOME_JOB = {"pv_kw": 4.0, "battery_kwh": 0, "occupants": 3, "location": "bristol", "days": 1}


def _build_app(data_dir: Path) -> Flask:
    return create_app(
        test_config={
            "TESTING": True,
            "SECRET_KEY": "drain-scope-test-secret",
            "DATABASE": str(data_dir / "test.db"),
            "DATA_DIR": str(data_dir),
        }
    )


@pytest.fixture(scope="module")
def module_app(tmp_path_factory: pytest.TempPathFactory) -> Generator[Flask, None, None]:
    """A module-scoped app; like every broader-scoped app fixture, it shuts down its own JobManager."""
    app = _build_app(tmp_path_factory.mktemp("module_app"))
    yield app
    with app.app_context():
        get_job_manager().shutdown(wait=True)


@pytest.fixture(scope="module")
def apps_built_inside_earlier_tests() -> list[Flask]:
    return []


def test_an_earlier_test_uses_the_module_app_and_builds_its_own_app(
    module_app: Flask,
    apps_built_inside_earlier_tests: list[Flask],
    tmp_path: Path,
) -> None:
    assert module_app.test_client().get("/").status_code == 200

    apps_built_inside_earlier_tests.append(_build_app(tmp_path))


def test_module_app_still_accepts_a_job_after_an_earlier_tests_teardown(module_app: Flask) -> None:
    response = module_app.test_client().post("/api/simulate/home", json=HOME_JOB)

    assert response.status_code == 201


def test_an_app_built_inside_an_earlier_test_was_drained_at_its_teardown(
    apps_built_inside_earlier_tests: list[Flask],
) -> None:
    assert apps_built_inside_earlier_tests, (
        "no app was recorded: this test observes the teardown of "
        "test_an_earlier_test_uses_the_module_app_and_builds_its_own_app, so run the whole module"
    )
    app_from_earlier_test = apps_built_inside_earlier_tests[0]

    with pytest.raises(RuntimeError, match="shutdown"):
        app_from_earlier_test.test_client().post("/api/simulate/home", json=HOME_JOB)
