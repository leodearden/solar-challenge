# SPDX-License-Identifier: AGPL-3.0-or-later
"""The built-in scenarios: the YAML files of the project's scenarios/ directory, each named by its file's stem."""

from collections.abc import Mapping
from pathlib import Path

_SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "scenarios"

#: A scenario file's suffixes, in preference order: a name with a file of each means the first.
_SUFFIXES = (".yaml", ".yml")


def builtin_scenario_files() -> Mapping[str, Path]:
    """Each built-in scenario file by its name: :func:`scenario_files_in` the scenarios/ directory, which an installed package does not have."""
    return scenario_files_in(_SCENARIOS_DIR)


def scenario_files_in(directory: Path) -> Mapping[str, Path]:
    """Each scenario file in *directory* by its name, in name order: a name with both a .yaml and a .yml file means its .yaml file. Empty when *directory* is absent."""
    if not directory.is_dir():
        return {}
    files_by_name: dict[str, list[Path]] = {}
    for path in directory.iterdir():
        if path.suffix in _SUFFIXES and path.is_file():
            files_by_name.setdefault(path.stem, []).append(path)
    return {
        name: min(files, key=lambda path: _SUFFIXES.index(path.suffix))
        for name, files in sorted(files_by_name.items())
    }
