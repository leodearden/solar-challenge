# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_pyproject.py, the packaging-metadata contract tests' structured reader of pyproject.toml."""

import pytest
from packaging.version import Version

from tests._pyproject import declared_floor


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
