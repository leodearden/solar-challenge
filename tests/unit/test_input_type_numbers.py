# SPDX-License-Identifier: AGPL-3.0-or-later
"""Invariant 1: every input type refuses a number that is not a finite number by name, and every other numeric dataclass is classified with its reason.

A numeric dataclass is one a module directly under solar_challenge defines at its top level, with a field whose
annotation mentions int or float at any depth. An input type is one whose numbers a user gives: a scenario file, a web
request or a library caller. Constructing one with NaN, ±inf, True or a non-number in any numeric field, or with a
fraction in a whole-number field, raises ConfigurationError naming the field and the value. INPUT_TYPES gives each
input type a factory of a valid instance; NOT_INPUT_TYPES gives every other numeric dataclass the reason it carries no
such contract, and EXCLUDED_FIELDS each numeric field of an input type that is not tried (docs/prds/finite-quantities.md
§5.6 and §7).
"""

import dataclasses
import importlib.util
import math
import re
import sys
import typing
from collections.abc import Callable, Collection, Iterable, Mapping
from datetime import date, time, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.community import CommunityBillingConfig
from solar_challenge.config import ScenarioConfig
from solar_challenge.dispatch import (
    ChargeWindow,
    GridChargeConfig,
    PeakShavingStrategyConfig,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import EVConfig
from solar_challenge.finance import FinanceConfig
from solar_challenge.fleet import default_runner
from solar_challenge.fleet_distribution import (
    ComponentDistribution,
    FleetDistributionConfig,
    NormalDistribution,
    ProportionalDistribution,
    ShuffledPoolDistribution,
    SweepSpec,
    UniformDistribution,
    WeightedDiscreteDistribution,
)
from solar_challenge.flex import FlexibilityValueBand
from solar_challenge.gridservices import EventWindow, FlatGridServices, GridServicesEventsConfig, GridServicesRateBand
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.optimize import ConfigPoint
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffPeriod
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow

from tests._exemption_reasons import Permanent, Transitional
from tests._package_modules import module_level_dataclasses, top_level_modules

_BAD_NUMBERS: tuple[object, ...] = (math.nan, math.inf, -math.inf, True, "x")



def _scenario() -> ScenarioConfig:
    """A one-day scenario of one home, with a SEG rate."""
    june_day = date(2025, 6, 1)
    return ScenarioConfig(
        name="Guard",
        period=SimulationWindow(june_day, june_day, ONE_MINUTE, "Europe/London"),
        home=HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig()),
        seg_tariff_pence_per_kwh=15.0,
    )


#: Each input type's dotted name, to a factory of a valid instance of it that gives every numeric field a value and
#: every tuple field one element.
INPUT_TYPES: Mapping[str, Callable[[], object]] = {
    "solar_challenge.battery.BatteryConfig": lambda: BatteryConfig(capacity_kwh=5.0, soh=0.9),
    "solar_challenge.community.CommunityBillingConfig": lambda: CommunityBillingConfig(seg_rate_pence_per_kwh=15.0),
    "solar_challenge.config.ScenarioConfig": _scenario,
    "solar_challenge.dispatch.GridChargeConfig": lambda: GridChargeConfig(target_soc_fraction=0.8),
    "solar_challenge.dispatch.TOUOptimizedStrategyConfig": lambda: TOUOptimizedStrategyConfig(peak_hours=((16, 19),)),
    "solar_challenge.dispatch.PeakShavingStrategyConfig": lambda: PeakShavingStrategyConfig(import_limit_kw=2.0),
    "solar_challenge.dispatch.ChargeWindow": lambda: ChargeWindow(
        days=frozenset({0}),
        start=time(1),
        duration=timedelta(hours=3),
        target_soc_fraction=0.8,
        allow_discharge=False,
    ),
    "solar_challenge.ev.EVConfig": lambda: EVConfig("7kW"),
    "solar_challenge.finance.FinanceConfig": lambda: FinanceConfig(
        standing_charge_pence_per_day=50.0, self_consumption_override=0.5
    ),
    "solar_challenge.fleet.FleetRunner": lambda: dataclasses.replace(default_runner(), max_workers=2),
    "solar_challenge.fleet_distribution.WeightedDiscreteDistribution": lambda: WeightedDiscreteDistribution(
        values=(4.0,), weights=(1.0,)
    ),
    "solar_challenge.fleet_distribution.NormalDistribution": lambda: NormalDistribution(
        mean=4.0, std=1.0, min=2.0, max=6.0
    ),
    "solar_challenge.fleet_distribution.UniformDistribution": lambda: UniformDistribution(min=1.0, max=2.0),
    "solar_challenge.fleet_distribution.ShuffledPoolDistribution": lambda: ShuffledPoolDistribution(
        values=(4.0,), counts=(2,)
    ),
    "solar_challenge.fleet_distribution.SweepSpec": lambda: SweepSpec(min=1.0, max=2.0, steps=3),
    "solar_challenge.fleet_distribution.ProportionalDistribution": lambda: ProportionalDistribution(
        source="pv.capacity_kw", multiplier=1.5, offset=0.5
    ),
    "solar_challenge.fleet_distribution.FleetDistributionConfig": lambda: FleetDistributionConfig(
        n_homes=2, pv=ComponentDistribution({"capacity_kw": 4.0}), seed=1
    ),
    "solar_challenge.flex.FlexibilityValueBand": lambda: FlexibilityValueBand(
        name="central",
        time_shift_gbp=100.0,
        grid_services_per_home_gbp=4.0,
        grid_services_per_kw_gbp=1.5,
        total_gbp=120.0,
        provenance="guard",
    ),
    "solar_challenge.gridservices.GridServicesRateBand": lambda: GridServicesRateBand(
        1.0, 2.0, flat_gbp_per_kw_per_year=3.0
    ),
    "solar_challenge.gridservices.EventWindow": lambda: EventWindow(
        months=(1,), weekdays=(0,), hours=(17,), events_per_year=12, event_hours=3.0
    ),
    "solar_challenge.gridservices.GridServicesEventsConfig": lambda: GridServicesEventsConfig(
        availability_gbp_per_kw_per_event=1.0, utilisation_gbp_per_mwh=2.0
    ),
    "solar_challenge.gridservices.FlatGridServices": lambda: FlatGridServices(10.0),
    "solar_challenge.heat_pump.HeatPumpConfig": lambda: HeatPumpConfig("ASHP"),
    "solar_challenge.load.LoadConfig": lambda: LoadConfig(
        annual_consumption_kwh=3000.0, household_occupants=3, seed=1
    ),
    "solar_challenge.location.Location": lambda: Location(51.45, -2.58, altitude=10.0),
    "solar_challenge.optimize.ConfigPoint": lambda: ConfigPoint(4.0, 5.0, 3.0),
    "solar_challenge.pv.PVConfig": lambda: PVConfig(
        capacity_kw=4.0, module_efficiency=0.2, temperature_coefficient=-0.004, inverter_capacity_kw=4.0
    ),
    "solar_challenge.seg.SEGTariff": lambda: SEGTariff("Outgoing", 15.0),
    "solar_challenge.tariff.TariffPeriod": lambda: TariffPeriod("00:00", "00:00", 0.25),
}

_COMPUTED_RESULT = Permanent(
    "a computed result: the package builds it from values already read, and a broken invariant of its own raises plain"
    " ValueError (errors.ConfigurationError's docstring; docs/prds/errors-leaf.md, contract C4)"
)
_PRIVATE_VALUE = Permanent(
    "a module-private value its own module builds from numbers an input type has already read or from the module's"
    " own constants; no caller gives its numbers"
)
_LIBRARY_VALUE = Permanent(
    "a library value: its instances are the package's own tables or pvlib's catalogue rows, never numbers a user gives"
)
_GRAMMAR_TABLE = Permanent(
    "a row of the fleet grammar's own tables: int and float appear only in the spec types and builder signatures it"
    " names, not as numbers it holds"
)

#: Each other numeric dataclass's dotted name, to the reason it refuses no bad number by name.
NOT_INPUT_TYPES: Mapping[str, Permanent] = {
    "solar_challenge.battery.SocEnvelope": _COMPUTED_RESULT,
    "solar_challenge.board_report.GridServicesIncome": _COMPUTED_RESULT,
    "solar_challenge.community.CommunityResults": _COMPUTED_RESULT,
    "solar_challenge.dispatch.DispatchDecision": _COMPUTED_RESULT,
    "solar_challenge.dispatch.GridChargeContext": _COMPUTED_RESULT,
    "solar_challenge.dispatch.StepLimits": _COMPUTED_RESULT,
    "solar_challenge.finance.AnnualPhysics": _COMPUTED_RESULT,
    "solar_challenge.finance.BillBreakdown": _COMPUTED_RESULT,
    "solar_challenge.finance.BillDistribution": _COMPUTED_RESULT,
    "solar_challenge.finance.CostRecoverySolution": _COMPUTED_RESULT,
    "solar_challenge.finance.HomeLedger": _COMPUTED_RESULT,
    "solar_challenge.fleet.FleetSummary": _COMPUTED_RESULT,
    "solar_challenge.flow.EnergyFlowResult": _COMPUTED_RESULT,
    "solar_challenge.gridservices.GridServicesAtEvents": _COMPUTED_RESULT,
    "solar_challenge.home.RunPricing": _COMPUTED_RESULT,
    "solar_challenge.home.SummaryStatistics": _COMPUTED_RESULT,
    "solar_challenge.optimize.ConfigResult": _COMPUTED_RESULT,
    "solar_challenge.optimize.RankedSweep": _COMPUTED_RESULT,
    "solar_challenge.optimize.SensitivityAxis": _COMPUTED_RESULT,
    "solar_challenge.optimize.SensitivityPanel": _COMPUTED_RESULT,
    "solar_challenge.output.CommunityMetrics": _COMPUTED_RESULT,
    "solar_challenge.output.SeasonSummary": _COMPUTED_RESULT,
    "solar_challenge.projection.FleetProjection": _COMPUTED_RESULT,
    "solar_challenge.projection.MultiYearCurve": _COMPUTED_RESULT,
    "solar_challenge.projection.ProjectEconomics": _COMPUTED_RESULT,
    "solar_challenge.projection.YearPoint": _COMPUTED_RESULT,
    "solar_challenge.projection._NodeData": _COMPUTED_RESULT,
    "solar_challenge.validation.ValidationResult": _COMPUTED_RESULT,
    "solar_challenge.battery._SocLimitsAndEfficiencies": _PRIVATE_VALUE,
    "solar_challenge.ev._ChargeRows": _PRIVATE_VALUE,
    "solar_challenge.ev._DayOnRows": _PRIVATE_VALUE,
    "solar_challenge.fleet._HomeJob": _PRIVATE_VALUE,
    "solar_challenge.flow._BatteryExchange": _PRIVATE_VALUE,
    "solar_challenge.flow._StepEnergies": _PRIVATE_VALUE,
    "solar_challenge.grid_charge_forecast._CheapWindow": _PRIVATE_VALUE,
    "solar_challenge.grid_charge_forecast._TrailingRule": _PRIVATE_VALUE,
    "solar_challenge.gridservices._EventDayTotals": _PRIVATE_VALUE,
    "solar_challenge.home._DispatchPath": _PRIVATE_VALUE,
    "solar_challenge.output._LoadSeason": _PRIVATE_VALUE,
    "solar_challenge.projection._DrivenMetric": _PRIVATE_VALUE,
    "solar_challenge.projection._NodeSelection": _PRIVATE_VALUE,
    "solar_challenge.pv._Inverter": _PRIVATE_VALUE,
    "solar_challenge.pv._NoctSamInput": _PRIVATE_VALUE,
    "solar_challenge.pv._NoctSamModule": _PRIVATE_VALUE,
    "solar_challenge.pv._StringGroup": _PRIVATE_VALUE,
    "solar_challenge.validation._PvSizeThresholds": _PRIVATE_VALUE,
    "solar_challenge.heat_pump.CopCurve": _LIBRARY_VALUE,
    "solar_challenge.number_fields.Interval": _LIBRARY_VALUE,
    "solar_challenge.pv.CecInverter": _LIBRARY_VALUE,
    "solar_challenge.scenario_knobs.Knob": _LIBRARY_VALUE,
    "solar_challenge.tariff.PresetRates": _LIBRARY_VALUE,
    "solar_challenge.fleet_distribution.DistributionType": _GRAMMAR_TABLE,
    "solar_challenge.fleet_distribution.DrawnKindRule": _GRAMMAR_TABLE,
    "solar_challenge.fleet_distribution.ComponentDistribution": Permanent(
        "a spec container: each draw is a spec type of INPUT_TYPES or a scalar the grammar reads at parse, and each"
        " setting is read by the generated home's own input type (docs/prds/finite-quantities.md §5.3, §5.4)"
    ),
    "solar_challenge.config._Placeholder": Permanent(
        "a ${NAME:default} placeholder, whose default config's placeholder reader reads with"
        " number_fields.as_finite_float before building it"
    ),
    "solar_challenge.config._ScenarioLevelBlocks": Permanent(
        "a private bundle whose seg_tariff_pence_per_kwh is read by the ScenarioConfig built from it"
    ),
}

_OUTCOME_VALUES = Permanent(
    "outcome values, which may be words such as a heat_pump_type, so the generated home's own type reads each"
    " (docs/prds/finite-quantities.md §4 decision 6)"
)
_PVLIB_PARAMETERS = Transitional(
    "S14, the PV-model stream, which owns PVConfig's pvlib parameter mappings (docs/prds/finite-quantities.md §5.4,"
    " §11)"
)

#: Each numeric field of an input type that is not tried, as (dotted name, field), to the reason.
EXCLUDED_FIELDS: Mapping[tuple[str, str], Permanent | Transitional] = {
    ("solar_challenge.fleet_distribution.WeightedDiscreteDistribution", "values"): _OUTCOME_VALUES,
    ("solar_challenge.fleet_distribution.ShuffledPoolDistribution", "values"): _OUTCOME_VALUES,
    ("solar_challenge.pv.PVConfig", "custom_module_params"): _PVLIB_PARAMETERS,
    ("solar_challenge.pv.PVConfig", "custom_inverter_params"): _PVLIB_PARAMETERS,
}

_NUMBER_TYPES_BY_NAME: Mapping[str, type] = {"int": int, "float": float}

_NUMBER_TYPE_NAME = re.compile(r"\b(int|float)\b")


def number_types(annotation: object) -> frozenset[type]:
    """Return int and float, each if *annotation* mentions it at any depth: in its text, its arguments or a Callable's parameter list, but not in a Literal's values; bool is not int here."""
    if isinstance(annotation, type) and annotation in _NUMBER_TYPES_BY_NAME.values():
        return frozenset({annotation})
    if isinstance(annotation, typing.ForwardRef):
        return number_types(annotation.__forward_arg__)
    if isinstance(annotation, str):
        return frozenset(_NUMBER_TYPES_BY_NAME[name] for name in _NUMBER_TYPE_NAME.findall(annotation))
    if typing.get_origin(annotation) is typing.Literal:
        return frozenset()
    items = annotation if isinstance(annotation, list) else typing.get_args(annotation)
    return frozenset().union(*(number_types(item) for item in items))


def numeric_fields(cls: type) -> dict[str, frozenset[type]]:
    """Return the number types each numeric field of the dataclass *cls* mentions, in field order.

    Its hints are resolved where they can be, and read as each field's annotation text where a name imported under
    TYPE_CHECKING leaves them unresolvable.
    """
    fields = dataclasses.fields(cls)
    try:
        hints = typing.get_type_hints(cls)
    except NameError:
        hints = {field.name: field.type for field in fields}
    types_by_field = {field.name: number_types(hints[field.name]) for field in fields}
    return {name: types for name, types in types_by_field.items() if types}


def numeric_dataclasses(modules: Iterable[ModuleType]) -> dict[str, type]:
    """Return each dataclass the *modules* define at their top level with a numeric field, keyed by its dotted name."""
    return {
        f"{cls.__module__}.{cls.__qualname__}": cls
        for module in modules
        for cls in module_level_dataclasses(module)
        if numeric_fields(cls)
    }


def unclassified(discovered: Iterable[str]) -> list[str]:
    """Return a message for each of the *discovered* dotted names in neither INPUT_TYPES nor NOT_INPUT_TYPES, sorted."""
    tried_with = ", ".join(repr(bad) for bad in _BAD_NUMBERS)
    return [
        f"{name} has a numeric field but is in neither INPUT_TYPES nor NOT_INPUT_TYPES: classify it, in INPUT_TYPES"
        " with a factory of a valid instance if a user gives its numbers (a scenario file, a web request or a library"
        f" caller), so each numeric field is tried with {tried_with}, or in NOT_INPUT_TYPES with the reason it carries"
        " no such contract"
        for name in sorted(discovered)
        if name not in INPUT_TYPES and name not in NOT_INPUT_TYPES
    ]


def stale(discovered: Collection[str]) -> list[str]:
    """Return a message for each INPUT_TYPES or NOT_INPUT_TYPES entry whose dotted name is not among the *discovered*, sorted."""
    tables: Mapping[str, Collection[str]] = {"INPUT_TYPES": INPUT_TYPES, "NOT_INPUT_TYPES": NOT_INPUT_TYPES}
    return sorted(
        f"{table} entry {name} names no numeric dataclass a module directly under solar_challenge defines: remove or"
        " rename the stale entry"
        for table, names in tables.items()
        for name in names
        if name not in discovered
    )


_SEEDED_MODULE_NAME = "seeded_numeric_dataclasses"

_SEEDED_SOURCE = '''
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from decimal import Decimal


@dataclass(frozen=True)
class SeededRate:
    rate: Optional[float]
    counts: tuple[int, ...]
    share: int | float
    label: str
    flag: bool
    other: Decimal | None = None


@dataclass
class SeededLabel:
    label: str
    flag: bool


class NotADataclass:
    rate: float
'''


@pytest.fixture
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """A module defining one numeric dataclass, whose hints a TYPE_CHECKING import leaves unresolvable, beside a dataclass with no numeric field and a plain class with one."""
    path = tmp_path / f"{_SEEDED_MODULE_NAME}.py"
    path.write_text(_SEEDED_SOURCE, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(_SEEDED_MODULE_NAME, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, _SEEDED_MODULE_NAME, module)
    spec.loader.exec_module(module)
    return module


def test_discovery_finds_a_dataclass_with_a_numeric_field_in_any_annotation_even_when_its_hints_cannot_be_resolved(
    seeded: ModuleType,
) -> None:
    seeded_rate = seeded.SeededRate

    assert numeric_dataclasses([seeded]) == {f"{seeded.__name__}.SeededRate": seeded_rate}
    assert numeric_fields(seeded_rate) == {
        "rate": frozenset({float}),
        "counts": frozenset({int}),
        "share": frozenset({int, float}),
    }


def test_top_level_modules_are_the_modules_directly_under_the_package() -> None:
    names = {module.__name__ for module in top_level_modules()}

    assert {"solar_challenge.pv", "solar_challenge.number_fields"} <= names
    assert [name for name in names if name.split(".")[1] in {"web", "cli"}] == []


def test_an_unclassified_numeric_dataclass_is_reported_by_name_with_the_classification_instruction(
    seeded: ModuleType,
) -> None:
    messages = unclassified(numeric_dataclasses([seeded]))

    assert len(messages) == 1, messages
    for part in (f"{seeded.__name__}.SeededRate", "INPUT_TYPES", "NOT_INPUT_TYPES", "classify it"):
        assert part in messages[0], messages[0]


@pytest.fixture(scope="module")
def discovered() -> dict[str, type]:
    """The numeric dataclasses of the modules directly under solar_challenge, keyed by dotted name."""
    return numeric_dataclasses(top_level_modules())


def test_every_numeric_dataclass_under_solar_challenge_is_classified(discovered: dict[str, type]) -> None:
    messages = unclassified(discovered)

    assert messages == [], "\n".join(messages)


def test_no_classified_class_is_stale(discovered: dict[str, type]) -> None:
    messages = stale(discovered)

    assert messages == [], "\n".join(messages)


def test_a_classified_class_no_longer_discovered_is_reported_as_stale(discovered: dict[str, type]) -> None:
    messages = stale(discovered.keys() - {"solar_challenge.seg.SEGTariff"})

    assert len(messages) == 1, messages
    for part in ("solar_challenge.seg.SEGTariff", "INPUT_TYPES", "remove or rename the stale entry"):
        assert part in messages[0], messages[0]


def test_no_class_is_both_an_input_type_and_not_one() -> None:
    assert INPUT_TYPES.keys() & NOT_INPUT_TYPES.keys() == set()


def test_every_excluded_field_is_a_numeric_field_of_an_input_type(discovered: dict[str, type]) -> None:
    for name, field in EXCLUDED_FIELDS:
        assert name in INPUT_TYPES, f"EXCLUDED_FIELDS' entry ({name!r}, {field!r}) names no class of INPUT_TYPES"
        assert field in numeric_fields(discovered[name]), (
            f"EXCLUDED_FIELDS' entry ({name!r}, {field!r}) names no numeric field of {name}"
        )


@pytest.mark.parametrize("name", sorted(INPUT_TYPES))
def test_each_input_type_factory_builds_a_valid_instance_of_its_class(name: str, discovered: dict[str, type]) -> None:
    instance = INPUT_TYPES[name]()

    assert type(instance) is discovered[name]


@pytest.mark.parametrize(
    ("value", "bad", "expected"),
    [
        (4.0, math.nan, math.nan),
        ((1,), True, (True,)),
        (((16, 19),), 2.5, ((2.5, 19),)),
        (frozenset({0}), "x", frozenset({"x"})),
    ],
    ids=["scalar", "tuple", "pairs", "frozenset"],
)
def test_a_bad_number_takes_the_place_of_the_first_number_of_a_field_s_value(
    value: object, bad: object, expected: object
) -> None:
    assert repr(with_bad_number(value, bad)) == repr(expected)


@pytest.mark.parametrize(("name", "field", "bad"), refusal_cases())
def test_each_input_type_refuses_each_bad_number_in_each_numeric_field_by_name(
    name: str, field: str, bad: object
) -> None:
    valid = INPUT_TYPES[name]()
    value = getattr(valid, field)
    assert value is not None, f"INPUT_TYPES' factory for {name} leaves {field} None, so its read is not tried: give it a value"

    with pytest.raises(ConfigurationError) as refusal:
        dataclasses.replace(valid, **{field: with_bad_number(value, bad)})

    message = str(refusal.value)
    assert field in message and repr(bad) in message, message


@pytest.mark.parametrize(
    ("construct", "field", "bad"),
    [
        (lambda: SEGTariff("x", math.nan), "rate_pence_per_kwh", math.nan),
        (lambda: HeatPumpConfig("ASHP", math.nan, 8000.0), "thermal_capacity_kw", math.nan),
        (lambda: EVConfig("7kW", True), "arrival_hour", True),
    ],
    ids=["SEGTariff", "HeatPumpConfig", "EVConfig"],
)
def test_the_named_library_constructions_are_refused_by_name(
    construct: Callable[[], object], field: str, bad: object
) -> None:
    with pytest.raises(ConfigurationError) as refusal:
        construct()

    message = str(refusal.value)
    assert field in message and repr(bad) in message, message
