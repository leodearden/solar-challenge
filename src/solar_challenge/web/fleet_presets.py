# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet page's presets: the built-in scenario files its form loads, each named by its file's stem."""

import functools
import logging
from collections.abc import Mapping
from pathlib import Path

from solar_challenge.web.builtin_scenarios import builtin_scenario_files
from solar_challenge.web.fleet_scenario import (
    FLEET_FORM_REFUSALS,
    ImportedFleetForm,
    fleet_form_from_yaml,
)

logger = logging.getLogger(__name__)


def fleet_preset_names() -> tuple[str, ...]:
    """The name of each built-in scenario file :func:`fleet_preset_form` loads, in name order."""
    return fleet_preset_names_among(builtin_scenario_files())


def fleet_preset_names_among(files: Mapping[str, Path]) -> tuple[str, ...]:
    """The name of each of the scenario *files* the fleet form loads, in their order.

    A file that cannot be read as UTF-8 text does not load either; a warning names it.
    """
    return tuple(name for name, path in files.items() if _loads(path))


def fleet_preset_form(name: str) -> ImportedFleetForm | None:
    """The fleet form the built-in scenario file *name* describes; None when no built-in scenario file is named *name*.

    Raises:
        ValueError, TypeError, ConfigurationError: As fleet_form_from_yaml
            (FLEET_FORM_REFUSALS), for a file the fleet form cannot load.
    """
    path = builtin_scenario_files().get(name)
    return None if path is None else fleet_form_from_yaml(_preset_text(path))


def _preset_text(path: Path) -> str:
    """The text of the scenario file at *path*: UTF-8 YAML."""
    return path.read_text(encoding="utf-8")


def _loads(path: Path) -> bool:
    """Whether the fleet form loads the scenario file at *path*: not a scenario it refuses, nor a file that cannot be read as UTF-8 text, which a warning names."""
    try:
        yaml_text = _preset_text(path)
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(
            "Scenario file %s is not offered as a fleet preset, since it cannot be read as UTF-8 text: %s",
            path,
            exc,
        )
        return False
    return _yaml_loads(yaml_text)


@functools.lru_cache
def _yaml_loads(yaml_text: str) -> bool:
    """Whether the fleet form loads the scenario YAML *yaml_text*, rather than refusing it; memoised by the text itself, so an edited file is judged afresh."""
    try:
        fleet_form_from_yaml(yaml_text)
    except FLEET_FORM_REFUSALS:
        return False
    return True
