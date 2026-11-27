# SPDX-License-Identifier: AGPL-3.0-or-later
"""The typed blocks a dashboard page's form offers, a tariff or a dispatch strategy, as the page shows, starts and reads them.

Each type a page offers for a block is a FormChoice, and each setting it holds for that
type a FormSetting.  fleet_scenario.py declares the fleet page's tables of them, which the
page renders; an import reads a block through each choice's held_type, the view
scenario_import.py's read_typed_block takes.  flat_rate_choice is the one flat-rate tariff
every form holds.
"""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

from solar_challenge.number_fields import Interval
from solar_challenge.web.fleet_components import page_limits
from solar_challenge.web.scenario_import import HeldType, SettingReader, required


class SettingInput(Enum):
    """How a page's form shows and holds a FormSetting."""

    #: One number input, holding the setting's value.
    NUMBER = "number"
    #: A choice of the tariff's clock, held as null, or one [start, end] window of whole
    #: hours, each in its own number input.
    CLOCK_OR_WINDOW = "clock_or_window"


@dataclass(frozen=True)
class FormSetting:
    """A setting of a typed block that a page's form holds for one of its types.

    Attributes:
        key: The setting's key in the block.
        title: Its input's caption.
        within: The values its input offers, either end included; for a CLOCK_OR_WINDOW
            setting, each hour's.
        step: Its input's step; for a CLOCK_OR_WINDOW setting, each hour's.
        start: The value the form starts at; for a CLOCK_OR_WINDOW setting, the one window
            its custom window starts at.
        read: Reads the setting from its value in a scenario and its path there.
        input: How the form shows and holds it.
    """

    key: str
    title: str
    within: Interval
    step: float
    start: Any
    read: SettingReader
    input: SettingInput = SettingInput.NUMBER


@dataclass(frozen=True)
class FormChoice:
    """A type a page's form offers for a typed block, a tariff or a dispatch strategy, with the settings it holds for it.

    Attributes:
        type: The type, as the block's type key names it.
        title: Its option's text.
        settings: The settings of that type the form holds, in the order it shows them.
    """

    type: str
    title: str
    settings: tuple[FormSetting, ...]

    def as_json(self) -> dict[str, Any]:
        """This choice as the page's script reads it, holding only dicts, lists, text and numbers: its type, and each setting's key, input and start, a tuple written as a list."""
        return {
            "type": self.type,
            "settings": [
                {"key": setting.key, "input": setting.input.value, "start": _json_value(setting.start)}
                for setting in self.settings
            ],
        }

    def starting_block(self, type_key: str) -> dict[str, Any]:
        """The block the form posts for this choice at its starts, its type under *type_key*."""
        return {type_key: self.type, **{setting.key: setting.start for setting in self.settings}}

    def held_type(self) -> HeldType:
        """This choice as an import reads a block of its type: its type, and each setting's reader by its key, in its order."""
        return HeldType(self.type, MappingProxyType({setting.key: setting.read for setting in self.settings}))


def _json_value(value: Any) -> Any:
    """*value* with each tuple or list in it, at any depth, written as a list."""
    if isinstance(value, tuple | list):
        return [_json_value(each) for each in value]
    return value


#: The rates, in £/kWh, a form's tariff rate input offers, and its step.
RATE_WITHIN = Interval(0, 2)
RATE_STEP = 0.01


def flat_rate_choice(page: str) -> FormChoice:
    """The flat-rate tariff as the *page*'s form holds it: its rate, which starts at page_limits().flat_rate_start and which the page always sets."""
    rate = FormSetting(
        "rate_per_kwh", "Rate (£/kWh)", RATE_WITHIN, RATE_STEP, page_limits().flat_rate_start, required(page)
    )
    return FormChoice("flat_rate", "Flat Rate", (rate,))
