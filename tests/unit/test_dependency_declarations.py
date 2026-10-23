# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dependency declaration contract tests on the real tree.

Each source scope of tests/_declared_dependencies.py, which states the
declared-dependency contract, may import only what [project].dependencies and
the scope's extras declare, and in the package each ImportError guard must
guard a distribution its scope does not declare.  This module judges the
scopes whose extras exclude e2e.  The scopes needing e2e are judged in
tests/e2e/test_declared_dependencies.py by the offline lane's e2e job, the one
run that installs that extra, and
test_the_e2e_lane_job_judges_each_scope_that_needs_the_e2e_extra pins that the
job collects a case for each.

No core dependency may request an extra its distribution does not provide.  No
declared requirement may carry an environment marker that holds only on Python
minors requires-python does not admit, since it could never install.
pyproject.toml is parsed structurally (TOML plus PEP 508 requirements), not by
regex.

pyproject.toml is also the only dependency declaration: no requirements*.txt at
the project root may restate it, since a hand-maintained copy drifts from it.
"""

from importlib.metadata import metadata
from pathlib import Path, PurePosixPath

import pytest
from packaging.utils import canonicalize_name

from tests._collect_only import requires_uv
from tests._declared_dependencies import (
    E2E,
    PACKAGE_SCOPES,
    SOURCE_SCOPES,
    SourceScope,
    assert_imports_only_declared,
    dead_import_guards,
    declared_distributions_or_skip,
)
from tests._interpreters import (
    admitted_minor_versions,
    minor_versions_where_marker_holds,
    requires_python,
)
from tests._lane_collection import collect_lane_job
from tests._pyproject import core_requirements, extra_requirements, load_project_table
from tests._uv_env import SharedUvEnvironments

_E2E_LANE_JOB = "e2e"
_E2E_CONTRACT_MODULE = PurePosixPath("tests/e2e/test_declared_dependencies.py")


@pytest.mark.parametrize(
    "scope", [scope for scope in SOURCE_SCOPES if E2E not in scope.extras], ids=lambda scope: scope.name
)
def test_sources_import_only_declared_dependencies(project_root: Path, scope: SourceScope) -> None:
    """Every third-party distribution a source scope requires must be declared for that scope.

    The scopes whose extras include e2e are judged in tests/e2e/test_declared_dependencies.py by the e2e lane
    job, as test_the_e2e_lane_job_judges_each_scope_that_needs_the_e2e_extra pins.
    """
    assert_imports_only_declared(project_root, scope)


@requires_uv
@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen")
def test_the_e2e_lane_job_judges_each_scope_that_needs_the_e2e_extra(
    project_root: Path, shared_uv_probe_environments: SharedUvEnvironments
) -> None:
    """Run as the lane runs it, the e2e job collects a case of tests/e2e/test_declared_dependencies.py for every
    scope whose extras include e2e.

    The per-task verify does not install that extra, so it cannot judge those scopes.
    """
    collection = collect_lane_job(project_root, _E2E_LANE_JOB, env_for=shared_uv_probe_environments.for_command)

    judged = {test.parametrize_id for test in collection.written_report().tests if test.path == _E2E_CONTRACT_MODULE}
    unjudged = [scope.name for scope in SOURCE_SCOPES if E2E in scope.extras and scope.name not in judged]
    assert not unjudged, (
        f"the {_E2E_LANE_JOB!r} lane job {collection.command!r} collects no case of {_E2E_CONTRACT_MODULE} for the "
        f"scopes {unjudged}, whose extras include {E2E}. No automated run then judges their imports, so an import "
        "of a distribution that only another requirement installs (e.g. greenlet through playwright) goes unseen. "
        f"Parametrise that module's contract over every scope whose extras include {E2E}"
    )


@pytest.mark.parametrize("scope", PACKAGE_SCOPES, ids=lambda scope: scope.name)
def test_import_guards_guard_an_undeclared_dependency(project_root: Path, scope: SourceScope) -> None:
    """Every try in the package that handles ImportError must guard a distribution its source
    scope does not declare.

    Its handler runs only if a guarded import fails, and a declared distribution always
    imports in a valid install, so a guard over declared distributions only is dead code.
    """
    declared = declared_distributions_or_skip(project_root, scope.extras)
    sources = scope.select(project_root)
    dead = [
        f"{source.relative_to(project_root)}:{line} guards {modules}"
        for source, line, modules in dead_import_guards(sources, declared)
    ]
    assert not dead, (
        f"these ImportError guards are dead code: {dead}. Each guards only distributions its "
        "source scope declares, and a declared distribution always imports in a valid install, "
        "so the except branch can never run. Delete the guard and its fallback, or, if the "
        "import is meant to be optional, stop declaring the distribution"
    )


def test_core_dependencies_request_only_provided_extras(project_root: Path) -> None:
    """No core dependency may request an extra that its installed distribution does not provide."""
    unknown_extras: dict[str, list[str]] = {}
    for requirement in core_requirements(project_root):
        if not requirement.extras:
            continue
        provides_extra = metadata(requirement.name).get_all("Provides-Extra") or []
        provided = {canonicalize_name(extra) for extra in provides_extra}
        missing = {canonicalize_name(extra) for extra in requirement.extras} - provided
        if missing:
            unknown_extras[requirement.name] = sorted(missing)

    assert not unknown_extras, (
        f"unknown extras: {unknown_extras} — [project].dependencies requests extras the "
        "installed distributions do not provide. Resolvers (uv, pip) warn about unknown "
        "extras in every consumer's lock or install; drop the extra and depend directly on "
        "what the code needs"
    )


def test_dependency_markers_hold_on_some_admitted_interpreter(project_root: Path) -> None:
    """No declared requirement may be gated to Python minors that requires-python does not admit.

    A marker that holds on no candidate minor on this host (e.g. another OS's
    sys_platform) is not version-gated here and is not judged.
    """
    extras = load_project_table(project_root)["optional-dependencies"].keys()
    requirements = [*core_requirements(project_root), *extra_requirements(project_root, extras)]
    python_range = requires_python(project_root)
    admitted = admitted_minor_versions(python_range)

    dead: list[str] = []
    for requirement in requirements:
        if requirement.marker is None:
            continue
        holds_on = minor_versions_where_marker_holds(requirement.marker)
        if holds_on and holds_on.isdisjoint(admitted):
            dead.append(str(requirement))

    assert not dead, (
        f"declared requirements {dead} can never install on an interpreter "
        f"requires-python={str(python_range)!r} admits: each marker holds only on Python "
        "minors outside that range. Delete them from pyproject.toml"
    )


def test_no_requirements_file_duplicates_pyproject(project_root: Path) -> None:
    """pyproject.toml must be the only dependency declaration; no requirements*.txt may restate it."""
    duplicates = sorted(path.name for path in project_root.glob("requirements*.txt"))
    assert not duplicates, (
        f"{duplicates} at the project root restate the dependencies pyproject.toml declares, "
        "and a hand-maintained copy drifts from its source; delete them and install from "
        'pyproject.toml instead (pip install -e ".[dev]", or uv run --extra dev)'
    )
