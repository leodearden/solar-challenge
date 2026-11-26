# SPDX-License-Identifier: AGPL-3.0-or-later
"""The solar_challenge modules, imported, and the dataclasses a module defines, for the tests that inspect the package.

package_modules is solar_challenge and every module beneath it. Importing every module imports the web subpackage too,
so its caller needs the web extra, and skips without it as the web tests do. top_level_modules is the modules directly
under solar_challenge that are not packages, so it leaves out web and cli.

Usage::

    from tests._package_modules import module_level_dataclasses, package_modules

    for module in package_modules():
        for cls in module_level_dataclasses(module):
            ...
"""

import dataclasses
import importlib
import pkgutil
from types import ModuleType

import solar_challenge


def package_modules() -> list[ModuleType]:
    """Return solar_challenge and every module beneath it, imported."""
    walk = pkgutil.walk_packages(solar_challenge.__path__, f"{solar_challenge.__name__}.")
    return [solar_challenge, *(importlib.import_module(info.name) for info in walk)]


def top_level_modules() -> list[ModuleType]:
    """Return each module directly under solar_challenge that is not a package, imported."""
    listing = pkgutil.iter_modules(solar_challenge.__path__, f"{solar_challenge.__name__}.")
    return [importlib.import_module(info.name) for info in listing if not info.ispkg]


def module_level_dataclasses(module: ModuleType) -> list[type]:
    """Return the dataclasses *module* defines at its top level."""
    return [
        value
        for value in vars(module).values()
        if isinstance(value, type) and value.__module__ == module.__name__ and dataclasses.is_dataclass(value)
    ]
