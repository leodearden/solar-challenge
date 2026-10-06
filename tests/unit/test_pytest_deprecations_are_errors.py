# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pytest deprecation fails the test, or the collection, that meets it.

pyproject.toml's dev range admits every later pytest, and each pytest major
release removes features its earlier releases deprecated. pyproject's
filterwarnings turns every PytestDeprecationWarning into an error in each run
that reads its ini: the per-task verify, every offline-lane job, and any run on
a pytest newer than uv.lock's. So a deprecated use fails the first run whose
pytest flags it, not a run on the release that removes it.

The filter names the base class, not a PytestRemovedIn<N>Warning. Each of those
exists in only a few releases, and a filter naming a class the running pytest
lacks stops pytest at startup.
"""

import warnings

import pytest


def test_a_pytest_deprecation_fails_the_test_that_meets_it() -> None:
    """A PytestDeprecationWarning raised while a test runs is raised as an error, not recorded."""
    with pytest.raises(pytest.PytestDeprecationWarning, match="a feature pytest will remove"):
        warnings.warn(pytest.PytestDeprecationWarning("a feature pytest will remove"), stacklevel=1)
