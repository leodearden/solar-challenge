# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check that the verify suite passes on the newest releases pyproject.toml's dependency ranges admit.

uv.lock pins every dependency, so the per-task verify and every other lane job
test only the pinned releases. A consumer that installs this package and
re-locks gets the newest releases its declared ranges admit instead. This
module copies the tree, upgrades the copy's uv.lock to those releases, and runs
the orchestrator verify suite there verbatim, on the .python-version pin.
Before the upgrade, the copy's pyproject.toml declares that pin on this host a
uv required environment, so wherever a release has no source distribution, uv
pins there only a release that ships a wheel for it; tests/_required_environment.py
says why. The suite's command is unchanged: only the copy's pyproject.toml
gains that [tool.uv] table, which every uv command in the copy reads. The run
deselects each test tests/_newest_releases_deselections.py names, which the
copy breaks, or may break, by design. An upstream release that breaks this code then files a
fix task before a consumer meets it.

The orchestrator's offline lane runs this module after each merge to main, as
its newest-releases job. tests/conftest.py keeps this directory out of every
default collection, so it runs only when its path is passed explicitly. Its
test is marked slow, the exemption from tests/conftest.py's offline guard,
because uv resolves and downloads the releases from PyPI.

Manual run::

    uv run --locked --extra dev pytest tests/newest_releases -p no:cacheprovider
"""

import shlex
import shutil
import subprocess
import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest

from tests._command_runner import describe_pytest_outcome
from tests._hermetic_checkout import init_hermetic_checkout
from tests._newest_releases_deselections import NEWEST_RELEASES_DESELECTIONS
from tests._repository_paths import REPOSITORY_ROOT
from tests._required_environment import declare_required_environment, pinned_environment
from tests._uv_env import isolated_uv_env
from tests._verify_suite import run_verify_suite
from tests._working_tree import copy_working_tree

pytestmark = pytest.mark.slow

# It exists only so a hung resolution or download fails this test by name.
_UV_TIMEOUT_SECS = 900


def _run(args: list[str], cwd: Path, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    """Run *args* in *cwd*, in *env*, capturing its output as text."""
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=_UV_TIMEOUT_SECS)


def _locked_releases(project: Path) -> frozenset[tuple[str, str]]:
    """Return the name and version of each release *project*'s uv.lock pins."""
    lock = tomllib.loads((project / "uv.lock").read_text(encoding="utf-8"))
    return frozenset((package["name"], package["version"]) for package in lock["package"] if "version" in package)


def _describe_upgrade(pinned: frozenset[tuple[str, str]], upgraded: frozenset[tuple[str, str]], uv_stderr: str) -> str:
    """Say what `uv lock --upgrade` moved past the *pinned* releases: uv's report of the moves, or that it moved none."""
    if upgraded == pinned:
        return (
            "`uv lock --upgrade` moved no release past uv.lock's pins, so this red comes from the tree itself, "
            "not from an upstream release"
        )
    return f"`uv lock --upgrade` moved these past uv.lock's pins:\n{uv_stderr}"


def test_verify_suite_passes_on_the_newest_releases_the_dependency_ranges_admit(tmp_path: Path) -> None:
    """The orchestrator verify suite passes in a copy of this tree whose uv.lock is upgraded to the newest
    releases pyproject.toml's ranges admit, as a consumer that re-locks would install them. For the
    .python-version pin on this host, that is the newest release with a wheel for it wherever a release has no
    source distribution.

    A missing git fails the test rather than skipping it: a skip would leave the
    lane green with nothing checked.

    Before the suite runs, every extra's newest wheels are synced into a
    throwaway environment, deleted once it has put them in uv's cache. The
    suite's own uv probes run offline under tests/conftest.py's guard and sync
    from the copy's upgraded lock, so each wheel it pins for this interpreter
    must already be in uv's cache: the e2e job's collection contract in
    tests/unit/test_offline_lane_contracts.py, for one, needs the e2e extra's
    newest playwright wheel, which nothing else fetches.
    """
    project = copy_working_tree(REPOSITORY_ROOT, tmp_path / "project")
    # So the suite's tests that list the tree's files with git, such as tests/integration/test_external_install.py's, run.
    init_hermetic_checkout(project)
    declare_required_environment(project, pinned_environment(project))

    pinned = _locked_releases(project)
    upgrade = _run(["uv", "lock", "--upgrade"], project, isolated_uv_env(tmp_path / "venv"))
    assert upgrade.returncode == 0, (
        "`uv lock --upgrade` could not resolve the newest releases pyproject.toml's ranges admit; "
        f"if uv could not reach PyPI, retry later; uv's stderr:\n{upgrade.stderr}"
    )
    upgrade_description = _describe_upgrade(pinned, _locked_releases(project), upgrade.stderr)

    every_extra = tmp_path / "every-extra"
    fetched = _run(
        ["uv", "sync", "--locked", "--all-extras", "--no-install-project"], project, isolated_uv_env(every_extra)
    )
    shutil.rmtree(every_extra, ignore_errors=True)
    assert fetched.returncode == 0, (
        "`uv sync --locked --all-extras --no-install-project` could not install the newest releases of every "
        f"extra into a scratch environment; uv's stderr:\n{fetched.stderr}"
    )

    env = {
        **isolated_uv_env(tmp_path / "venv"),
        "PYTEST_ADDOPTS": shlex.join(f"--deselect={deselected.node_id}" for deselected in NEWEST_RELEASES_DESELECTIONS),
    }
    result = run_verify_suite(project, env, variant="on the newest releases")

    assert result.returncode == 0, (
        "the verify suite failed on the newest releases pyproject.toml's dependency ranges admit, "
        f"the releases a consumer that re-locks installs; {upgrade_description}\n{describe_pytest_outcome(result)}"
    )
