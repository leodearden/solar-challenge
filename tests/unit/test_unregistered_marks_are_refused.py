# SPDX-License-Identifier: AGPL-3.0-or-later
"""A module carrying a mark that pyproject.toml does not register fails collection, naming the mark.

Without pyproject's strict_markers, pytest only warns about an unknown mark and
runs the test as if it were unmarked. A misspelt slow leaves the test under
tests/conftest.py's offline guard, and a misspelt usefixtures or skipif does
nothing. So a new mark is registered in pyproject's marker table, or its module
fails collection naming it.

strict_markers is an ini option, not --strict-markers in addopts, so the refusal
holds when addopts are cleared, as dark-factory's serial recovery run clears
them with `-o addopts=`.
"""

import pytest


@pytest.mark.usefixtures("pytester_sessions_read_the_project_ini")
@pytest.mark.parametrize("pytest_args", [(), ("-o", "addopts=")], ids=["as-configured", "addopts-cleared"])
def test_a_module_carrying_an_unregistered_mark_fails_collection_naming_the_mark(
    pytester_under_root_conftest: pytest.Pytester, pytest_args: tuple[str, ...]
) -> None:
    """The module is collected in a session of its own, under copies of this project's pyproject.toml and root conftest."""
    module = pytester_under_root_conftest.makepyfile(
        """
        import pytest


        @pytest.mark.slwo
        def test_needs_a_live_service():
            pass
        """
    )

    result = pytester_under_root_conftest.runpytest_subprocess(*pytest_args, module)

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*ERROR collecting*", "*'slwo'*"])


@pytest.mark.usefixtures("pytester_sessions_read_the_project_ini")
def test_the_xdist_group_mark_collects_with_pytest_xdist_disabled(
    pytester_under_root_conftest: pytest.Pytester,
) -> None:
    """With xdist disabled, as dark-factory's serial recovery run disables it, the plugin that registers xdist_group is gone, so under strict_markers the mark resolves only if pyproject.toml registers it."""
    module = pytester_under_root_conftest.makepyfile(
        """
        import pytest


        @pytest.mark.xdist_group("shared")
        def test_shares_a_worker_with_its_group():
            pass
        """
    )

    result = pytester_under_root_conftest.runpytest_subprocess("-p", "no:xdist", "-o", "addopts=", module)

    result.assert_outcomes(passed=1)
