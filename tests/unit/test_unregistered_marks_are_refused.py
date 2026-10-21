# SPDX-License-Identifier: AGPL-3.0-or-later
"""A module carrying a mark that pyproject.toml does not register fails collection, naming the mark.

Without pyproject's strict_markers, pytest only warns about an unknown mark and
runs the test as if it were unmarked. A misspelt slow leaves the test under
tests/conftest.py's offline guard, and a misspelt usefixtures or skipif does
nothing. So a new mark is registered in pyproject's marker table, or its module
fails collection naming it.

strict_markers is an ini option, not --strict-markers in addopts, so the refusal
holds when addopts are cleared, as dark-factory's serial and confirm reruns
clear them with `-o addopts=`.
"""

from pathlib import Path

import pytest


@pytest.mark.parametrize("pytest_args", [(), ("-o", "addopts=")], ids=["as-configured", "addopts-cleared"])
def test_a_module_carrying_an_unregistered_mark_fails_collection_naming_the_mark(
    pytester_under_root_conftest: pytest.Pytester, project_root: Path, pytest_args: tuple[str, ...]
) -> None:
    """The module is collected in a session of its own, under copies of this project's pyproject.toml and root conftest."""
    pytester_under_root_conftest.makepyprojecttoml((project_root / "pyproject.toml").read_text(encoding="utf-8"))
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
