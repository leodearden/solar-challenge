# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_pytest_plugins_reader.py, which reads the modules pytest imports for a module's pytest_plugins."""

import ast
from pathlib import Path

import pytest

from tests._pytest_plugins_reader import plugin_imports

_PLUGIN = Path("plugin.py")
_ASSIGNS_RERUNFAILURES = 'pytest_plugins = ["pytest_rerunfailures"]'
_SOURCE_ASSIGNING_RERUNFAILURES = 'SOURCE = "pytest_plugins = [\'pytest_rerunfailures\']"'
_ASSIGNS_PYTESTER = 'pytest_plugins = ["pytester"]'
_UNREADABLE_USE = "which can bind or change pytest_plugins in a form the contract cannot read"


def _plugin_modules(*lines: str) -> list[str]:
    """Return the module of each import plugin_imports yields, in order, for the module of *lines* at
    _PLUGIN. No file is written: plugin_imports reads only the syntax tree, and names the path only in
    a failure.
    """
    tree = ast.parse("".join(f"{line}\n" for line in lines))
    return [alias.name for node in plugin_imports(_PLUGIN, tree) for alias in node.names]


@pytest.mark.parametrize(
    ("lines", "modules"),
    [
        pytest.param(
            ("pytest_plugins = []", 'pytest_plugins += ["pytest_rerunfailures"]'),
            ("pytest_rerunfailures",),
            id="extended-with-plus-equals",
        ),
        pytest.param(
            ('pytest_plugins = "pytester"', 'pytest_plugins += ",pytest_rerunfailures"'),
            ("_pytest.pytester", "pytest_rerunfailures"),
            id="a-str-extended-after-a-comma",
        ),
        pytest.param(
            ('if sys.platform == "linux":', f"    {_ASSIGNS_RERUNFAILURES}"),
            ("pytest_rerunfailures",),
            id="in-an-if",
        ),
        pytest.param(
            ("if not sys.platform:", "    pass", "else:", f"    {_ASSIGNS_RERUNFAILURES}"),
            ("pytest_rerunfailures",),
            id="in-an-else",
        ),
        pytest.param(
            ("try:", f"    {_ASSIGNS_RERUNFAILURES}", "except Exception:", "    pass"),
            ("pytest_rerunfailures",),
            id="in-a-try",
        ),
        pytest.param(
            ("try:", "    pass", "except Exception:", f"    {_ASSIGNS_RERUNFAILURES}"),
            ("pytest_rerunfailures",),
            id="in-an-except-handler",
        ),
        pytest.param(
            ("try:", "    pass", "finally:", f"    {_ASSIGNS_RERUNFAILURES}"),
            ("pytest_rerunfailures",),
            id="in-a-finally",
        ),
        pytest.param(
            ("try:", "    pass", "except* Exception:", f"    {_ASSIGNS_RERUNFAILURES}"),
            ("pytest_rerunfailures",),
            id="in-an-except-star-handler",
        ),
        pytest.param(
            ("with contextlib.suppress(Exception):", f"    {_ASSIGNS_RERUNFAILURES}"),
            ("pytest_rerunfailures",),
            id="in-a-with",
        ),
        pytest.param(
            ("for _ in range(1):", f"    {_ASSIGNS_RERUNFAILURES}"),
            ("pytest_rerunfailures",),
            id="in-a-for",
        ),
        pytest.param(
            ("while True:", f"    {_ASSIGNS_RERUNFAILURES}", "    break"),
            ("pytest_rerunfailures",),
            id="in-a-while",
        ),
        pytest.param(
            ("match sys.platform:", "    case _:", f"        {_ASSIGNS_RERUNFAILURES}"),
            ("pytest_rerunfailures",),
            id="in-a-match-case",
        ),
        pytest.param(
            (
                'if sys.platform == "linux":',
                "    if sys.version_info >= (3, 11):",
                f"        {_ASSIGNS_RERUNFAILURES}",
            ),
            ("pytest_rerunfailures",),
            id="two-blocks-deep",
        ),
        pytest.param(
            ('if sys.platform == "linux":', '    pytest_plugins: list[str] = ["pytest_rerunfailures"]'),
            ("pytest_rerunfailures",),
            id="annotated-in-an-if",
        ),
        pytest.param(
            (
                'pytest_plugins = ["pytester"]',
                'if sys.platform == "linux":',
                '    pytest_plugins += ("pytest_rerunfailures",)',
            ),
            ("_pytest.pytester", "pytest_rerunfailures"),
            id="extended-in-an-if",
        ),
    ],
)
def test_plugin_imports_reads_every_pytest_plugins_entry_its_module_scope_gives(
    lines: tuple[str, ...],
    modules: tuple[str, ...],
) -> None:
    """plugin_imports yields an import of the module pytest imports for each pytest_plugins entry,
    wherever a statement of the module's own scope gives it.

    pytest reads pytest_plugins as an attribute of the module once the module has run, so an
    augmented assignment adds its entries to those the assignment before it gave. A str extended
    after a comma adds the names after the comma, not the empty piece before it. An assignment,
    annotated or not, in any block of a compound statement, however deep, counts as well. A
    built-in plugin's short name, such as pytester, names that module of pytest's own _pytest
    package.
    """
    found = _plugin_modules("import contextlib", "import sys", *lines)

    assert found == list(modules), (
        f"plugin_imports yielded imports of {found}, not of {list(modules)}, the modules pytest "
        f"imports for the entries a module gives pytest_plugins with these lines: {lines}"
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
def test_plugin_imports_ignores_a_pytest_plugins_that_binds_no_attribute_of_its_module(
    lines: tuple[str, ...],
) -> None:
    """plugin_imports yields nothing for a pytest_plugins that binds no attribute of the module,
    wherever the def or class around it stands in the module.

    A function that declares no global binds it as a local, in whatever form, and a class as an
    attribute of the class: pytest reads neither. An annotation with no value assigns nothing.
    """
    found = _plugin_modules("import sys", *lines)

    assert found == [], (
        f"plugin_imports yielded imports of {found} from a pytest_plugins that binds no attribute of "
        f"its module, with these lines: {lines}"
    )


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
        pytest.param(
            ("exec(\"pytest_plugins, count = ['pytest_rerunfailures'], 1\")",),
            "exec(\"pytest_plugins, count = ['pytest_rerunfailures'], 1\")",
            _UNREADABLE_USE,
            id="bound-by-a-tuple-target-in-exec",
        ),
        pytest.param(
            (
                "namespace = globals()",
                "class Settings:",
                "    namespace = {}",
                "    def configure(self):",
                "        namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            ),
            "namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="set-in-a-method-through-a-module-variable-holding-globals-that-its-class-rebinds",
        ),
        pytest.param(
            (
                "def configure():",
                "    namespace = globals()",
                "    class Settings:",
                "        def apply(self):",
                "            namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            ),
            "namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="set-in-a-method-through-a-function-variable-holding-globals-around-its-class",
        ),
        pytest.param(
            (
                "def configure():",
                "    global namespace",
                "    namespace = globals()",
                "configure()",
                "namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            ),
            "namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="assigned-through-a-module-variable-a-function-binds-to-globals-as-a-global",
        ),
        pytest.param(
            (
                "def configure():",
                "    global namespace",
                "    namespace = globals()",
                "def apply():",
                "    namespace.update(pytest_plugins=['pytest_rerunfailures'])",
            ),
            "namespace.update(pytest_plugins=['pytest_rerunfailures'])",
            _UNREADABLE_USE,
            id="updated-in-a-function-through-a-variable-another-function-binds-to-globals-as-a-global",
        ),
        pytest.param(
            (
                "class Settings:",
                "    def configure(self):",
                "        global namespace",
                "        namespace = globals()",
                "namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            ),
            "namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="assigned-through-a-module-variable-a-method-binds-to-globals-as-a-global",
        ),
        pytest.param(
            (
                "def outer():",
                "    namespace = {}",
                "    def inner():",
                "        nonlocal namespace",
                "        namespace = globals()",
                "    inner()",
                "    namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            ),
            "namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            _UNREADABLE_USE,
            id="assigned-through-a-variable-an-inner-function-binds-to-globals-as-a-nonlocal",
        ),
    ],
)
def test_plugin_imports_fails_naming_the_file_line_and_statement_of_a_pytest_plugins_it_cannot_read(
    lines: tuple[str, ...],
    statement: str,
    clause: str,
) -> None:
    """plugin_imports fails on a pytest_plugins it cannot read, wherever the module's code gives,
    binds or changes it: a value that is no literal str, list or tuple of str; a binding of the name
    in a form the contract does not follow; a read of the name, which can change the list it holds;
    an entry of the module's namespace, or an attribute of the module, reached under the name,
    directly, through a name that holds the namespace, or through exec or eval of code that does.

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
    line = len(prefix) + len(lines)

    with pytest.raises(AssertionError) as failure:
        _plugin_modules(*prefix, *lines)

    message = str(failure.value)
    assert f"{_PLUGIN}:{line} has `{statement}`, {clause}" in message, (
        f"the failure does not name line {line} of {_PLUGIN}, the statement `{statement}` on it and "
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
        pytest.param(
            (
                "namespace = {}",
                "class Settings:",
                "    namespace = globals()",
                "    def configure(self):",
                "        namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            ),
            id="a-class-variable-holding-globals-that-a-method-cannot-see",
        ),
        pytest.param(
            (
                "namespace = {}",
                "def configure():",
                "    namespace = globals()",
                "namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            ),
            id="a-function-variable-holding-globals-that-is-no-global",
        ),
        pytest.param(
            (
                "def configure():",
                "    global namespace",
                "    namespace = dict(globals())",
                "namespace['pytest_plugins'] = ['pytest_rerunfailures']",
            ),
            id="a-copy-of-globals-a-function-binds-as-a-global",
        ),
    ],
)
def test_plugin_imports_ignores_what_only_resembles_a_use_of_pytest_plugins(
    lines: tuple[str, ...],
) -> None:
    """plugin_imports neither yields nor fails on what only resembles a use of pytest_plugins: the
    same key of another dict, another key of a namespace, a string that spells a use, hasattr, which
    only tests for the attribute, and a key of something pytest never consults for the module's
    attribute, such as a frame's f_builtins or a copy of a namespace.

    A name holds a namespace only where Python resolves it to a binding that gives it one: a name
    so bound in another scope, rebound in this one, bound in a class whose methods cannot see it,
    or bound in a function without a global declaration does not.

    Code that names no pytest_plugins does not fail when exec runs it, wherever it runs. Nor does
    code it cannot read that exec runs in a namespace of its own, such as a copy of the module's,
    or a method named exec of another object.
    """
    found = _plugin_modules(*lines)

    assert found == [], (
        f"plugin_imports yielded imports of {found} from a module that only resembles a use of "
        f"pytest_plugins, with these lines: {lines}"
    )
