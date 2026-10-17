# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fixtures more than one rule module of this package uses.

Outer and Preset are defined at module level, where a qualified name carries no
'<locals>'; a rule module that imports them binds their names for its own forward
references to resolve. imported_module writes a module and imports it, for the rules
about the module a name is read in.
"""

import importlib.util
import pathlib
import sys
import types
from dataclasses import dataclass

import pytest


class Outer:
    class Inner:
        pass


@dataclass(frozen=True)
class Preset:
    rate: float


_source_by_name: dict[str, str] = {}


def imported_module(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str, source: str
) -> types.ModuleType:
    """The module *name*, written from *source* under *tmp_path* and imported, left in sys.modules until the test ends.

    Raises ValueError naming *name* if an earlier call in this process imported it from
    another source.
    """
    if _source_by_name.get(name, source) != source:
        raise ValueError(
            f"The module name {name!r} was already imported from another source: the "
            "helper under test reads a module's `if TYPE_CHECKING:` imports once per "
            "name, so give this test's module a name no other test uses"
        )
    _source_by_name[name] = source
    path = tmp_path / f"{name}.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module
