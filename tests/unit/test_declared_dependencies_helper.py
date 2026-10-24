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
    web_subpackage_imports,
)

_UNPROVIDED_MODULE = "no_installed_distribution_provides_this_module"
_ASSIGNS_RERUNFAILURES = 'pytest_plugins = ["pytest_rerunfailures"]'
_SOURCE_ASSIGNING_RERUNFAILURES = 'SOURCE = "pytest_plugins = [\'pytest_rerunfailures\']"'
_ASSIGNS_PYTESTER = 'pytest_plugins = ["pytester"]'
_UNREADABLE_USE = "which can bind or change pytest_plugins in a form the contract cannot read"


def _write_module(path: Path, *lines: str) -> Path:
    """Write *path* as a module of *lines*, creating its parent directories, and return *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def _write_import_guard(path: Path, *body_lines: str) -> Path:
    """Write *path* as a module whose one function runs *body_lines* in a try that handles
    ImportError, creating its parent directories, and return *path*. The try is on line 2.
    """
    return _write_module(
        path,
        "def render():",
        "    try:",
        *(f"        {line}" for line in body_lines),
        "    except ImportError:",
        "        return None",
    )


def test_undeclared_distributions_flags_only_files_requiring_an_undeclared_distribution(
    tmp_path: Path,
) -> None:
    """A file is flagged with every distribution it requires that is not declared, including each
    whose module it names to pytest.importorskip, and each whose plugin module a pytest_plugins
    entry names. A built-in plugin's short name, such as pytester, names a module of pytest itself.

    A module named to pytest.importorskip counts even inside a try of the package that handles
    ImportError: the handler cannot catch the skip.
    """
    undeclared_top_level = _write_module(
        tmp_path / "undeclared_top_level.py", "import pytest", "import yaml", "import numpy"
    )
    undeclared_function_local = _write_module(
        tmp_path / "undeclared_function_local.py",
        "def load():",
        "    from yaml import safe_load",
        "    return safe_load",
    )
    undeclared_importorskip = _write_module(
        tmp_path / "undeclared_importorskip.py", "import pytest", 'pytest.importorskip("yaml")'
    )
    undeclared_importorskip_in_test = _write_module(
        tmp_path / "undeclared_importorskip_in_test.py",
        "from pytest import importorskip",
        "def test_solves():",
        '    importorskip(minversion="2", modname="numpy.linalg")',
    )
    undeclared_importorskip_in_guard = _write_import_guard(
        tmp_path / "src" / "solar_challenge" / "undeclared_importorskip_in_guard.py", 'pytest.importorskip("yaml")'
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
    declared_importorskip = _write_module(
        tmp_path / "declared_importorskip.py",
        "import pytest",
        'pytest.importorskip("_pytest.pytester")',
        'pytest.importorskip("sqlite3")',
    )
    non_literal_importorskip = _write_module(
        tmp_path / "non_literal_importorskip.py",
        "import pytest",
        'MODULE = "yaml"',
        "pytest.importorskip(MODULE)",
    )
    undeclared_pytest_plugin = _write_module(
        tmp_path / "undeclared_pytest_plugin.py", 'pytest_plugins = "pytester,pytest_rerunfailures"'
    )
    builtin_pytest_plugin = _write_module(tmp_path / "builtin_pytest_plugin.py", 'pytest_plugins = ["pytester"]')
    empty_pytest_plugins = _write_module(tmp_path / "empty_pytest_plugins.py", 'pytest_plugins = ""')
    module_pytest_plugins = _write_module(tmp_path / "module_pytest_plugins.py", "import json as pytest_plugins")

    undeclared = undeclared_distributions(
        tmp_path,
        [
            undeclared_top_level,
            undeclared_function_local,
            undeclared_importorskip,
            undeclared_importorskip_in_test,
            undeclared_importorskip_in_guard,
            declared_only,
            first_party_only,
            standard_library_only,
            relative_only,
            declared_importorskip,
            non_literal_importorskip,
            undeclared_pytest_plugin,
            builtin_pytest_plugin,
            empty_pytest_plugins,
            module_pytest_plugins,
        ],
        declared={"pytest"},
    )

    assert undeclared == [
        (undeclared_importorskip_in_guard, ["pyyaml"]),
        (undeclared_function_local, ["pyyaml"]),
        (undeclared_importorskip, ["pyyaml"]),
        (undeclared_importorskip_in_test, ["numpy"]),
        (undeclared_pytest_plugin, ["pytest-rerunfailures"]),
        (undeclared_top_level, ["numpy", "pyyaml"]),
    ], (
        "the undeclared-distributions detector misjudged a synthetic file: each undeclared_* file "
        "requires distributions beside the declared pytest, named canonically (pyyaml provides "
        "yaml), at top level or inside a function, or as a module it names to "
        "pytest.importorskip. The undeclared_importorskip* files do that as pytest.importorskip "
        "or by the bare name from pytest, positionally or as modname= beside another keyword, "
        "at module level, inside a test, or inside a try of src/solar_challenge that handles ImportError, "
        "which cannot catch the skip; a dotted name's top-level module counts. declared_only imports only "
        "modules the declared pytest provides,first_party_only only solar_challenge and tests, "
        "standard_library_only only the standard library and relative_only only a sibling, "
        "declared_importorskip names to pytest.importorskip only a module the declared pytest "
        "provides and a standard-library one, and non_literal_importorskip passes it a name, "
        "not a string literal, so none of those may be flagged. undeclared_pytest_plugin names "
        "the pytest_rerunfailures plugin module in a comma-separated pytest_plugins string, "
        "beside the built-in pytester. builtin_pytest_plugin names only pytester, which pytest "
        "imports from its own _pytest package. empty_pytest_plugins sets pytest_plugins to an "
        "empty string, which names no plugin. module_pytest_plugins binds pytest_plugins to a "
        "module, json, which pytest reads as naming no plugin. So none of the last three may be "
        "flagged"
    )


@pytest.mark.parametrize(
    "lines",
    [
        pytest.param(
            ("pytest_plugins = []", 'pytest_plugins += ["pytest_rerunfailures"]'),
            id="extended-with-plus-equals",
        ),
        pytest.param(
            ('pytest_plugins = "pytester"', 'pytest_plugins += ",pytest_rerunfailures"'),
            id="a-str-extended-after-a-comma",
        ),
        pytest.param(('if sys.platform == "linux":', f"    {_ASSIGNS_RERUNFAILURES}"), id="in-an-if"),
        pytest.param(
            ("if not sys.platform:", "    pass", "else:", f"    {_ASSIGNS_RERUNFAILURES}"), id="in-an-else"
        ),
        pytest.param(
            ("try:", f"    {_ASSIGNS_RERUNFAILURES}", "except Exception:", "    pass"), id="in-a-try"
        ),
        pytest.param(
            ("try:", "    pass", "except Exception:", f"    {_ASSIGNS_RERUNFAILURES}"),
            id="in-an-except-handler",
        ),
        pytest.param(
            ("try:", "    pass", "finally:", f"    {_ASSIGNS_RERUNFAILURES}"), id="in-a-finally"
        ),
        pytest.param(
            ("try:", "    pass", "except* Exception:", f"    {_ASSIGNS_RERUNFAILURES}"),
            id="in-an-except-star-handler",
        ),
        pytest.param(
            ("with contextlib.suppress(Exception):", f"    {_ASSIGNS_RERUNFAILURES}"), id="in-a-with"
        ),
        pytest.param(("for _ in range(1):", f"    {_ASSIGNS_RERUNFAILURES}"), id="in-a-for"),
        pytest.param(("while True:", f"    {_ASSIGNS_RERUNFAILURES}", "    break"), id="in-a-while"),
        pytest.param(
            ("match sys.platform:", "    case _:", f"        {_ASSIGNS_RERUNFAILURES}"), id="in-a-match-case"
        ),
        pytest.param(
            (
                'if sys.platform == "linux":',
                "    if sys.version_info >= (3, 11):",
                f"        {_ASSIGNS_RERUNFAILURES}",
            ),
            id="two-blocks-deep",
        ),
        pytest.param(
            ('if sys.platform == "linux":', '    pytest_plugins: list[str] = ["pytest_rerunfailures"]'),
            id="annotated-in-an-if",
        ),
        pytest.param(
            (
                'pytest_plugins = ["pytester"]',
                'if sys.platform == "linux":',
                '    pytest_plugins += ("pytest_rerunfailures",)',
            ),
            id="extended-in-an-if",
        ),
    ],
)
def test_undeclared_distributions_reads_every_pytest_plugins_entry_its_module_scope_gives(
    tmp_path: Path,
    lines: tuple[str, ...],
) -> None:
    """A pytest_plugins entry counts as a requirement wherever a statement of the module's own scope gives it.

    pytest reads pytest_plugins as an attribute of the module once the module has run, so an
    augmented assignment adds its entries to those the assignment before it gave. A str extended
    after a comma adds the names after the comma, not the empty piece before it. An assignment,
    annotated or not, in any block of a compound statement, however deep, counts as well.
    """
    plugin = _write_module(tmp_path / "plugin.py", "import contextlib", "import sys", *lines)

    assert undeclared_distributions(tmp_path, [plugin], declared={"pytest"}) == [
        (plugin, ["pytest-rerunfailures"])
    ], (
        "the undeclared-distributions detector missed the pytest_rerunfailures module, which the "
        "undeclared pytest-rerunfailures provides, among the entries a module gives pytest_plugins "
        f"with these lines: {lines}"
    )


@pytest.mark.parametrize(
    "lines",
    [
        pytest.param(("def configure():", f"    {_ASSIGNS_RERUNFAILURES}"), id="in-a-function"),
        pytest.param(("async def configure():", f"    {_ASSIGNS_RERUNFAILURES}"), id="in-an-async-function"),
        pytest.param(("class Plugins:", f"    {_ASSIGNS_RERUNFAILURES}"), id="in-a-class"),
        pytest.param(
            ('if sys.platform == "linux":', "    def configure():", f"        {_ASSIGNS_RERUNFAILURES}"),
            id="in-a-function-inside-an-if",
        ),
        pytest.param(
            (
                'if sys.platform == "linux":',
                "    def configure():",
                "        pytest_plugins, count = ['pytest_rerunfailures'], 1",
            ),
            id="unpacked-in-a-function-inside-an-if",
        ),
        pytest.param(("pytest_plugins: list[str]",), id="annotated-with-no-value"),
        pytest.param(
            ("def configure():", "    try:", "        pass", "    except Exception as pytest_plugins:", "        pass"),
            id="caught-in-a-function",
        ),
        pytest.param(
            ("def configure():", "    from tests._plugins import PLUGINS as pytest_plugins"),
            id="imported-as-it-in-a-function",
        ),
        pytest.param(("class Plugins:", "    def pytest_plugins(self): pass"), id="a-method"),
    ],
)
def test_undeclared_distributions_ignores_a_pytest_plugins_that_binds_no_attribute_of_its_module(
    tmp_path: Path,
    lines: tuple[str, ...],
) -> None:
    """A pytest_plugins requires nothing when it binds no attribute of the module, wherever the def
    or class around it stands in the module.

    A function that declares no global binds it as a local, in whatever form, and a class as an
    attribute of the class: pytest reads neither. An annotation with no value assigns nothing.
    """
    plugin = _write_module(tmp_path / "plugin.py", "import sys", *lines)

    assert undeclared_distributions(tmp_path, [plugin], declared={"pytest"}) == [], (
        "the undeclared-distributions detector read a requirement of pytest-rerunfailures from a "
        f"pytest_plugins that binds no attribute of its module, with these lines: {lines}"
    )


def test_undeclared_distributions_counts_an_import_inside_an_import_error_guard_outside_the_package_only(
    tmp_path: Path,
) -> None:
    """Outside the package, an import inside a try that handles ImportError or ModuleNotFoundError
    is required like any other, so a guarded module the scope does not declare is flagged, even one
    another declared requirement installs. A guard over a declared or standard-library module is not.

    In the package, src/solar_challenge, such a try makes its imports optional.
    """
    optional_yaml = _write_import_guard(
        tmp_path / "src" / "solar_challenge" / "optional_yaml.py", "import yaml", f"import {_UNPROVIDED_MODULE}"
    )
    test_skips_without_yaml = _write_module(
        tmp_path / "tests" / "test_skips_without_yaml.py",
        "import pytest",
        "try:",
        "    import yaml",
        "except ImportError:",
        '    pytest.skip("needs yaml", allow_module_level=True)',
    )
    falls_back_without_yaml = _write_module(
        tmp_path / "scripts" / "falls_back_without_yaml.py",
        "def load():",
        "    try:",
        "        from yaml import safe_load",
        "    except ModuleNotFoundError:",
        "        return None",
        "    return safe_load",
    )
    test_skips_without_pluggy = _write_import_guard(tmp_path / "tests" / "test_skips_without_pluggy.py", "import pluggy")
    guards_a_declared_module = _write_import_guard(
        tmp_path / "tests" / "guards_a_declared_module.py", "import _pytest.pytester"
    )
    guards_the_standard_library = _write_import_guard(
        tmp_path / "scripts" / "guards_the_standard_library.py", "import tomllib"
    )

    undeclared = undeclared_distributions(
        tmp_path,
        [
            optional_yaml,
            test_skips_without_yaml,
            falls_back_without_yaml,
            test_skips_without_pluggy,
            guards_a_declared_module,
            guards_the_standard_library,
        ],
        declared={"pytest"},
    )

    assert undeclared == [
        (falls_back_without_yaml, ["pyyaml"]),
        (test_skips_without_pluggy, ["pluggy"]),
        (test_skips_without_yaml, ["pyyaml"]),
    ], (
        "the undeclared-distributions detector misjudged a synthetic import guard, a try that handles "
        "ImportError or ModuleNotFoundError. Outside src/solar_challenge: test_skips_without_yaml skips "
        "at module level unless yaml imports, and falls_back_without_yaml returns None inside a "
        "function unless it does, so each must be flagged with the undeclared pyyaml; "
        "test_skips_without_pluggy guards pluggy, which only the declared pytest's own requirements "
        "install, so it must be flagged with the undeclared pluggy; guards_a_declared_module guards a "
        "module of the declared pytest and guards_the_standard_library one of the standard library, so "
        "neither may be flagged. In src/solar_challenge, optional_yaml guards yaml and a module no "
        "installed distribution provides, so it may be neither flagged nor fail the detector"
    )


@pytest.mark.parametrize(
    "lines",
    [
        pytest.param(("loader = object()", 'loader.importorskip("yaml")'), id="method-of-another-object"),
        pytest.param(
            ('"""Skips unless pytest.importorskip("yaml") finds it."""', '# pytest.importorskip("yaml")'),
            id="named-in-a-docstring-and-a-comment",
        ),
        pytest.param(("import pytest", 'pytest.skip("yaml")'), id="another-pytest-function"),
        pytest.param(("import pytest", 'pytest.importorskip(minversion="2")'), id="no-module-named"),
    ],
)
def test_undeclared_distributions_ignores_what_only_resembles_a_call_of_pytests_importorskip(
    tmp_path: Path,
    lines: tuple[str, ...],
) -> None:
    """A file requires a module through importorskip only by calling pytest's importorskip with its name.

    A method of that name on another object, a mention in a docstring or a comment, another pytest
    function given the name of a module, and a call that names no module require nothing.
    """
    resembling = _write_module(tmp_path / "resembling.py", *lines)

    assert undeclared_distributions(tmp_path, [resembling], declared={"pytest"}) == [], (
        "the undeclared-distributions detector read a requirement of yaml, which no declared "
        f"distribution provides, from a file that only resembles a call of pytest.importorskip: {lines}"
    )


@pytest.mark.parametrize(
    "skip_lines",
    [
        pytest.param((f'pytest.importorskip("{_UNPROVIDED_MODULE}")',), id="named-to-importorskip"),
        pytest.param(
            (
                "try:",
                f"    import {_UNPROVIDED_MODULE}",
                "except ImportError:",
                f'    pytest.skip("needs {_UNPROVIDED_MODULE}", allow_module_level=True)',
            ),
            id="imported-inside-an-import-error-guard",
        ),
    ],
)
def test_undeclared_distributions_fails_naming_a_file_whose_test_skips_without_a_module_no_installed_distribution_provides(
    tmp_path: Path,
    skip_lines: tuple[str, ...],
) -> None:
    """A module that no installed distribution provides fails the detector, naming the file and the
    module, when a file outside the package names it to pytest.importorskip or imports it inside a
    try that handles ImportError by skipping, because that file's test skips in every run.
    """
    skips_always = _write_module(tmp_path / "skips_always.py", "import pytest", *skip_lines)

    with pytest.raises(AssertionError) as failure:
        undeclared_distributions(tmp_path, [skips_always], declared={"pytest"})

    message = str(failure.value)
    assert str(skips_always) in message and _UNPROVIDED_MODULE in message, (
        f"the failure does not name {skips_always}, nor the module {_UNPROVIDED_MODULE} that its test "
        f"skips without, which no installed distribution provides: {message}"
    )


def test_dead_import_guards_flags_only_guards_wholly_over_declared_distributions(
    tmp_path: Path,
) -> None:
    """A guard is dead only when declared distributions provide every third-party module it guards.

    Once src/ holds no dead guard,
    tests/unit/test_dependency_declarations.py::test_import_guards_guard_an_undeclared_dependency
    passes for a detector that flags nothing, so this checks the detector on guards of known verdict.
    """
    dead_import = _write_import_guard(tmp_path / "dead_import.py", "import yaml")
    dead_nested_from_import = _write_import_guard(
        tmp_path / "dead_nested_from_import.py",
        "if sys.version_info >= (3, 11):",
        "    from yaml import safe_load",
    )
    live_unprovided = _write_import_guard(tmp_path / "live_unprovided.py", f"import {_UNPROVIDED_MODULE}")
    live_partly_declared = _write_import_guard(
        tmp_path / "live_partly_declared.py", "import yaml", f"import {_UNPROVIDED_MODULE}"
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


def test_web_subpackage_imports_flags_each_file_whose_imports_run_a_module_of_the_web_subpackage(
    tmp_path: Path,
) -> None:
    """A file is flagged with each file of the package's web subpackage that its imports run, however
    it names the subpackage: a module of it, the subpackage from its parent package, a name of it
    inside a function, for type checking or inside a try that handles ImportError, a module named to
    pytest.importorskip, or a pytest_plugins entry.
    """
    package_dir = tmp_path / "src" / "solar_challenge"
    _write_module(package_dir / "__init__.py")
    _write_module(package_dir / "weather.py")
    web_init = _write_module(package_dir / "web" / "__init__.py")
    web_jobs = _write_module(package_dir / "web" / "jobs.py")
    web_app = _write_module(package_dir / "web" / "app.py", "import flask")
    _write_module(tmp_path / "tests" / "web" / "__init__.py")
    scripts_dir = tmp_path / "scripts"
    imports_a_module = _write_module(scripts_dir / "imports_a_module.py", "import solar_challenge.web.jobs")
    imports_the_subpackage_from_its_parent = _write_module(
        scripts_dir / "imports_the_subpackage_from_its_parent.py", "from solar_challenge import web"
    )
    imports_a_name_in_a_function = _write_module(
        scripts_dir / "imports_a_name_in_a_function.py",
        "def build():",
        "    from solar_challenge.web.app import create_app",
        "    return create_app()",
    )
    imports_for_type_checking = _write_module(
        scripts_dir / "imports_for_type_checking.py",
        "from typing import TYPE_CHECKING",
        "if TYPE_CHECKING:",
        "    from solar_challenge.web.jobs import JobManager",
    )
    importorskips = _write_module(
        scripts_dir / "importorskips.py", "import pytest", 'pytest.importorskip("solar_challenge.web.app")'
    )
    names_a_plugin = _write_module(scripts_dir / "names_a_plugin.py", 'pytest_plugins = ["solar_challenge.web.jobs"]')
    imports_the_package_only = _write_module(
        scripts_dir / "imports_the_package_only.py",
        "import solar_challenge",
        "from solar_challenge import weather",
        "from solar_challenge.weather import fetch",
    )
    guards_the_import = _write_import_guard(
        scripts_dir / "guards_the_import.py", "from solar_challenge.web.app import create_app"
    )
    imports_another_web = _write_module(scripts_dir / "imports_another_web.py", "import web", "from tests import web")
    names_it_in_a_string = _write_module(
        scripts_dir / "names_it_in_a_string.py", "import sys", 'sys.modules.get("solar_challenge.web.jobs")'
    )

    flagged = web_subpackage_imports(
        tmp_path,
        [
            imports_a_module,
            imports_the_subpackage_from_its_parent,
            imports_a_name_in_a_function,
            imports_for_type_checking,
            importorskips,
            names_a_plugin,
            imports_the_package_only,
            guards_the_import,
            imports_another_web,
            names_it_in_a_string,
        ],
    )

    assert flagged == [
        (guards_the_import, [web_init, web_app]),
        (importorskips, [web_init, web_app]),
        (imports_a_module, [web_init, web_jobs]),
        (imports_a_name_in_a_function, [web_init, web_app]),
        (imports_for_type_checking, [web_init, web_jobs]),
        (imports_the_subpackage_from_its_parent, [web_init]),
        (names_a_plugin, [web_init, web_jobs]),
    ], (
        "the web-subpackage detector misjudged a synthetic file. Each flagged file runs "
        "web/__init__.py, and the module of src/solar_challenge/web it names, by importing a module of "
        "the subpackage, the subpackage from its parent package, or a name of it inside a function, "
        "under TYPE_CHECKING or inside a try that handles ImportError, or by naming a module of it to "
        "pytest.importorskip or in pytest_plugins. "
        "imports_the_package_only imports solar_challenge and its weather module only. "
        "imports_another_web imports modules named web elsewhere, a third-party one and tests/web, "
        "neither of which is the package's subpackage. names_it_in_a_string names it in a string only, "
        "which is no import. So none of those three may be flagged"
    )


_OWN_FILES_OF_EACH_SCOPE = {
    "outside-web": ("src/solar_challenge/simulate.py",),
    "web": ("src/solar_challenge/web/views.py",),
    "scripts": ("scripts/measure.py",),
    "tests-dev-only-lanes": (
        "tests/__init__.py",
        "tests/_linux_plugin.py",
        "tests/_lock.py",
        "tests/_nested_plugin.py",
        "tests/_network.py",
        "tests/_newest.py",
        "tests/_paths.py",
        "tests/_pins.py",
        "tests/_plugin.py",
        "tests/_plugin_fixtures.py",
        "tests/_plugin_hooks.py",
        "tests/_uv.py",
        "tests/_web_double.py",
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
        "tests/integration/test_fleet.py",
        "tests/unit/conftest.py",
        "tests/unit/test_simulate.py",
    ),
    "tests-e2e": ("tests/e2e/test_pages.py",),
}
_LINES_OF_EACH_IMPORTING_FILE: dict[str, tuple[str, ...]] = {
    # a conftest every run loads; its pytest_plugins list names a pytest built-in, which is no file
    # of the project, beside a plugin of the project. The += inside the if adds a plugin of the
    # project, which is followed; the list in the function's body is a local of the function, so
    # the helper it names stays with the verify
    "tests/conftest.py": (
        "import sys",
        "from tests._network import refusing_network",
        'pytest_plugins = ["pytester", "tests._plugin"]',
        'if sys.platform == "linux":',
        '    pytest_plugins += ["tests._linux_plugin"]',
        "def pytest_configure(config):",
        '    pytest_plugins = ["tests._helpers"]',
    ),
    # a plugin's own entries, in the comma-separated string form pytest also accepts
    "tests/_plugin.py": ('pytest_plugins = "pytester,tests._plugin_fixtures"',),
    # an annotated assignment, which pytest honours too
    "tests/_plugin_fixtures.py": ('pytest_plugins: list[str] = ["tests._plugin_hooks"]',),
    # an annotation with no value assigns nothing; an assignment in the block of a with does
    "tests/_plugin_hooks.py": (
        "import contextlib",
        "pytest_plugins: list[str]",
        "with contextlib.suppress(Exception):",
        '    pytest_plugins = ["tests._nested_plugin"]',
    ),
    # module level; the trailing name is an attribute of the module
    "tests/interpreter_matrix/test_matrix.py": ("from tests._uv import isolated_env",),
    # transitive
    "tests/_uv.py": ("import tests._lock",),
    # a cycle back to _uv: the walk ends, and each file is selected once
    "tests/_lock.py": ("import tests._uv",),
    # _uv is shared with the verify and still goes to the dev-only scope; _helpers stays with the verify
    "tests/unit/test_simulate.py": (
        "from tests._helpers import build",
        "from tests._uv import isolated_env",
    ),
    # the module named inside a try that handles ImportError is followed, and so are the
    # function-local from-package submodule and the module the test names to pytest.importorskip
    "tests/newest_releases/test_newest.py": (
        "try:",
        "    from tests._web_double import app",
        "except ImportError:",
        "    app = None",
        "def test_newest():",
        "    from tests import _newest",
        '    pytest.importorskip("tests._pins")',
    ),
    # the package __init__.py on the way is run too
    "tests/css_build/test_build.py": ("from tests.unit._css import classes",),
    # relative, two levels up and with a module; no other file imports _paths, so only this
    # import selects it
    "tests/unit/_css.py": ("from .._paths import root",),
    # relative, with no module; and a module of the package, which stays with the package's own scope
    "tests/integration/test_pvgis.py": ("from . import _pvgis_probe", "from solar_challenge.simulate import run"),
}


def _write_project_of_every_scope(project_root: Path) -> list[str]:
    """Write every scope's own files under *project_root*, each importing as
    _LINES_OF_EACH_IMPORTING_FILE gives, and return their paths relative to it.
    """
    project_files = sorted({path for files in _OWN_FILES_OF_EACH_SCOPE.values() for path in files})
    for relative_path in project_files:
        _write_module(project_root / relative_path, *_LINES_OF_EACH_IMPORTING_FILE.get(relative_path, ()))
    return project_files


def _scope_named(name: str) -> SourceScope:
    """Return the source scope called *name*."""
    return next(scope for scope in SOURCE_SCOPES if scope.name == name)


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
    relatively (from the package directory or from one above it), or through a package's
    __init__.py. Modules that import each other are selected once each. tests-verify owns none
    of them. A module named inside a try that handles ImportError counts as imported too. A
    module named to pytest.importorskip as a string literal counts as imported: the test imports
    it or skips. The dev-only lanes' closure selects tests modules only, so a module of the
    package that a lane file imports stays with the package's own scope.

    A module that a pytest_plugins entry names, as a list or a comma-separated string, in a
    conftest or in a plugin it loads, counts as imported: pytest imports each entry. So does
    one that an annotated assignment names, one that += adds, and one that a block of a compound
    statement, such as an if or a with, gives. An annotation with no value names none, and nor
    does a pytest_plugins that a function's body binds as a local. A built-in
    such as pytester names no file of the project.
    """
    project_files = _write_project_of_every_scope(tmp_path)

    selected = sorted(path.relative_to(tmp_path).as_posix() for path in scope.select(tmp_path))

    assert selected == sorted(own_files), (
        f"in a project holding each scope's own files, {project_files}, which import as "
        f"{_LINES_OF_EACH_IMPORTING_FILE} gives, this scope selected {selected}, "
        f"but it owns exactly {sorted(own_files)}"
    )


@pytest.mark.parametrize(
    ("lines", "quoted"),
    [
        pytest.param(
            ("from tests._network import BASE_PLUGINS", 'pytest_plugins = [*BASE_PLUGINS, "tests._plugin"]'),
            "[*BASE_PLUGINS, 'tests._plugin']",
            id="a-starred-list",
        ),
        pytest.param(
            (
                "import sys",
                _ASSIGNS_PYTESTER,
                'if sys.platform == "linux":',
                '    pytest_plugins.append("tests._plugin")',
            ),
            "pytest_plugins.append('tests._plugin')",
            id="appended-in-an-if",
        ),
    ],
)
def test_a_scope_fails_naming_the_file_and_line_of_a_pytest_plugins_it_cannot_read(
    tmp_path: Path,
    lines: tuple[str, ...],
    quoted: str,
) -> None:
    """A scope that follows pytest_plugins entries fails, naming the file, the line and the
    statement, on one it cannot read without running the file. The conftest is written from
    *lines*, and the failure is on the last of them.

    pytest accepts any expression, such as a starred list or a name imported from another
    module. A bare ValueError from reading it would name no file. The tests-dev-only-lanes scope
    also fails on a statement that changes pytest_plugins in another form, such as appending to
    it in an if.
    """
    _write_project_of_every_scope(tmp_path)
    conftest = _write_module(tmp_path / "tests" / "conftest.py", *lines)

    with pytest.raises(AssertionError) as failure:
        _scope_named("tests-dev-only-lanes").select(tmp_path)

    message = str(failure.value)
    assert f"{conftest}:{len(lines)}" in message and quoted in message, (
        f"the failure does not name line {len(lines)} of {conftest}, nor the statement `{quoted}` "
        f"on it that the scope cannot read: {message}"
    )
    assert "literal" in message, f"the failure does not say that pytest_plugins must be a literal: {message}"


@pytest.mark.parametrize(
    ("lines", "statement", "clause"),
    [
        pytest.param(
            ("pytest_plugins = [1]",),
            "pytest_plugins = [1]",
            "whose value names 1, not a module name",
            id="an-int-entry",
        ),
        pytest.param(
            ("pytest_plugins = ['tests._plugin', None]",),
            "pytest_plugins = ['tests._plugin', None]",
            "whose value names None, not a module name",
            id="none-beside-a-module-name",
        ),
        pytest.param(
            ("pytest_plugins = (['tests._plugin'],)",),
            "pytest_plugins = (['tests._plugin'],)",
            "whose value names ['tests._plugin'], not a module name",
            id="a-nested-list-entry",
        ),
        pytest.param(
            ("pytest_plugins = 5",),
            "pytest_plugins = 5",
            "whose value is neither a str nor a list or tuple",
            id="an-int-for-the-whole-value",
        ),
        pytest.param(
            ("pytest_plugins = {}",),
            "pytest_plugins = {}",
            "whose value is neither a str nor a list or tuple",
            id="an-empty-dict-is-no-empty-value",
        ),
        pytest.param(
            ("pytest_plugins = []", "pytest_plugins += PLUGINS"),
            "pytest_plugins += PLUGINS",
            "whose value is not a literal",
            id="a-name-added-with-plus-equals",
        ),
        pytest.param(
            ("pytest_plugins = []", "pytest_plugins += [1]"),
            "pytest_plugins += [1]",
            "whose value names 1, not a module name",
            id="an-int-added-with-plus-equals",
        ),
        pytest.param(
            ('if sys.platform == "linux":', "    pytest_plugins = PLUGINS"),
            "pytest_plugins = PLUGINS",
            "whose value is not a literal",
            id="a-name-in-an-if",
        ),
        pytest.param(
            ("pytest_plugins, count = ['pytest_rerunfailures'], 1",),
            "pytest_plugins, count = (['pytest_rerunfailures'], 1)",
            _UNREADABLE_USE,
            id="a-tuple-target",
        ),
        pytest.param(
            ("plugins = pytest_plugins = ['pytest_rerunfailures']",),
            "plugins = pytest_plugins = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="chained-with-another-target",
        ),
        pytest.param(
            ("if (pytest_plugins := ['pytest_rerunfailures']): pass",),
            "if (pytest_plugins := ['pytest_rerunfailures']):",
            _UNREADABLE_USE,
            id="a-walrus-in-an-if-test",
        ),
        pytest.param(
            ("for pytest_plugins in [['pytest_rerunfailures']]: pass",),
            "for pytest_plugins in [['pytest_rerunfailures']]:",
            _UNREADABLE_USE,
            id="a-for-target",
        ),
        pytest.param(
            ("with contextlib.nullcontext(['pytest_rerunfailures']) as pytest_plugins: pass",),
            "with contextlib.nullcontext(['pytest_rerunfailures']) as pytest_plugins:",
            _UNREADABLE_USE,
            id="a-with-target",
        ),
        pytest.param(
            ("def configure():", "    global pytest_plugins"),
            "global pytest_plugins",
            _UNREADABLE_USE,
            id="a-global-declaration-in-a-function",
        ),
        pytest.param(
            (_ASSIGNS_PYTESTER, "pytest_plugins.append('pytest_rerunfailures')"),
            "pytest_plugins.append('pytest_rerunfailures')",
            _UNREADABLE_USE,
            id="appended",
        ),
        pytest.param(
            (_ASSIGNS_PYTESTER, "pytest_plugins.extend(['pytest_rerunfailures'])"),
            "pytest_plugins.extend(['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="extended-by-a-method",
        ),
        pytest.param(
            (_ASSIGNS_PYTESTER, "pytest_plugins.insert(0, 'pytest_rerunfailures')"),
            "pytest_plugins.insert(0, 'pytest_rerunfailures')",
            _UNREADABLE_USE,
            id="inserted",
        ),
        pytest.param(
            (_ASSIGNS_PYTESTER, 'if sys.platform == "linux":', "    pytest_plugins.append('pytest_rerunfailures')"),
            "pytest_plugins.append('pytest_rerunfailures')",
            _UNREADABLE_USE,
            id="appended-in-an-if",
        ),
        pytest.param(
            (_ASSIGNS_PYTESTER, "pytest_plugins[:0] = ['pytest_rerunfailures']"),
            "pytest_plugins[:0] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="a-slice-assigned",
        ),
        pytest.param(
            (_ASSIGNS_PYTESTER, "plugins = pytest_plugins"),
            "plugins = pytest_plugins",
            _UNREADABLE_USE,
            id="aliased",
        ),
        pytest.param(
            (_ASSIGNS_PYTESTER, "del pytest_plugins"),
            "del pytest_plugins",
            _UNREADABLE_USE,
            id="deleted",
        ),
        pytest.param(
            (_ASSIGNS_PYTESTER, "def configure():", "    pytest_plugins.append('pytest_rerunfailures')"),
            "pytest_plugins.append('pytest_rerunfailures')",
            _UNREADABLE_USE,
            id="appended-in-a-function",
        ),
        pytest.param(
            (_ASSIGNS_PYTESTER, "class Plugins:", "    pytest_plugins.append('pytest_rerunfailures')"),
            "pytest_plugins.append('pytest_rerunfailures')",
            _UNREADABLE_USE,
            id="appended-in-a-class-body",
        ),
        pytest.param(
            ("globals()['pytest_plugins'] = ['pytest_rerunfailures']",),
            "globals()['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="assigned-through-globals",
        ),
        pytest.param(
            ("def configure():", "    globals()['pytest_plugins'] = ['pytest_rerunfailures']"),
            "globals()['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="assigned-through-globals-in-a-function",
        ),
        pytest.param(
            (_ASSIGNS_PYTESTER, "vars()['pytest_plugins'].append('pytest_rerunfailures')"),
            "vars()['pytest_plugins'].append('pytest_rerunfailures')",
            _UNREADABLE_USE,
            id="appended-through-vars",
        ),
        pytest.param(
            ("locals()['pytest_plugins'] = ['pytest_rerunfailures']",),
            "locals()['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="assigned-through-locals",
        ),
        pytest.param(
            ("sys.modules[__name__].__dict__['pytest_plugins'] = ['pytest_rerunfailures']",),
            "sys.modules[__name__].__dict__['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="assigned-through-the-dict-of-the-module",
        ),
        pytest.param(
            (
                _ASSIGNS_PYTESTER,
                "def configure():",
                "    sys.modules[__name__].__dict__['pytest_plugins'].append('pytest_rerunfailures')",
            ),
            "sys.modules[__name__].__dict__['pytest_plugins'].append('pytest_rerunfailures')",
            _UNREADABLE_USE,
            id="appended-through-the-dict-of-the-module-in-a-function",
        ),
        pytest.param(
            ("module = sys.modules[__name__]", "module.__dict__['pytest_plugins'] = ['pytest_rerunfailures']"),
            "module.__dict__['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="assigned-through-the-dict-of-an-alias-of-the-module",
        ),
        pytest.param(
            ("try:", "    pass", "except Exception as pytest_plugins: pass"),
            "except Exception as pytest_plugins:",
            _UNREADABLE_USE,
            id="an-except-clause-name",
        ),
        pytest.param(
            ("try:", "    pass", "except* Exception as pytest_plugins: pass"),
            "except* Exception as pytest_plugins:",
            _UNREADABLE_USE,
            id="an-except-star-clause-name",
        ),
        pytest.param(
            ("match [['pytest_rerunfailures']]:", "    case [pytest_plugins]: pass"),
            "case [pytest_plugins]:",
            _UNREADABLE_USE,
            id="a-match-capture",
        ),
        pytest.param(
            ("match ['pytest_rerunfailures']:", "    case [*pytest_plugins]: pass"),
            "case [*pytest_plugins]:",
            _UNREADABLE_USE,
            id="a-match-star-capture",
        ),
        pytest.param(
            ("match {'plugin': 'pytest_rerunfailures'}:", "    case {**pytest_plugins}: pass"),
            "case {**pytest_plugins}:",
            _UNREADABLE_USE,
            id="a-match-mapping-rest",
        ),
        pytest.param(
            ("match ['pytest_rerunfailures']:", "    case [str()] as pytest_plugins: pass"),
            "case [str()] as pytest_plugins:",
            _UNREADABLE_USE,
            id="a-match-as-pattern",
        ),
        pytest.param(
            ("match sys.platform:", "    case _ if (pytest_plugins := ['pytest_rerunfailures']): pass"),
            "case _ if (pytest_plugins := ['pytest_rerunfailures']):",
            _UNREADABLE_USE,
            id="a-walrus-in-a-case-guard",
        ),
        pytest.param(
            (
                _ASSIGNS_PYTESTER,
                "match sys.platform:",
                "    case _ if pytest_plugins.append('pytest_rerunfailures'): pass",
            ),
            "case _ if pytest_plugins.append('pytest_rerunfailures'):",
            _UNREADABLE_USE,
            id="appended-in-a-case-guard",
        ),
        pytest.param(
            ("from tests._plugins import pytest_plugins",),
            "from tests._plugins import pytest_plugins",
            _UNREADABLE_USE,
            id="imported-from-a-module",
        ),
        pytest.param(
            ("from tests._plugins import PLUGINS as pytest_plugins",),
            "from tests._plugins import PLUGINS as pytest_plugins",
            _UNREADABLE_USE,
            id="imported-from-a-module-as-it",
        ),
        pytest.param(
            ("from tests._plugins import *",),
            "from tests._plugins import *",
            _UNREADABLE_USE,
            id="a-star-import",
        ),
        pytest.param(("def pytest_plugins(): pass",), "def pytest_plugins():", _UNREADABLE_USE, id="a-def"),
        pytest.param(
            ("async def pytest_plugins(): pass",),
            "async def pytest_plugins():",
            _UNREADABLE_USE,
            id="an-async-def",
        ),
        pytest.param(("class pytest_plugins: pass",), "class pytest_plugins:", _UNREADABLE_USE, id="a-class"),
        pytest.param(
            ('if sys.platform == "linux":', "    def pytest_plugins(): pass"),
            "def pytest_plugins():",
            _UNREADABLE_USE,
            id="a-def-in-an-if",
        ),
        pytest.param(
            ("sys.modules[__name__].pytest_plugins = ['pytest_rerunfailures']",),
            "sys.modules[__name__].pytest_plugins = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="an-attribute-of-the-module-assigned",
        ),
        pytest.param(
            (
                _ASSIGNS_PYTESTER,
                "def configure():",
                "    sys.modules[__name__].pytest_plugins.append('pytest_rerunfailures')",
            ),
            "sys.modules[__name__].pytest_plugins.append('pytest_rerunfailures')",
            _UNREADABLE_USE,
            id="an-attribute-of-the-module-appended-in-a-function",
        ),
        pytest.param(
            ("setattr(sys.modules[__name__], 'pytest_plugins', ['pytest_rerunfailures'])",),
            "setattr(sys.modules[__name__], 'pytest_plugins', ['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="set-by-setattr",
        ),
        pytest.param(
            (_ASSIGNS_PYTESTER, "getattr(sys.modules[__name__], 'pytest_plugins').append('pytest_rerunfailures')"),
            "getattr(sys.modules[__name__], 'pytest_plugins').append('pytest_rerunfailures')",
            _UNREADABLE_USE,
            id="appended-through-getattr",
        ),
        pytest.param(
            (_ASSIGNS_PYTESTER, "delattr(sys.modules[__name__], 'pytest_plugins')"),
            "delattr(sys.modules[__name__], 'pytest_plugins')",
            _UNREADABLE_USE,
            id="deleted-by-delattr",
        ),
        pytest.param(
            ("from tests._plugins import pytest_plugins as lane_plugins",),
            "from tests._plugins import pytest_plugins as lane_plugins",
            _UNREADABLE_USE,
            id="imported-under-another-name",
        ),
        pytest.param(
            ("def configure():", "    from tests._plugins import pytest_plugins"),
            "from tests._plugins import pytest_plugins",
            _UNREADABLE_USE,
            id="imported-in-a-function",
        ),
        pytest.param(
            ("globals().update(pytest_plugins=['pytest_rerunfailures'])",),
            "globals().update(pytest_plugins=['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="updated-through-globals-by-a-keyword",
        ),
        pytest.param(
            ("vars().update({'pytest_plugins': ['pytest_rerunfailures']})",),
            "vars().update({'pytest_plugins': ['pytest_rerunfailures']})",
            _UNREADABLE_USE,
            id="updated-through-vars-by-a-dict",
        ),
        pytest.param(
            ("locals().__setitem__('pytest_plugins', ['pytest_rerunfailures'])",),
            "locals().__setitem__('pytest_plugins', ['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="set-through-locals-by-setitem",
        ),
        pytest.param(
            ("sys.modules[__name__].__dict__.setdefault('pytest_plugins', ['pytest_rerunfailures'])",),
            "sys.modules[__name__].__dict__.setdefault('pytest_plugins', ['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="set-through-the-dict-of-the-module-by-setdefault",
        ),
        pytest.param(
            (_ASSIGNS_PYTESTER, "globals().get('pytest_plugins').append('pytest_rerunfailures')"),
            "globals().get('pytest_plugins').append('pytest_rerunfailures')",
            _UNREADABLE_USE,
            id="appended-through-a-get-of-globals",
        ),
        pytest.param(
            ("dict.update(globals(), pytest_plugins=['pytest_rerunfailures'])",),
            "dict.update(globals(), pytest_plugins=['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="updated-by-a-function-given-globals",
        ),
        pytest.param(
            ("sys._getframe().f_globals['pytest_plugins'] = ['pytest_rerunfailures']",),
            "sys._getframe().f_globals['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="assigned-through-the-globals-of-a-frame",
        ),
        pytest.param(
            ("sys._getframe().f_locals.setdefault('pytest_plugins', ['pytest_rerunfailures'])",),
            "sys._getframe().f_locals.setdefault('pytest_plugins', ['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="set-through-the-locals-of-a-frame",
        ),
        pytest.param(
            (
                "def configure(): pass",
                "configure.__globals__.__setitem__('pytest_plugins', ['pytest_rerunfailures'])",
            ),
            "configure.__globals__.__setitem__('pytest_plugins', ['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="set-through-the-globals-of-a-function",
        ),
        pytest.param(
            ("getattr(sys.modules[__name__], '__dict__')['pytest_plugins'] = ['pytest_rerunfailures']",),
            "getattr(sys.modules[__name__], '__dict__')['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="assigned-through-the-dict-of-the-module-by-getattr",
        ),
        pytest.param(
            ("namespace = globals()", "namespace['pytest_plugins'] = ['pytest_rerunfailures']"),
            "namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="assigned-through-a-variable-holding-globals",
        ),
        pytest.param(
            (
                "namespace: dict[str, object] = sys.modules[__name__].__dict__",
                "namespace.update(pytest_plugins=['pytest_rerunfailures'])",
            ),
            "namespace.update(pytest_plugins=['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="updated-through-an-annotated-variable-holding-the-dict-of-the-module",
        ),
        pytest.param(
            (
                "namespace = vars(sys.modules[__name__])",
                "alias = namespace",
                "alias.setdefault('pytest_plugins', ['pytest_rerunfailures'])",
            ),
            "alias.setdefault('pytest_plugins', ['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="set-through-an-alias-of-a-variable-holding-a-namespace",
        ),
        pytest.param(
            (
                "namespace = globals()",
                "def configure():",
                "    namespace.__setitem__('pytest_plugins', ['pytest_rerunfailures'])",
            ),
            "namespace.__setitem__('pytest_plugins', ['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="set-in-a-function-through-a-module-variable-holding-globals",
        ),
        pytest.param(
            (
                "def configure():",
                "    frame_globals = sys._getframe().f_globals",
                "    frame_globals.update(pytest_plugins=['pytest_rerunfailures'])",
            ),
            "frame_globals.update(pytest_plugins=['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="updated-through-a-function-variable-holding-the-globals-of-a-frame",
        ),
        pytest.param(
            ("(namespace := globals()).update(pytest_plugins=['pytest_rerunfailures'])",),
            "(namespace := globals()).update(pytest_plugins=['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="updated-through-a-walrus-of-globals",
        ),
        pytest.param(
            ("if (namespace := globals()): pass", "namespace['pytest_plugins'] = ['pytest_rerunfailures']"),
            "namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="assigned-through-a-variable-a-walrus-binds-to-globals",
        ),
        pytest.param(
            ("namespace = globals()", "namespace |= {'pytest_plugins': ['pytest_rerunfailures']}"),
            "namespace |= {'pytest_plugins': ['pytest_rerunfailures']}",
            _UNREADABLE_USE,
            id="updated-by-or-equals-through-a-variable-holding-globals",
        ),
        pytest.param(
            ("exec(\"pytest_plugins = ['pytest_rerunfailures']\")",),
            "exec(\"pytest_plugins = ['pytest_rerunfailures']\")",
            _UNREADABLE_USE,
            id="assigned-by-exec",
        ),
        pytest.param(
            ("exec(\"import sys; sys.modules['plugin'].pytest_plugins.append('pytest_rerunfailures')\", {})",),
            "exec(\"import sys; sys.modules['plugin'].pytest_plugins.append('pytest_rerunfailures')\", {})",
            _UNREADABLE_USE,
            id="appended-to-an-attribute-of-a-module-by-exec-in-a-namespace-of-its-own",
        ),
        pytest.param(
            (_SOURCE_ASSIGNING_RERUNFAILURES, "exec(SOURCE)"),
            "exec(SOURCE)",
            _UNREADABLE_USE,
            id="run-by-exec-of-code-it-cannot-read",
        ),
        pytest.param(
            (_SOURCE_ASSIGNING_RERUNFAILURES, "exec(SOURCE, None)"),
            "exec(SOURCE, None)",
            _UNREADABLE_USE,
            id="run-by-exec-given-none-for-globals",
        ),
        pytest.param(
            (_SOURCE_ASSIGNING_RERUNFAILURES, "exec(compile(SOURCE, 'plugins', 'exec'), globals())"),
            "exec(compile(SOURCE, 'plugins', 'exec'), globals())",
            _UNREADABLE_USE,
            id="run-by-exec-of-compiled-code-in-globals",
        ),
        pytest.param(
            (_SOURCE_ASSIGNING_RERUNFAILURES, "exec(SOURCE, globals=globals())"),
            "exec(SOURCE, globals=globals())",
            _UNREADABLE_USE,
            id="run-by-exec-given-globals-by-keyword",
        ),
        pytest.param(
            (
                _SOURCE_ASSIGNING_RERUNFAILURES,
                "namespace = globals()",
                "def configure():",
                "    exec(SOURCE, {}, namespace)",
            ),
            "exec(SOURCE, {}, namespace)",
            _UNREADABLE_USE,
            id="run-by-exec-with-locals-held-in-a-module-variable",
        ),
        pytest.param(
            ("eval(\"globals().setdefault('pytest_plugins', ['pytest_rerunfailures'])\")",),
            "eval(\"globals().setdefault('pytest_plugins', ['pytest_rerunfailures'])\")",
            _UNREADABLE_USE,
            id="set-by-eval",
        ),
        pytest.param(
            ("eval(\" globals().setdefault('pytest_plugins', ['pytest_rerunfailures'])\")",),
            "eval(\" globals().setdefault('pytest_plugins', ['pytest_rerunfailures'])\")",
            _UNREADABLE_USE,
            id="set-by-eval-of-code-with-a-leading-blank",
        ),
    ],
)
def test_undeclared_distributions_fails_naming_the_file_line_and_statement_of_a_pytest_plugins_it_cannot_read(
    tmp_path: Path,
    lines: tuple[str, ...],
    statement: str,
    clause: str,
) -> None:
    """A pytest_plugins the detector cannot read fails it, wherever a statement of the module's own
    scope gives or binds it. Its value may be no str, list or tuple of str, nor a literal. The name
    may be bound by a tuple, a walrus, a for, a with, an except clause, of a try* too, a capture
    of a match pattern or a from-import, a star import among them; be the name of a def or class;
    sit beside another target of a chained assignment, which aliases the list; or be declared
    global in a function. It may also be read or deleted in any scope, function and class bodies
    included, as a method call such as append, a subscript, an alias or a del does, and a read may
    sit in a case guard. Or a namespace may be subscripted with the name, |='d with it, or be given
    it in a call: of a method of the namespace such as update, __setitem__, setdefault or get,
    which hands out the list as surely as the others write it, or of a function given the
    namespace, such as dict.update. A namespace is the dict that globals(), locals() or vars()
    returns, the __dict__ of an object such as sys.modules[__name__], also when reached through
    getattr, the f_globals or f_locals of a frame, or the __globals__ of a function. It may also be
    held in a name that an assignment, an annotated assignment or a walrus binds to one, directly
    or through an alias; such a name counts in that scope, and in a scope nested there that does
    not rebind it. Or an attribute pytest_plugins of an object may be reached directly, through
    getattr, setattr or delattr, or by a from-import of that name, in any position or scope.

    exec or eval may run a literal whose code binds or uses the name, as a module would, or does
    not parse as one. They may also run other code in a namespace that may be the module's: the
    caller's, when given no globals or None for them, or a namespace given for globals or locals.

    pytest accepts None, a str or a sequence only, and imports each entry as a module name, so an int
    read as one would otherwise fail on its first string method, naming no file. Only None and the
    empty str name no plugin, so an empty dict fails like any other value of the wrong type.

    The failure names the file, the line and the statement, or the except or case clause, that starts
    on the last of *lines*, as written, or by its first line when it is compound, with what is wrong
    with it. An augmented assignment is quoted whole, not described as setting pytest_plugins, and
    an except clause of a try* keeps its star. It says how to write pytest_plugins instead: as a
    literal list or tuple of module names, added to only with += and such a literal.
    """
    prefix = ("import contextlib", "import sys", 'PLUGINS = ["pytester"]')
    plugin = _write_module(tmp_path / "plugin.py", *prefix, *lines)
    line = len(prefix) + len(lines)

    with pytest.raises(AssertionError) as failure:
        undeclared_distributions(tmp_path, [plugin], declared={"pytest"})

    message = str(failure.value)
    assert f"{plugin}:{line} has `{statement}`, {clause}" in message, (
        f"the failure does not name line {line} of {plugin}, the statement `{statement}` on it and "
        f"what is wrong with it, `{clause}`: {message}"
    )
    advice = message.partition(clause)[2]
    assert "list or tuple of module names" in advice and "+=" in advice, (
        "the failure does not say, after the clause, how to write pytest_plugins: a literal list or "
        f"tuple of module names, added to only with +=: {message}"
    )


@pytest.mark.parametrize(
    "lines",
    [
        pytest.param(
            ("settings = {}", "settings['pytest_plugins'] = ['pytest_rerunfailures']"),
            id="a-key-of-another-dict",
        ),
        pytest.param(
            ("SOURCE = \"pytest_plugins.append('pytest_rerunfailures')\"",),
            id="spelled-in-a-string",
        ),
        pytest.param(("import sys", "hasattr(sys.modules[__name__], 'pytest_plugins')"), id="tested-by-hasattr"),
        pytest.param(
            ("import sys", "sys.modules[__name__].__dict__['other_plugins'] = ['pytest_rerunfailures']"),
            id="another-key-of-the-dict-of-the-module",
        ),
        pytest.param(
            ("settings = {}", "settings.update(pytest_plugins=['pytest_rerunfailures'])"),
            id="a-keyword-of-another-dicts-method",
        ),
        pytest.param(
            ("globals().update(other_plugins=['pytest_rerunfailures'])",),
            id="another-key-updated-through-globals",
        ),
        pytest.param(
            ("import sys", "sys._getframe().f_builtins['pytest_plugins'] = ['pytest_rerunfailures']"),
            id="a-key-of-the-builtins-of-a-frame",
        ),
        pytest.param(
            ("namespace = dict(globals())", "namespace['pytest_plugins'] = ['pytest_rerunfailures']"),
            id="a-key-of-a-copy-of-a-namespace",
        ),
        pytest.param(
            (
                "def configure():",
                "    namespace = globals()",
                "def report():",
                "    namespace = {}",
                "    namespace.update(pytest_plugins=['pytest_rerunfailures'])",
            ),
            id="a-name-holding-a-namespace-in-another-function",
        ),
        pytest.param(
            (
                "namespace = globals()",
                "def report():",
                "    namespace = {}",
                "    namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            ),
            id="a-module-variable-holding-globals-rebound-in-a-function",
        ),
        pytest.param(
            ("PLUGINS = []", "exec(\"PLUGINS.append('pytester')\", globals())"),
            id="exec-of-code-that-names-no-pytest-plugins-in-globals",
        ),
        pytest.param(
            (
                "import sys",
                _SOURCE_ASSIGNING_RERUNFAILURES,
                "namespace = dict(vars(sys.modules[__name__]))",
                "exec(SOURCE, namespace)",
            ),
            id="exec-of-code-it-cannot-read-in-a-copy-of-the-module-namespace",
        ),
        pytest.param(
            (_SOURCE_ASSIGNING_RERUNFAILURES, "loader = object()", "loader.exec(SOURCE)"),
            id="a-method-named-exec-of-another-object",
        ),
    ],
)
def test_undeclared_distributions_ignores_what_only_resembles_a_use_of_pytest_plugins(
    tmp_path: Path,
    lines: tuple[str, ...],
) -> None:
    """Only the name pytest_plugins, its entry in a namespace, the dict that globals(), locals() or
    vars() returns, the __dict__ of an object, the f_globals or f_locals of a frame or the
    __globals__ of a function, or an attribute of that name, reached directly, through getattr,
    setattr or delattr, or by a from-import, reaches the attribute of the module. So does the name
    given in a call on a namespace.

    The same key of another dict, or given to another dict's method, another key of a namespace,
    or another key given to a namespace's method, a string that spells such a statement, and
    hasattr, which only tests for the attribute, require nothing and fail nothing. Nor does a key
    of a frame's f_builtins, which pytest, reading an attribute of the module, never consults, nor
    one of a copy of a namespace, nor one of a name bound to a namespace only in another function
    or rebound in this one.

    Code that names no pytest_plugins does not fail when exec runs it, wherever it runs. Nor does
    code it cannot read that exec runs in a namespace of its own, such as a copy of the module's,
    or a method named exec of another object.
    """
    resembling = _write_module(tmp_path / "resembling.py", *lines)

    assert undeclared_distributions(tmp_path, [resembling], declared={"pytest"}) == [], (
        "the undeclared-distributions detector found a use of pytest_plugins, or a requirement of "
        f"pytest-rerunfailures, in a file that only resembles one, with these lines: {lines}"
    )


@pytest.mark.parametrize(
    "level",
    [pytest.param(3, id="out-of-the-project"), pytest.param(100, id="above-the-filesystem-root")],
)
def test_a_scope_fails_naming_the_file_and_line_of_a_relative_import_that_leaves_the_project(
    tmp_path: Path,
    level: int,
) -> None:
    """A scope that follows relative imports fails, naming the file, the line and the import, on one
    that climbs out of the project root.

    Python rejects a relative import beyond its top-level package, so no working suite holds one.
    The contract names it, instead of raising an IndexError or resolving against a directory
    outside the project.
    """
    _write_project_of_every_scope(tmp_path)
    relative_import = f"from {'.' * level} import elsewhere"
    conftest = _write_module(tmp_path / "tests" / "conftest.py", relative_import)

    with pytest.raises(AssertionError) as failure:
        _scope_named("tests-dev-only-lanes").select(tmp_path)

    message = str(failure.value)
    assert f"{conftest}:1" in message and relative_import in message, (
        f"the failure does not name line 1 of {conftest}, nor the import `{relative_import}` "
        f"on it that climbs out of the project root: {message}"
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
