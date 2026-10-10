# SPDX-License-Identifier: AGPL-3.0-or-later
"""The built-in scenarios: the YAML files of the project's scenarios/ directory, each named by its file's stem."""

from collections.abc import Mapping
from pathlib import Path

_SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "scenarios"

#: A scenario file's suffixes, in preference order: a name with a file of each means the first.
_SUFFIXES = (".yaml", ".yml")


def builtin_scenario_files() -> Mapping[str, Path]:
    """Each built-in scenario file by its name, in name order: a name with both a .yaml and a .yml file means its .yaml file. Empty when the scenarios/ directory is absent, as in an installed package."""
    if not _SCENARIOS_DIR.is_dir():
        return {}
    files: dict[str, Path] = {}
    for suffix in _SUFFIXES:
        for path in _SCENARIOS_DIR.iterdir():
            if path.suffix == suffix and path.is_file():
                files.setdefault(path.stem, path)
    return dict(sorted(files.items()))
