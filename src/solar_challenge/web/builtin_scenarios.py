# SPDX-License-Identifier: AGPL-3.0-or-later
"""The built-in scenarios: the YAML files of the project's scenarios/ directory, each named by its file's stem, and those a page's importer loads as its form.

A page offers as presets the built-in scenarios its importer loads, and loads one through
:func:`builtin_scenario_form`; the importer is the page's, so this module imports no form.
"""

import functools
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeVar

from solar_challenge.web.request_boundary import refusal_text

logger = logging.getLogger(__name__)

#: A page's form, as its importer reads one from a scenario's YAML text.
T = TypeVar("T")

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


def builtin_scenarios_loaded_by(importer: Callable[[str], object]) -> tuple[str, ...]:
    """The name of each built-in scenario file *importer* loads, in name order: :func:`scenario_files_loaded_by` the built-in files."""
    return scenario_files_loaded_by(builtin_scenario_files(), importer)


def scenario_files_loaded_by(files: Mapping[str, Path], importer: Callable[[str], object]) -> tuple[str, ...]:
    """The name of each of the scenario *files* *importer*, a page's reader of scenario YAML as its form, loads, in their order.

    A file that cannot be read as UTF-8 text does not load either; a warning names it.
    """
    return tuple(name for name, path in files.items() if _loads(path, importer))


def builtin_scenario_form(name: str, importer: Callable[[str], T]) -> T | None:
    """The form *importer* reads from the built-in scenario file *name*; None when no built-in scenario file is named *name*.

    Raises:
        ConfigurationError: As *importer* raises it, for a file the page's form cannot load;
            so does any other ValueError *importer* raises.
    """
    path = builtin_scenario_files().get(name)
    return None if path is None else importer(_scenario_text(path))


def _scenario_text(path: Path) -> str:
    """The text of the scenario file at *path*: UTF-8 YAML."""
    return path.read_text(encoding="utf-8")


def _loads(path: Path, importer: Callable[[str], object]) -> bool:
    """Whether *importer* loads the scenario file at *path*: not a scenario it refuses, which a DEBUG record names with the refusal, nor a file that cannot be read as UTF-8 text, which a warning names."""
    try:
        yaml_text = _scenario_text(path)
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(
            "Scenario file %s is not offered as a preset, since it cannot be read as UTF-8 text: %s",
            path,
            exc,
        )
        return False
    refusal = _yaml_refusal(yaml_text, importer)
    if refusal is not None:
        logger.debug("Scenario file %s is not offered as a preset, since the page's form refuses it: %s", path, refusal)
    return refusal is None


@functools.lru_cache
def _yaml_refusal(yaml_text: str, importer: Callable[[str], object]) -> str | None:
    """*importer*'s refusal of the scenario YAML *yaml_text*, as refusal_text answers it; None when it loads it. Memoised by the text itself and the importer, so an edited file is judged afresh.

    A ValueError that is not a ConfigurationError is a refusal too, which refusal_text logs
    once, at ERROR, as a probable defect.
    """
    try:
        importer(yaml_text)
    except ValueError as refusal:
        return refusal_text(refusal)
    return None
