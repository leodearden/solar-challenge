# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pytest deprecation fails the test, or the collection, that meets it.

pyproject.toml's dev range admits every later pytest, and each pytest major
release removes features its earlier releases deprecated. pyproject's
filterwarnings turns every PytestDeprecationWarning into an error in each run
that reads its pytest ini. So a deprecated use fails the first run whose pytest
flags it, not a run on the release that removes it.

The filter names the base class, not a PytestRemovedIn<N>Warning. Each of those
exists in only a few releases, and a filter naming a class the running pytest
lacks stops pytest at startup.
"""

import warnings
from pathlib import Path

import pytest


def test_a_pytest_deprecation_fails_the_test_that_meets_it() -> None:
    """A PytestDeprecationWarning raised while a test runs is raised as an error, not recorded."""
    with pytest.raises(pytest.PytestDeprecationWarning, match="a feature pytest will remove"):
        warnings.warn(pytest.PytestDeprecationWarning("a feature pytest will remove"), stacklevel=1)


def test_a_pytest_deprecation_fails_the_collection_that_meets_it(
    pytester_under_root_conftest: pytest.Pytester, project_root: Path
) -> None:
    """A PytestDeprecationWarning raised while a module is collected is a collection error, not recorded.

    Collection is over before any test runs, so the module is collected in a
    session of its own, under copies of this project's pyproject.toml and root conftest.
    """
    pytester_under_root_conftest.makepyprojecttoml((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    module = pytester_under_root_conftest.makepyfile(
        """
        import warnings

        import pytest

        warnings.warn(pytest.PytestDeprecationWarning("a feature pytest will remove"), stacklevel=1)
        """
    )

    result = pytester_under_root_conftest.runpytest_subprocess(module)

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*ERROR collecting*", "*PytestDeprecationWarning: a feature pytest will remove*"])
