# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_declared_dependencies.py, the declared-dependency contract's source scopes and import detector."""

from pathlib import Path

import pytest

from tests._declared_dependencies import (
    DEV,
    E2E,
    SOURCE_SCOPES,
    SourceScope,
    assert_imports_only_declared,
    dead_import_guards,
    undeclared_distributions,
)


def _write_module(path: Path, *lines: str) -> Path:
    """Write *path* as a module of *lines*, creating its parent directories, and return *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def _write_import_guard(path: Path, *body_lines: str) -> Path:
    """Write *path* as a module whose one function runs *body_lines* in a try that handles
    ImportError, and return *path*. The try is on line 2.
    """
    body = "".join(f"        {line}\n" for line in body_lines)
    path.write_text(
        f"def render():\n    try:\n{body}    except ImportError:\n        return None\n",
        encoding="utf-8",
    )
    return path


def test_undeclared_distributions_flags_only_files_requiring_an_undeclared_distribution(
    tmp_path: Path,
) -> None:
    """A file is flagged with every distribution it requires that is not declared."""
    undeclared_top_level = _write_module(
        tmp_path / "undeclared_top_level.py", "import pytest", "import yaml", "import numpy"
    )
    undeclared_function_local = _write_module(
        tmp_path / "undeclared_function_local.py",
        "def load():",
        "    from yaml import safe_load",
        "    return safe_load",
    )
    declared_only = _write_module(
        tmp_path / "declared_only.py", "import pytest", "from _pytest.monkeypatch import MonkeyPatch"
    )
    first_party_only = _write_module(
        tmp_path / "first_party_only.py",
        "import solar_challenge",
        "from tests._pyproject import load_project_table",
    )
    standard_library_only = _write_module(
        tmp_path / "standard_library_only.py", "import json", "from collections.abc import Iterator"
    )
    relative_only = _write_module(tmp_path / "relative_only.py", "from . import sibling")
    guarded_only = _write_import_guard(tmp_path / "guarded_only.py", "import yaml")

    undeclared = undeclared_distributions(
        [
            undeclared_top_level,
            undeclared_function_local,
            declared_only,
            first_party_only,
            standard_library_only,
            relative_only,
            guarded_only,
        ],
        declared={"pytest"},
    )

    assert undeclared == [
        (undeclared_function_local, ["pyyaml"]),
        (undeclared_top_level, ["numpy", "pyyaml"]),
    ], (
        "the undeclared-distributions detector misjudged a synthetic file: each undeclared_* file "
        "requires distributions beside the declared pytest, named canonically (pyyaml provides "
        "yaml), at top level or inside a function. declared_only imports only modules the "
        "declared pytest provides, first_party_only only solar_challenge and tests, "
        "standard_library_only only the standard library and relative_only only a sibling, and "
        "guarded_only imports yaml only inside a try that handles ImportError, so none of those "
        "may be flagged"
    )


def test_dead_import_guards_flags_only_guards_wholly_over_declared_distributions(
    tmp_path: Path,
) -> None:
    """A guard is dead only when declared distributions provide every third-party module it guards.

    Once src/ holds no dead guard,
    tests/unit/test_dependency_declarations.py::test_import_guards_guard_an_undeclared_dependency
    passes for a detector that flags nothing, so this checks the detector on guards of known verdict.
    """
    unprovided = "no_installed_distribution_provides_this_module"
    dead_import = _write_import_guard(tmp_path / "dead_import.py", "import yaml")
    dead_nested_from_import = _write_import_guard(
        tmp_path / "dead_nested_from_import.py",
        "if sys.version_info >= (3, 11):",
        "    from yaml import safe_load",
    )
    live_unprovided = _write_import_guard(tmp_path / "live_unprovided.py", f"import {unprovided}")
    live_partly_declared = _write_import_guard(
        tmp_path / "live_partly_declared.py", "import yaml", f"import {unprovided}"
    )
    not_judged_stdlib_only = _write_import_guard(tmp_path / "not_judged_stdlib_only.py", "import json")

    dead = dead_import_guards(
        [
            dead_import,
            dead_nested_from_import,
            live_unprovided,
            live_partly_declared,
            not_judged_stdlib_only,
        ],
        declared={"pyyaml"},
    )

    assert dead == [(dead_import, 2, ["yaml"]), (dead_nested_from_import, 2, ["yaml"])], (
        "the dead-guard detector misjudged a synthetic guard: the dead_* guards import only the "
        "declared pyyaml, each live_* guard imports a module no declared distribution provides, "
        "and not_judged_stdlib_only imports only the standard library, so it guards no "
        "third-party import and must not be judged dead"
    )


_OWN_FILES_OF_EACH_SCOPE = {
    "outside-web": ("src/solar_challenge/simulate.py",),
    "web": ("src/solar_challenge/web/views.py",),
    "scripts": ("scripts/measure.py",),
    "tests-dev-only-lanes": (
        "tests/__init__.py",
        "tests/_lock.py",
        "tests/_network.py",
        "tests/_newest.py",
        "tests/_plugin.py",
        "tests/_plugin_fixtures.py",
        "tests/_uv.py",
        "tests/conftest.py",
        "tests/css_build/test_build.py",
        "tests/integration/__init__.py",
        "tests/integration/_pvgis_probe.py",
        "tests/integration/test_pvgis.py",
        "tests/interpreter_matrix/test_matrix.py",
        "tests/newest_releases/test_newest.py",
        "tests/unit/__init__.py",
        "tests/unit/_css.py",
    ),
    "tests-verify": (
        "tests/_helpers.py",
        "tests/_web_double.py",
        "tests/integration/test_fleet.py",
        "tests/unit/conftest.py",
        "tests/unit/test_simulate.py",
    ),
    "tests-e2e": ("tests/e2e/test_pages.py",),
}
_LINES_OF_EACH_IMPORTING_FILE: dict[str, tuple[str, ...]] = {
    # a conftest every run loads; its pytest_plugins list names a pytest built-in, which is no file
    # of the project, beside a plugin of the project
    "tests/conftest.py": (
        "from tests._network import refusing_network",
        'pytest_plugins = ["pytester", "tests._plugin"]',
    ),
    # a plugin's own entries, in the comma-separated string form pytest also accepts
    "tests/_plugin.py": ('pytest_plugins = "pytester,tests._plugin_fixtures"',),
    # module level; the trailing name is an attribute of the module
    "tests/interpreter_matrix/test_matrix.py": ("from tests._uv import isolated_env",),
    # transitive
    "tests/_uv.py": ("import tests._lock",),
    # _uv is shared with the verify and still goes to the dev-only scope; _helpers stays with the verify
    "tests/unit/test_simulate.py": (
        "from tests._helpers import build",
        "from tests._uv import isolated_env",
    ),
    # the guarded import is not followed; the function-local from-package submodule is
    "tests/newest_releases/test_newest.py": (
        "try:",
        "    from tests._web_double import app",
        "except ImportError:",
        "    app = None",
        "def test_newest():",
        "    from tests import _newest",
    ),
    # the package __init__.py on the way is run too
    "tests/css_build/test_build.py": ("from tests.unit._css import classes",),
    # relative, with no module
    "tests/integration/test_pvgis.py": ("from . import _pvgis_probe",),
}


@pytest.mark.parametrize(
    ("scope", "own_files"),
    [pytest.param(scope, _OWN_FILES_OF_EACH_SCOPE[scope.name], id=scope.name) for scope in SOURCE_SCOPES],
)
def test_each_source_scope_selects_only_its_own_files(
    tmp_path: Path,
    scope: SourceScope,
    own_files: tuple[str, ...],
) -> None:
    """A source scope selects exactly its own files of the project root it is given.

    tests-dev-only-lanes also owns every module of the tests package that its files import,
    transitively: at module level, inside a function, as a submodule a from-import names,
    relatively, or through a package's __init__.py. tests-verify owns none of them. A module
    named only inside a try that handles ImportError is not imported for certain, so it
    stays with tests-verify.

    A module that a pytest_plugins entry names, as a list or a comma-separated string, in a
    conftest or in a plugin it loads, counts as imported: pytest imports each entry. A built-in
    such as pytester names no file of the project.
    """
    project_files = sorted({path for files in _OWN_FILES_OF_EACH_SCOPE.values() for path in files})
    for relative_path in project_files:
        _write_module(tmp_path / relative_path, *_LINES_OF_EACH_IMPORTING_FILE.get(relative_path, ()))

    selected = sorted(path.relative_to(tmp_path).as_posix() for path in scope.select(tmp_path))

    assert selected == sorted(own_files), (
        f"in a project holding each scope's own files, {project_files}, which import as "
        f"{_LINES_OF_EACH_IMPORTING_FILE} gives, this scope selected {selected}, "
        f"but it owns exactly {sorted(own_files)}"
    )


def test_assert_imports_only_declared_names_each_file_requiring_a_distribution_its_scope_does_not_declare(
    tmp_path: Path,
) -> None:
    """The contract fails naming each selected file, relative to the project root, with the distributions it
    requires beyond [project].dependencies and the scope's own extras, and the groups it checked them against.

    Another extra's requirements are not declared for the scope, so pyyaml, which only web declares, is flagged
    for a scope whose one extra is dev, and packaging, which dev declares, is not.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'dependencies = ["pytest"]\n'
        "[project.optional-dependencies]\n"
        'dev = ["packaging"]\n'
        'web = ["pyyaml"]\n',
        encoding="utf-8",
    )
    _write_module(tmp_path / "pkg" / "uses_yaml.py", "import packaging.version", "import yaml")
    scope = SourceScope("probe", lambda project_root: [project_root / "pkg" / "uses_yaml.py"], (DEV,))

    with pytest.raises(AssertionError) as failure:
        assert_imports_only_declared(tmp_path, scope)

    message = str(failure.value)
    assert "pkg/uses_yaml.py requires ['pyyaml']" in message and str(tmp_path) not in message, (
        f"the failure does not name pkg/uses_yaml.py, relative to the project root, as requiring exactly the "
        f"undeclared pyyaml: {message}"
    )
    assert "[project].dependencies, [project.optional-dependencies].dev:" in message, (
        f"the failure does not list the groups the scope's imports were checked against: {message}"
    )
    assert "[project.optional-dependencies].web" not in message, (
        f"the failure lists the web extra, which the scope does not name: {message}"
    )


def test_assert_imports_only_declared_skips_while_an_extra_of_the_scope_is_not_installed(tmp_path: Path) -> None:
    """The contract skips, never fails, while a requirement of the scope's extras is not installed.

    Imports map to distributions only through installed metadata, so a scope is judged only in a run that
    installs its extras; here the selected file's yaml import is undeclared, and still nothing fails.
    """
    uninstalled = "solar-challenge-no-such-distribution"
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'dependencies = ["pytest"]\n'
        "[project.optional-dependencies]\n"
        f'e2e = ["{uninstalled}"]\n',
        encoding="utf-8",
    )
    _write_module(tmp_path / "pkg" / "uses_yaml.py", "import yaml")
    scope = SourceScope("probe", lambda project_root: [project_root / "pkg" / "uses_yaml.py"], (E2E,))

    with pytest.raises(pytest.skip.Exception, match=uninstalled):
        assert_imports_only_declared(tmp_path, scope)
