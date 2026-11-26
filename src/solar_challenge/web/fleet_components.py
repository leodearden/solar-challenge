# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the dashboard's forms accept and start at: a fleet's size and seed, a simulation window's days, and the fleet components PV, battery and load.

page_limits() is the one PageLimits value every dashboard form's bounds and starting
values render from. A context processor gives every template it as page_limits, and
base.html writes its as_json() once into each page as the #page-limits element, a
<script type="application/json">, which the pages' scripts read.

Each fleet component's value_range bounds every home's value, fixed or drawn.
simulation_params.parse_home_config reads a home's value within it, and the fleet page
and the scenario builder refuse a fleet whose generated homes hold a value outside it
with refuse_homes_outside_ranges.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import MappingProxyType
from typing import Any

from solar_challenge.errors import ConfigurationError
from solar_challenge.home import HomeConfig
from solar_challenge.number_fields import Interval, as_whole_number
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY, SHORT_WINDOW_START, covered_days


def _require(admitted: bool, field_name: str, requirement: str, value: object) -> None:
    """Refuse *value*, given for *field_name*, unless it is *admitted*: "<field_name> must <requirement>, got <value!r>"."""
    if not admitted:
        raise ValueError(f"{field_name} must {requirement}, got {value!r}")


#: The most homes a dashboard fleet holds. The fleet forms refuse a larger fleet, and the
#: preview a shuffled pool that holds values for more homes or a draw of more values.
MAX_FLEET_HOMES = 10_000
#: The numbers of homes a dashboard fleet holds.
FLEET_SIZE = Interval(1, MAX_FLEET_HOMES)
#: The number of homes a fleet form starts at.
FLEET_SIZE_DEFAULT = 100

#: The largest seed, positive or negative, a dashboard fleet holds: Number.MAX_SAFE_INTEGER,
#: past which the JavaScript number the fleet page holds its seed in rounds some whole numbers.
MAX_FLEET_SEED = 2**53 - 1
#: The seeds a dashboard fleet holds.
FLEET_SEED = Interval(-MAX_FLEET_SEED, MAX_FLEET_SEED)
#: The seed a fleet form starts at.
SEED_DEFAULT = 42


def read_fleet_size(value: Any, field: str) -> int:
    """Read *value*, the setting named *field*, as a dashboard fleet's number of homes, a whole number from 1 to :data:`MAX_FLEET_HOMES`.

    Raises:
        ConfigurationError: From :func:`~solar_challenge.number_fields.as_whole_number`,
            naming *field* and the value sent.
    """
    return as_whole_number(value, field, within=FLEET_SIZE)


def read_fleet_seed(value: Any, field: str) -> int:
    """Read *value*, the setting named *field*, as a dashboard fleet's seed, a whole number from -:data:`MAX_FLEET_SEED` to :data:`MAX_FLEET_SEED`.

    Raises:
        ConfigurationError: From :func:`~solar_challenge.number_fields.as_whole_number`,
            naming *field* and the value sent.
    """
    return as_whole_number(value, field, within=FLEET_SEED)


#: The days value that runs DEFAULT_FIRST_DAY to DEFAULT_LAST_DAY, all MAX_WINDOW_DAYS days of
#: the year, rather than that many days from SHORT_WINDOW_START.
FULL_YEAR_DAYS_SENTINEL: int = 365

#: The most days a simulation window may span: the full year, DEFAULT_FIRST_DAY to
#: DEFAULT_LAST_DAY, that days=FULL_YEAR_DAYS_SENTINEL and a request without dates run;
#: rationale in docs/web-ui-design.md (Simulation window).
MAX_WINDOW_DAYS: int = covered_days(DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY)
#: The most days a body may send: FULL_YEAR_DAYS_SENTINEL, so the full year is the one
#: year-long window days runs; rationale in docs/web-ui-design.md (Simulation window).
MAX_DAYS: int = FULL_YEAR_DAYS_SENTINEL
#: The days values a body may send.
WINDOW_DAYS = Interval(1, MAX_DAYS)
#: The days the home and fleet forms offer, the full year last.
DAY_CHOICES: tuple[int, ...] = (7, 14, 30, 90, FULL_YEAR_DAYS_SENTINEL)
#: The days the home and fleet forms start at.
DEFAULT_DAYS = 30


def days_window(days: int) -> tuple[date, date]:
    """The window a ``days`` request runs: DEFAULT_FIRST_DAY to DEFAULT_LAST_DAY for FULL_YEAR_DAYS_SENTINEL, else *days* days from SHORT_WINDOW_START."""
    if days == FULL_YEAR_DAYS_SENTINEL:
        return DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY
    return SHORT_WINDOW_START, SHORT_WINDOW_START + timedelta(days=days - 1)


@dataclass(frozen=True)
class EditorDistribution:
    """A distribution as the distribution editor holds it at Fixed Value: the fixed value, and the parameters and rows each other type starts at.

    Attributes:
        values: Weighted Discrete's (value, weight) rows.
        entries: Shuffled Pool's (value, count) rows.
    """

    fixed: float
    mean: float
    std: float
    min: float
    max: float
    values: tuple[tuple[float, float], ...]
    entries: tuple[tuple[float, int], ...]

    def editor_state(self) -> dict[str, Any]:
        """The distribution editor's dist object holding this distribution, which type '' shows at Fixed Value."""
        return {
            "type": "",
            "fixed": self.fixed,
            "mean": self.mean,
            "std": self.std,
            "min": self.min,
            "max": self.max,
            "values": [{"value": value, "weight": weight} for value, weight in self.values],
            "entries": [{"value": value, "count": count} for value, count in self.entries],
        }


@dataclass(frozen=True)
class ComponentLimits:
    """A fleet component: the names the form and the scenario grammar give it, the range of a home's value, and what its distribution editor shows and starts at.

    Attributes:
        key: Its fleet_distribution block, and the prefix of the builder form's fields for it.
        grammar_key: Its spec's key in that block.
        fixed_field: The builder form field carrying a fixed value.
        subject: What its values measure, e.g. 'PV Capacity': the fleet page's card heading,
            and the words that start each accessible name in that card's distribution editor.
        unit: The unit of its values, e.g. 'kW', which heading appends to subject in parentheses.
        step: The step of every value input but a weight or count.
        value_range: The range of the value every home holds, fixed or drawn, either end
            included.
        new_row_value: The value an added row starts at.
        start: The distribution its card starts at.
        value_of: The value a home holds for it, None when the home has no such component
            or leaves the value unset.

    Raises:
        ValueError: for a start whose fixed value lies outside value_range.
    """

    key: str
    grammar_key: str
    fixed_field: str
    subject: str
    unit: str
    step: float
    value_range: Interval
    new_row_value: float
    start: EditorDistribution
    value_of: Callable[[HomeConfig], float | None] = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        _require(
            self.value_range.admits(self.start.fixed),
            f"start.fixed of fleet component {self.key!r}",
            f"lie within its value_range, {self.value_range}",
            self.start.fixed,
        )

    @property
    def heading(self) -> str:
        """Its subject and unit, e.g. 'PV Capacity (kW)'."""
        return f"{self.subject} ({self.unit})"

    def as_json(self) -> dict[str, Any]:
        """This component as #page-limits writes it: its names, step, value_range as its bounds, new_row_value and start as the editor holds it."""
        return {
            "key": self.key,
            "grammar_key": self.grammar_key,
            "subject": self.subject,
            "unit": self.unit,
            "step": self.step,
            "value_range": _interval_json(self.value_range),
            "new_row_value": self.new_row_value,
            "start": self.start.editor_state(),
        }


FLEET_COMPONENTS: Mapping[str, ComponentLimits] = MappingProxyType({
    component.key: component
    for component in (
        ComponentLimits(
            key="pv",
            grammar_key="capacity_kw",
            fixed_field="pv_capacity_kw",
            subject="PV Capacity",
            unit="kW",
            step=0.1,
            value_range=Interval(0.5, 20),
            new_row_value=4.0,
            start=EditorDistribution(
                fixed=4.0,
                mean=4.0,
                std=1.0,
                min=2.0,
                max=8.0,
                values=((3.0, 20), (4.0, 40), (5.0, 30)),
                entries=((3.0, 20), (4.0, 40), (5.0, 30), (6.0, 10)),
            ),
            value_of=lambda home: home.pv_config.capacity_kw,
        ),
        ComponentLimits(
            key="battery",
            grammar_key="capacity_kwh",
            fixed_field="battery_capacity_kwh",
            subject="Battery Capacity",
            unit="kWh",
            step=0.1,
            value_range=Interval(0, 100),
            new_row_value=5.0,
            start=EditorDistribution(
                fixed=5.0,
                mean=5.0,
                std=2.0,
                min=0,
                max=13.5,
                values=((0, 40), (5.0, 40), (10.0, 20)),
                entries=((0, 40), (5.0, 40), (10.0, 20)),
            ),
            value_of=lambda home: None if home.battery_config is None else home.battery_config.capacity_kwh,
        ),
        ComponentLimits(
            key="load",
            grammar_key="annual_consumption_kwh",
            fixed_field="annual_consumption_kwh",
            subject="Annual Consumption",
            unit="kWh",
            step=100,
            value_range=Interval(500, 20000),
            new_row_value=3500,
            start=EditorDistribution(
                fixed=3500,
                mean=3400,
                std=800,
                min=2000,
                max=5000,
                values=((2900, 30), (3500, 40), (4500, 30)),
                entries=((2900, 30), (3500, 40), (4500, 30)),
            ),
            value_of=lambda home: home.load_config.annual_consumption_kwh,
        ),
    )
})


@dataclass(frozen=True)
class PageLimits:
    """What the dashboard's forms accept and start at, as every form's bounds and starting values render it.

    Attributes:
        fleet_size: The numbers of homes a fleet holds.
        fleet_size_default: The number of homes a fleet form starts at.
        fleet_size_slider: The fleet page's size slider's (min, max, step): a convenience
            for choosing a size, not its bound, which fleet_size is.
        seed: The seeds a fleet holds.
        seed_default: The seed a fleet form starts at.
        window_days: The days values a request may send.
        full_year_days: The days value that runs default_window, the full year.
        default_window: The window a request without days or dates runs.
        short_window_start: The first day of a window of fewer days than the full year.
        day_choices: The days the home and fleet forms offer, the full year last.
        default_days: The day choice the home and fleet forms start at.
        custom_range_default: The window the home and fleet forms' custom range starts at:
            the window default_days runs.
        period_presets: The builder's period buttons, each title with the window it sets,
            in button order.
        components: The fleet components, in FLEET_COMPONENTS order.

    Raises:
        ValueError: For a fleet_size_default outside fleet_size, a seed_default outside seed,
            a fleet_size_slider that starts or ends outside fleet_size, a day choice outside
            window_days, or a default_days that is not one of day_choices, naming the field
            and the value.
    """

    fleet_size: Interval
    fleet_size_default: int
    fleet_size_slider: tuple[int, int, int]
    seed: Interval
    seed_default: int
    window_days: Interval
    full_year_days: int
    default_window: tuple[date, date]
    short_window_start: date
    day_choices: tuple[int, ...]
    default_days: int
    custom_range_default: tuple[date, date]
    period_presets: Mapping[str, tuple[date, date]]
    components: Mapping[str, ComponentLimits]

    def __post_init__(self) -> None:
        slider_low, slider_high, _slider_step = self.fleet_size_slider
        _require(
            self.fleet_size.admits(self.fleet_size_default),
            "fleet_size_default",
            f"be {self.fleet_size}",
            self.fleet_size_default,
        )
        _require(self.seed.admits(self.seed_default), "seed_default", f"be {self.seed}", self.seed_default)
        _require(
            self.fleet_size.admits(slider_low) and self.fleet_size.admits(slider_high),
            "fleet_size_slider",
            f"start and end within fleet_size, {self.fleet_size}",
            self.fleet_size_slider,
        )
        _require(
            all(self.window_days.admits(days) for days in self.day_choices),
            "day_choices",
            f"each be {self.window_days}",
            self.day_choices,
        )
        _require(
            self.default_days in self.day_choices,
            "default_days",
            f"be one of day_choices {self.day_choices}",
            self.default_days,
        )

    def as_json(self) -> dict[str, Any]:
        """This value as #page-limits writes it, holding only dicts, lists, text and numbers: each date as ISO 8601 text, each Interval as its low and high, and each tuple as a list.

        period_presets, as each title with its window, and components, as each one's as_json(),
        are lists in their order: tojson writes an object's keys sorted, so an object would
        not keep it.
        """
        return {
            "fleet_size": _interval_json(self.fleet_size),
            "fleet_size_default": self.fleet_size_default,
            "fleet_size_slider": list(self.fleet_size_slider),
            "seed": _interval_json(self.seed),
            "seed_default": self.seed_default,
            "window_days": _interval_json(self.window_days),
            "full_year_days": self.full_year_days,
            "default_window": _window_json(self.default_window),
            "short_window_start": self.short_window_start.isoformat(),
            "day_choices": list(self.day_choices),
            "default_days": self.default_days,
            "custom_range_default": _window_json(self.custom_range_default),
            "period_presets": [
                {"title": title, "window": _window_json(window)} for title, window in self.period_presets.items()
            ],
            "components": [component.as_json() for component in self.components.values()],
        }


_YEAR = DEFAULT_FIRST_DAY.year

_PAGE_LIMITS = PageLimits(
    fleet_size=FLEET_SIZE,
    fleet_size_default=FLEET_SIZE_DEFAULT,
    fleet_size_slider=(10, 500, 10),
    seed=FLEET_SEED,
    seed_default=SEED_DEFAULT,
    window_days=WINDOW_DAYS,
    full_year_days=FULL_YEAR_DAYS_SENTINEL,
    default_window=(DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY),
    short_window_start=SHORT_WINDOW_START,
    day_choices=DAY_CHOICES,
    default_days=DEFAULT_DAYS,
    custom_range_default=days_window(DEFAULT_DAYS),
    period_presets=MappingProxyType({
        "Full Year": (DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY),
        "Summer": (date(_YEAR, 6, 1), date(_YEAR, 8, 31)),
        "Winter": (date(_YEAR, 12, 1), date(_YEAR + 1, 2, 28)),
        "1 Month": days_window(30),
        "1 Week": days_window(7),
    }),
    components=FLEET_COMPONENTS,
)


def page_limits() -> PageLimits:
    """The one PageLimits value: what every dashboard form accepts and starts at."""
    return _PAGE_LIMITS


def refuse_homes_outside_ranges(homes: Sequence[HomeConfig]) -> None:
    """Refuse *homes*, a fleet's homes in order, when one holds a PV, battery or load value outside its component's value_range.

    A home without a battery, or whose load is not scaled to an annual consumption, holds
    no value for that component, so none is checked.

    Raises:
        ConfigurationError: For the first value outside its range, taking the homes in
            order and each home's components in FLEET_COMPONENTS order, naming the
            component's path in the fleet form (e.g. pv.capacity_kw), the range, the value
            and the home's number, counted from 1.
    """
    for number, home in enumerate(homes, start=1):
        for component in FLEET_COMPONENTS.values():
            value = component.value_of(home)
            if value is not None and not component.value_range.admits(value):
                raise ConfigurationError(
                    f"{component.key}.{component.grammar_key} must be {component.value_range} "
                    f"for every home, got {value!r} for home {number}"
                )


def _interval_json(interval: Interval) -> dict[str, float]:
    """*interval* as #page-limits writes it: its low and high bounds."""
    return {"low": interval.low, "high": interval.high}


def _window_json(window: tuple[date, date]) -> list[str]:
    """*window*, a (first, last) pair of days, as #page-limits writes it: each day as ISO 8601 text."""
    return [day.isoformat() for day in window]
