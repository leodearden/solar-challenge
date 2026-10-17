# SPDX-License-Identifier: AGPL-3.0-or-later
"""The solar_challenge package and every module beneath it, imported, for the tests that inspect the whole package.

Importing every module imports the web subpackage too, so a caller needs the web
extra, and skips without it as the web tests do.

Usage::

    from tests._package_modules import package_modules

    for module in package_modules():
        found = doctest.DocTestFinder().find(module)
"""

import importlib
import pkgutil
from types import ModuleType

import solar_challenge


def package_modules() -> list[ModuleType]:
    """Return solar_challenge and every module beneath it, imported."""
    walk = pkgutil.walk_packages(solar_challenge.__path__, f"{solar_challenge.__name__}.")
    return [solar_challenge, *(importlib.import_module(info.name) for info in walk)]
