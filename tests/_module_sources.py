# SPDX-License-Identifier: AGPL-3.0-or-later
"""The source file of a package module, by its dotted name, for the guards that parse the package's source.

Usage::

    from tests._module_sources import module_source

    tree = ast.parse(module_source(src_dir, "solar_challenge.config").read_text(encoding="utf-8"))
"""

from pathlib import Path


def module_source(src_dir: Path, module: str) -> Path:
    """Return the file under *src_dir* that holds *module*, a module of the package that is no package itself."""
    return src_dir.joinpath(*module.split(".")).with_suffix(".py")
