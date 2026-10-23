# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_pyproject.py, the packaging-metadata contract tests' structured reader of pyproject.toml and uv.lock."""

from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from tests._pyproject import core_requirements, declared_floor, extra_requirements, locked_versions


def _lock(*entries: dict[str, Any]) -> dict[str, Any]:
    """Return a parsed uv.lock holding *entries* as its [[package]] tables."""
    return {"version": 1, "package": list(entries)}


@pytest.mark.parametrize(
    ("requirements", "floor"),
    [
        pytest.param(
            ["wheel", "Setuptools>=62.3.0"],
            Version("62.3.0"),
            id="names-compare-canonically",
        ),
        pytest.param(
            ["setuptools>=62.3.0,<90,>=77.0.0"],
            Version("77.0.0"),
            id="highest-of-several-lower-bounds",
        ),
        pytest.param(
            ["setuptools_scm>=90.0", "setuptools>=62.3.0"],
            Version("62.3.0"),
            id="other-distributions-ignored",
        ),
    ],
)
def test_declared_floor_is_the_highest_lower_bound_on_the_named_distribution(
    requirements: list[str], floor: Version
) -> None:
    assert declared_floor(requirements, "setuptools") == floor


@pytest.mark.parametrize(
    "requirements",
    [
        pytest.param(["wheel"], id="distribution-not-required"),
        pytest.param(["setuptools<90"], id="no-lower-bound"),
    ],
)
def test_declared_floor_is_none_when_nothing_bounds_the_named_distribution_from_below(
    requirements: list[str],
) -> None:
    assert declared_floor(requirements, "setuptools") is None


@pytest.mark.parametrize(
    ("requirements", "floor"),
    [
        pytest.param(
            ["setuptools>=62.3.0", "setuptools>=77.0.0; python_version >= '3.12'"],
            Version("62.3.0"),
            id="higher-marked-bound-beside-unmarked-ignored",
        ),
        pytest.param(
            ["setuptools>=77.0.0", "setuptools>=62.3.0; python_version < '3.12'"],
            Version("77.0.0"),
            id="lower-marked-bound-beside-unmarked-ignored",
        ),
        pytest.param(
            ["setuptools", "setuptools>=77.0.0; python_version >= '3.12'"],
            None,
            id="marked-bound-beside-unbounded-unmarked-ignored",
        ),
        pytest.param(
            ["setuptools>=77.0.0", "setuptools; python_version < '3.12'"],
            Version("77.0.0"),
            id="unbounded-marked-entry-beside-bounded-unmarked-ignored",
        ),
        pytest.param(
            ["setuptools>=77.0.0; platform_machine != 'armv7l'"],
            Version("77.0.0"),
            id="single-marked-entry-bounds",
        ),
        pytest.param(
            ["setuptools>=77.0.0; python_version >= '3.12'", "setuptools>=62.3.0; python_version < '3.12'"],
            Version("62.3.0"),
            id="complementary-markers-give-lower-bound",
        ),
        pytest.param(
            ["setuptools>=77.0.0; python_version >= '3.12'", "setuptools; python_version < '3.12'"],
            None,
            id="unbounded-marked-entry-voids-floor",
        ),
        pytest.param(
            ["setuptools>=62.3.0", "setuptools>=77.0.0"],
            Version("77.0.0"),
            id="unmarked-duplicates-give-higher-bound",
        ),
    ],
)
def test_declared_floor_is_the_bound_guaranteed_whichever_markers_apply(
    requirements: list[str], floor: Version | None
) -> None:
    assert declared_floor(requirements, "setuptools") == floor


@pytest.mark.parametrize(
    ("lock", "distribution", "versions"),
    [
        pytest.param(
            _lock({"name": "pandas", "version": "3.0.3"}, {"name": "numpy", "version": "2.4.6"}),
            "pandas",
            (Version("3.0.3"),),
            id="one-pin",
        ),
        pytest.param(
            _lock({"name": "pandas", "version": "3.0.3"}, {"name": "pandas", "version": "2.3.3"}),
            "pandas",
            (Version("2.3.3"), Version("3.0.3")),
            id="forked-pins-lowest-first",
        ),
        pytest.param(
            _lock({"name": "pyyaml", "version": "6.0.3"}),
            "PyYAML",
            (Version("6.0.3"),),
            id="names-compare-canonically",
        ),
    ],
)
def test_locked_versions_are_every_release_the_lock_pins_for_the_named_distribution_lowest_first(
    lock: dict[str, Any], distribution: str, versions: tuple[Version, ...]
) -> None:
    assert locked_versions(lock, distribution) == versions


@pytest.mark.parametrize(
    "lock",
    [
        pytest.param(_lock({"name": "numpy", "version": "2.4.6"}), id="distribution-not-locked"),
        pytest.param(_lock({"name": "pandas", "source": {"editable": "."}}), id="versionless-entry-is-no-pin"),
    ],
)
def test_locked_versions_are_empty_when_the_lock_pins_no_release_of_the_named_distribution(
    lock: dict[str, Any],
) -> None:
    assert locked_versions(lock, "pandas") == ()


def test_core_and_extra_requirements_are_the_project_table_s_parsed_requirements_markers_kept(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        "dependencies = [\"pandas>=3.0.3\", \"tzdata>=2025.2; sys_platform == 'win32'\"]\n"
        "[project.optional-dependencies]\n"
        'dev = ["pytest>=9.0.3"]\n'
        'web = ["flask>=3.1.3", "jinja2>=3.1.6"]\n'
        "e2e = [\"playwright>=1.61.0; platform_machine != 'armv7l'\"]\n",
        encoding="utf-8",
    )

    assert core_requirements(tmp_path) == [
        Requirement("pandas>=3.0.3"),
        Requirement("tzdata>=2025.2; sys_platform == 'win32'"),
    ]
    assert extra_requirements(tmp_path, ["e2e", "dev", "web"]) == [
        Requirement("playwright>=1.61.0; platform_machine != 'armv7l'"),
        Requirement("pytest>=9.0.3"),
        Requirement("flask>=3.1.3"),
        Requirement("jinja2>=3.1.6"),
    ]
