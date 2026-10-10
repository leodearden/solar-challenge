# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet page's presets: the built-in scenario files its form loads, each named by its file's stem."""

from pathlib import Path

from solar_challenge.web.builtin_scenarios import builtin_scenario_files
from solar_challenge.web.fleet_scenario import (
    FLEET_FORM_REFUSALS,
    ImportedFleetForm,
    fleet_form_from_yaml,
)


def fleet_preset_names() -> tuple[str, ...]:
    """The name of each built-in scenario file :func:`fleet_preset_form` loads, in name order."""
    return tuple(name for name, path in builtin_scenario_files().items() if _loads(path))


def fleet_preset_form(name: str) -> ImportedFleetForm | None:
    """The fleet form the built-in scenario file *name* describes; None when no built-in scenario file is named *name*.

    Raises:
        ValueError, TypeError, ConfigurationError: As fleet_form_from_yaml
            (FLEET_FORM_REFUSALS), for a file the fleet form cannot load.
    """
    path = builtin_scenario_files().get(name)
    return None if path is None else _preset_form(path)


def _preset_form(path: Path) -> ImportedFleetForm:
    """The fleet form the scenario file at *path*, UTF-8 YAML, describes."""
    return fleet_form_from_yaml(path.read_text(encoding="utf-8"))


def _loads(path: Path) -> bool:
    """Whether the fleet form loads the scenario file at *path*, rather than refusing it."""
    try:
        _preset_form(path)
    except FLEET_FORM_REFUSALS:
        return False
    return True
