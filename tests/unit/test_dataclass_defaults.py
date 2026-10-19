# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every module-level dataclass field default in solar_challenge is hashable, as dataclasses requires of a default.

dataclasses refuses an unhashable default when it defines the class. Python 3.11
judges that by the default's class, and 3.12 made MappingProxyType's class
hashable, so `MappingProxyType({})` as a default imports on the 3.12 pin but
stops its module importing on 3.11, which requires-python admits. hash() of such
a default fails on every minor, so this test finds it on the pin, in every
verify; the offline lane's interpreter matrix (tests/interpreter_matrix) remains
the authoritative check, and the only one for a dataclass nested in a class.
Finding the dataclasses imports every module, the web subpackage's too, so like
the web tests it needs the web extra.
"""

import dataclasses
from types import ModuleType

import pytest

from tests._package_modules import package_modules

pytest.importorskip("flask")


def _module_level_dataclasses(module: ModuleType) -> list[type]:
    """Return the dataclasses *module* defines at its top level."""
    return [
        value
        for value in vars(module).values()
        if isinstance(value, type) and value.__module__ == module.__name__ and dataclasses.is_dataclass(value)
    ]


def _is_hashable(value: object) -> bool:
    """Return whether hash() accepts *value*."""
    try:
        hash(value)
    except TypeError:
        return False
    return True


def _unhashable_field_defaults() -> dict[str, str]:
    """Return the repr of each unhashable field default of a module-level dataclass, keyed by the field's dotted name."""
    return {
        f"{module.__name__}.{cls.__qualname__}.{field.name}": repr(field.default)
        for module in package_modules()
        for cls in _module_level_dataclasses(module)
        for field in dataclasses.fields(cls)
        if field.default is not dataclasses.MISSING and not _is_hashable(field.default)
    }


def test_every_module_level_dataclass_field_default_in_the_package_is_hashable() -> None:
    """No dataclass a solar_challenge module defines at its top level has a field default that hash() refuses."""
    unhashable = _unhashable_field_defaults()

    assert unhashable == {}, (
        f"these dataclass fields have unhashable defaults: {unhashable}. dataclasses does not allow an "
        "unhashable default: it refuses one whose class it judges unhashable when it defines the class, as "
        "Python 3.11 judges MappingProxyType's, so a module with such a default does not import there. Give "
        "each field a default_factory instead: dataclasses.field(default_factory=...)."
    )
