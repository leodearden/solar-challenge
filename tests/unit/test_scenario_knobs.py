# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests of scenario_knobs: each knob's one ScenarioConfig edit, and the names and aliases that resolve to it; no sweep runs."""
from __future__ import annotations

import copy
import dataclasses
import re
from collections.abc import Callable, Iterator

import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import ScenarioConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import EVConfig
from solar_challenge.finance import FinanceConfig
from solar_challenge.gridservices import FlatGridServices, GridServicesEventsConfig, NoGridServices
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.scenario_knobs import (
    ALIASES,
    FLAT_PRICING_REMEDY,
    KNOBS,
    Knob,
    flat_rate_pricing,
    is_knob_name,
    knob_listing,
    knob_named,
    names_with_aliases,
)
from solar_challenge.seg import SEGTariff, resolve_seg_tariff
from tests._finance_builders import make_home_config, make_period, make_scenario_and_finance
from tests._modules_loaded_by_importing import (
    package_modules_loaded_by_importing,
    web_modules_loaded_by_importing,
)


def _default_fleet(n_homes: int = 2) -> ScenarioConfig:
    """A fleet of *n_homes* default homes carrying make_scenario_and_finance's finance block, with no scenario SEG rate."""
    scenario, finance = make_scenario_and_finance(n_homes=n_homes)
    return dataclasses.replace(scenario, finance=finance)


def _fleet_carrying(tariffs: list[SEGTariff | None]) -> ScenarioConfig:
    """_default_fleet's fleet, its homes carrying *tariffs* in order."""
    scenario = _default_fleet(n_homes=len(tariffs))
    return dataclasses.replace(
        scenario,
        homes=tuple(
            dataclasses.replace(home, seg_tariff=tariff)
            for home, tariff in zip(scenario.homes, tariffs, strict=True)
        ),
    )


def _fleet() -> ScenarioConfig:
    """A three-home fleet whose homes differ in the settings a knob must leave alone.

    homes[0] has a heat pump and a battery whose power and SOC settings are not
    BatteryConfig's defaults; homes[1] has an EV and no battery; homes[2] carries
    its own SEG tariff, Octopus at 4.1 p/kWh.  The scenario sets no SEG rate.
    """
    scenario = _default_fleet(n_homes=3)
    first, second, third = scenario.homes
    return dataclasses.replace(
        scenario,
        homes=(
            dataclasses.replace(
                first,
                heat_pump_config=HeatPumpConfig("ASHP"),
                battery_config=BatteryConfig(
                    capacity_kwh=5.0, max_charge_kw=3.3, max_discharge_kw=3.3, min_soc_fraction=0.2
                ),
            ),
            dataclasses.replace(second, ev_config=EVConfig("7kW", arrival_hour=18)),
            dataclasses.replace(third, seg_tariff=resolve_seg_tariff("Octopus")),
        ),
    )


def _single_home() -> ScenarioConfig:
    """A single-home scenario of the default home, carrying the fleets' finance block."""
    _, finance = make_scenario_and_finance()
    return ScenarioConfig(name="single-home", period=make_period(), home=make_home_config(), finance=finance)


def _leaves(value: object, path: str = "") -> Iterator[tuple[str, object]]:
    """Each leaf of *value* with its dotted path: a dataclass's fields and a tuple's items are followed, anything else is a leaf."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            yield from _leaves(getattr(value, field.name), f"{path}.{field.name}" if path else field.name)
    elif isinstance(value, tuple):
        for index, item in enumerate(value):
            yield from _leaves(item, f"{path}[{index}]")
    else:
        yield path, value


def _changed_paths(before: object, after: object) -> set[str]:
    """The paths of the leaves that differ between *before* and *after*, or that only one of them has."""
    old = dict(_leaves(before))
    new = dict(_leaves(after))
    return {path for path in old.keys() | new.keys() if path not in old or path not in new or old[path] != new[path]}


_HOME_TARGETS = {
    "pv_capacity_kw": "pv_config.capacity_kw",
    "inverter_capacity_kw": "pv_config.inverter_capacity_kw",
    "battery_capacity_kwh": "battery_config",
    "annual_consumption_kwh": "load_config.annual_consumption_kwh",
    "degradation_rate_per_year": "pv_config.degradation_rate_per_year",
}
_SCENARIO_TARGETS = {"seg_tariff_pence_per_kwh": "seg_tariff_pence_per_kwh"}
_PRICING_TARGETS = {"grid_services_income_per_kw_per_year_gbp": "finance.grid_services_model"}
_FINANCE_FIELD_NAMES = frozenset(field.name for field in dataclasses.fields(FinanceConfig))


def _target(knob: Knob) -> re.Pattern[str]:
    """The paths, of a scenario's leaves, that *knob* may change."""
    if knob.name in _HOME_TARGETS:
        return re.compile(rf"(home|homes\[\d+\])\.{re.escape(_HOME_TARGETS[knob.name])}([.\[].*)?")
    if knob.name in _SCENARIO_TARGETS:
        return re.compile(re.escape(_SCENARIO_TARGETS[knob.name]))
    if knob.name in _PRICING_TARGETS:
        return re.compile(rf"{re.escape(_PRICING_TARGETS[knob.name])}(\..*)?")
    if knob.name in _FINANCE_FIELD_NAMES:
        return re.compile(rf"finance\.{re.escape(knob.name)}")
    pytest.fail(f"knob {knob.name!r} has no target in this test's table")


def _value_for(knob: Knob) -> float:
    """A value every scenario form accepts for *knob*: 4.1 p/kWh, homes[2]'s own rate, for the SEG knob, else 0.5."""
    return 4.1 if knob.name == "seg_tariff_pence_per_kwh" else 0.5


_FORMS: tuple[Callable[[], ScenarioConfig], ...] = (_fleet, _single_home)


class TestEachKnobIsOnePureFormPreservingEdit:
    """Every knob's apply returns a new scenario of the form it was given, changing only the knob's target."""

    @pytest.mark.parametrize("form", _FORMS, ids=["fleet", "single-home"])
    @pytest.mark.parametrize("knob", tuple(KNOBS.values()), ids=lambda knob: knob.name)
    def test_apply_changes_only_its_target_and_keeps_the_form(
        self, knob: Knob, form: Callable[[], ScenarioConfig]
    ) -> None:
        """The argument is unchanged, the form and home count are kept, the leaves changed are the target's, and a second apply changes nothing."""
        scenario = form()
        before = copy.deepcopy(scenario)
        value = _value_for(knob)

        result = knob.apply(scenario, value)

        assert scenario == before
        assert (result.home is None) == (scenario.home is None)
        assert len(result.homes) == len(scenario.homes)
        changed = _changed_paths(scenario, result)
        target = _target(knob)
        assert changed, f"{knob.name} at {value} changed nothing"
        assert {path for path in changed if not target.fullmatch(path)} == set()
        assert knob.apply(result, value) == result

    def test_the_seg_knob_refuses_a_rate_a_home_carries_another_of(self) -> None:
        """A home whose own tariff sets another rate is refused, naming it and both rates, not overwritten."""
        with pytest.raises(ConfigurationError, match=r"homes\[2\].*4\.1.*6\.0"):
            KNOBS["seg_tariff_pence_per_kwh"].apply(_fleet(), 6.0)

    @pytest.mark.parametrize("form", _FORMS, ids=["fleet", "single-home"])
    @pytest.mark.parametrize("knob", tuple(KNOBS.values()), ids=lambda knob: knob.name)
    def test_apply_keeps_the_window_and_the_location(self, knob: Knob, form: Callable[[], ScenarioConfig]) -> None:
        """No knob moves a scenario's window or location, so every point of a `fleet sweep` of a knob simulates over the window of its first point."""
        scenario = form()

        applied = knob.apply(scenario, _value_for(knob))

        assert applied.window() == scenario.window()
        assert applied.get_location() == scenario.get_location()


class TestTheBatteryKnob:
    """battery_capacity_kwh: 0 removes every battery, a capacity resizes a battery or gives a home without one a default one."""

    def test_zero_leaves_no_home_a_battery(self) -> None:
        """At 0 every stored home's battery is None, the one homes[0] had included."""
        swept = KNOBS["battery_capacity_kwh"].apply(_fleet(), 0.0)

        assert [home.battery_config for home in swept.homes] == [None, None, None]

    def test_a_capacity_resizes_a_battery_keeping_its_settings_and_gives_a_home_without_one_a_default_battery(
        self,
    ) -> None:
        """homes[0]'s battery keeps its power, SOC and dispatch at the new capacity; homes[1] gains BatteryConfig's defaults."""
        fleet = _fleet()
        original = fleet.homes[0].battery_config
        assert original is not None

        swept = KNOBS["battery_capacity_kwh"].apply(fleet, 7.5)

        assert swept.homes[0].battery_config == dataclasses.replace(original, capacity_kwh=7.5)
        assert swept.homes[1].battery_config == BatteryConfig(capacity_kwh=7.5)

    def test_a_negative_capacity_is_refused_naming_the_knob(self) -> None:
        """A capacity CAPACITY_SETTING_KWH refuses raises ConfigurationError naming battery_capacity_kwh."""
        with pytest.raises(ConfigurationError, match="battery_capacity_kwh"):
            KNOBS["battery_capacity_kwh"].apply(_fleet(), -1.0)


_ALIAS_FIELDS = {
    "retained_floor": "retained_cash_floor_per_home_per_year_gbp",
    "battery_cost": "battery_cost_per_kwh_gbp",
    "pv_cost": "pv_cost_per_kwp_gbp",
    "inverter_cost": "inverter_cost_per_kw_gbp",
    "grid_services": "grid_services_income_per_kw_per_year_gbp",
    "seg": "seg_tariff_pence_per_kwh",
    "degradation": "degradation_rate_per_year",
}

_REAL_NUMBER_FINANCE_FIELDS = {
    "standing_charge_pence_per_day",
    "vat_rate",
    "retail_baseline_rate_pence_per_kwh",
    "self_consumption_override",
    "pv_cost_per_kwp_gbp",
    "roof_fit_cost_gbp",
    "battery_cost_per_kwh_gbp",
    "inverter_cost_per_kw_gbp",
    "grant_gbp",
    "equity_fraction",
    "loan_rate",
    "opex_per_home_per_year_gbp",
    "own_use_rate_pence_per_kwh",
    "retained_cash_floor_per_home_per_year_gbp",
}


class TestNames:
    """KNOBS holds each knob under its canonical name, ALIASES each alias's canonical name, and knob_named resolves either."""

    def test_an_alias_and_its_canonical_name_name_one_knob(self) -> None:
        """retained_floor and its canonical name resolve to the registry's one knob."""
        assert (
            knob_named("retained_floor")
            is knob_named("retained_cash_floor_per_home_per_year_gbp")
            is KNOBS["retained_cash_floor_per_home_per_year_gbp"]
        )

    @pytest.mark.parametrize(("alias", "field"), tuple(_ALIAS_FIELDS.items()))
    def test_each_alias_resolves_to_its_fields_knob(self, alias: str, field: str) -> None:
        """Each alias, the CLI's five, seg and degradation, names the knob of its field."""
        assert knob_named(alias) is KNOBS[field]

    def test_the_aliases_are_exactly_the_cli_sensitivity_aliases_seg_and_degradation(self) -> None:
        """ALIASES maps exactly the documented aliases to their fields."""
        assert dict(ALIASES) == _ALIAS_FIELDS

    def test_every_alias_names_a_knob_and_none_is_a_canonical_name(self) -> None:
        """Each ALIASES value is a KNOBS key, and no ALIASES key is one."""
        assert set(ALIASES.values()) <= set(KNOBS)
        assert set(ALIASES) & set(KNOBS) == set()

    @pytest.mark.parametrize("name", tuple(KNOBS), ids=str)
    def test_each_knob_is_held_under_its_name_and_resolves_to_itself(self, name: str) -> None:
        """KNOBS' key is its knob's name, and knob_named of a canonical name is that knob."""
        assert KNOBS[name].name == name
        assert knob_named(name) is KNOBS[name]

    def test_an_unknown_name_is_refused_listing_every_knob_and_alias(self) -> None:
        """knob_named of no knob's name raises ConfigurationError naming it, every canonical name and every alias."""
        with pytest.raises(ConfigurationError) as refused:
            knob_named("battery_kwh")

        message = str(refused.value)
        assert "battery_kwh" in message
        assert [name for name in (*KNOBS, *ALIASES) if name not in message] == []

    def test_the_finance_knobs_are_financeconfigs_real_number_fields(self) -> None:
        """The year counts and grid_services_model are not knobs; every real-number finance field is."""
        assert {field.name for field in dataclasses.fields(FinanceConfig)} & set(KNOBS) == _REAL_NUMBER_FINANCE_FIELDS

    def test_names_with_aliases_names_each_knob_given_with_its_aliases(self) -> None:
        """The listing names each knob by its canonical name, its aliases after it in parentheses, in the order given."""
        listing = names_with_aliases([KNOBS["pv_capacity_kw"], knob_named("seg")])

        assert listing == "pv_capacity_kw, seg_tariff_pence_per_kwh (seg)"

    def test_the_knob_listing_names_every_knob_with_its_aliases_after_its_framing(self) -> None:
        """knob_listing frames the registry's every canonical name and alias, in registry order, as a clause a sentence can end with."""
        listing = knob_listing()

        assert listing.startswith("the knobs, each with its aliases: pv_capacity_kw, inverter_capacity_kw")
        assert [name for name in (*KNOBS, *ALIASES) if name not in listing] == []

    @pytest.mark.parametrize("name", [*KNOBS, *ALIASES], ids=str)
    def test_is_knob_name_holds_for_every_canonical_name_and_every_alias(self, name: str) -> None:
        """Each knob's canonical name and each alias is a knob name."""
        assert is_knob_name(name) is True

    @pytest.mark.parametrize("name", ["battery_kwh", "CAP", ""], ids=repr)
    def test_is_knob_name_holds_for_no_other_name(self, name: str) -> None:
        """A name that is no knob's canonical name and no alias is not a knob name, and knob_named refuses it."""
        assert is_knob_name(name) is False
        with pytest.raises(ConfigurationError):
            knob_named(name)


class TestFinanceKnobs:
    """A finance knob sets one FinanceConfig field on the copy it returns."""

    def test_a_finance_knob_sets_that_field_on_the_copy_only(self) -> None:
        """The field is set on the returned finance; the other fields and the argument are kept."""
        scenario = _default_fleet()
        assert scenario.finance is not None
        old_battery_cost = scenario.finance.battery_cost_per_kwh_gbp

        new = knob_named("battery_cost_per_kwh_gbp").apply(scenario, 999.0)

        assert new.finance is not None
        assert new.finance.battery_cost_per_kwh_gbp == pytest.approx(999.0)
        assert new.finance.pv_cost_per_kwp_gbp == pytest.approx(scenario.finance.pv_cost_per_kwp_gbp)
        assert scenario.finance.battery_cost_per_kwh_gbp == pytest.approx(old_battery_cost)

    def test_grid_services_prices_the_copy_at_the_flat_rate_it_is_given(self) -> None:
        """grid_services sets the returned finance's grid_services_model to FlatGridServices at the rate."""
        new = knob_named("grid_services").apply(_default_fleet(), 42.0)

        assert new.finance is not None
        assert new.finance.grid_services_model == FlatGridServices(42.0)

    def test_grid_services_at_zero_prices_the_copy_at_no_grid_services(self) -> None:
        """A zero rate is NoGridServices, which FlatGridServices refuses to stand for."""
        scenario = _default_fleet()
        assert scenario.finance is not None
        scenario = dataclasses.replace(
            scenario, finance=dataclasses.replace(scenario.finance, grid_services_model=FlatGridServices(12.0))
        )

        new = knob_named("grid_services").apply(scenario, 0.0)

        assert new.finance is not None
        assert new.finance.grid_services_model == NoGridServices()

    @pytest.mark.parametrize(
        ("rate", "pricing"), [(0.0, NoGridServices()), (12.0, FlatGridServices(12.0))]
    )
    def test_flat_rate_pricing_is_no_grid_services_at_zero_and_the_flat_rate_above(
        self, rate: float, pricing: object
    ) -> None:
        """flat_rate_pricing is the one rule the knob, and a builder priced at a flat rate, read a rate through."""
        assert flat_rate_pricing(rate) == pricing

    @pytest.mark.parametrize(
        ("rate", "requirement"),
        [(-1.0, "at least 0"), (float("nan"), "a finite number"), (float("inf"), "a finite number")],
    )
    def test_grid_services_refuses_a_rate_below_zero_or_not_finite_naming_itself_and_the_bound_it_applies(
        self, rate: float, requirement: str
    ) -> None:
        """The knob takes 0 as no grid services, so it refuses below 0 itself, under its own name, rather than leaving FlatGridServices to refuse 0 and below."""
        with pytest.raises(ConfigurationError) as refused:
            knob_named("grid_services").apply(_default_fleet(), rate)

        assert str(refused.value) == f"grid_services_income_per_kw_per_year_gbp must be {requirement}, got {rate!r}"

    def test_grid_services_leaves_the_argument_scenario_unchanged(self) -> None:
        scenario = _default_fleet()
        before = copy.deepcopy(scenario)

        knob_named("grid_services").apply(scenario, 42.0)

        assert scenario == before

    def test_grid_services_under_the_events_model_is_refused_naming_the_knob_and_the_model(self) -> None:
        """The capacity-at-events model reads no flat rate, so the knob refuses rather than silently replacing the model."""
        scenario = _default_fleet()
        assert scenario.finance is not None
        scenario = dataclasses.replace(
            scenario, finance=dataclasses.replace(scenario.finance, grid_services_model=GridServicesEventsConfig())
        )

        with pytest.raises(ConfigurationError) as refused:
            knob_named("grid_services").apply(scenario, 42.0)

        assert "grid_services_income_per_kw_per_year_gbp" in str(refused.value)
        assert "capacity_at_events" in str(refused.value)
        assert repr(scenario.name) in str(refused.value)
        assert str(refused.value).endswith(FLAT_PRICING_REMEDY)

    def test_a_finance_knob_on_a_scenario_without_finance_is_refused_naming_the_knob_and_the_scenario(self) -> None:
        """With finance None the knob raises ConfigurationError naming itself and the scenario, not a TypeError."""
        scenario = dataclasses.replace(_default_fleet(), finance=None)

        with pytest.raises(ConfigurationError) as refused:
            knob_named("battery_cost_per_kwh_gbp").apply(scenario, 999.0)

        assert "battery_cost_per_kwh_gbp" in str(refused.value)
        assert scenario.name in str(refused.value)


class TestTheSegKnob:
    """The SEG knob sets the scenario's rate, which each home without a tariff of its own exports at."""

    @pytest.mark.parametrize("name", ["seg", "seg_tariff_pence_per_kwh"])
    def test_it_sets_the_rate_every_simulated_home_exports_at(self, name: str) -> None:
        """Either name sets only the scenario's rate: the stored homes and the finance are kept."""
        scenario = _default_fleet()

        new = knob_named(name).apply(scenario, 7.5)

        assert new.seg_tariff_pence_per_kwh == pytest.approx(7.5)
        assert new.homes == scenario.homes
        assert [home.seg_tariff for home in new.simulated_homes()] == [
            SEGTariff(name="", rate_pence_per_kwh=7.5)
        ] * len(scenario.homes)
        assert new.finance is scenario.finance

    def test_it_keeps_the_homes_carrying_the_swept_rate(self) -> None:
        """Homes whose own tariff already sets the swept rate are accepted, each keeping its tariff."""
        octopus = resolve_seg_tariff("Octopus")
        scenario = _fleet_carrying([octopus, None])

        new = knob_named("seg").apply(scenario, octopus.rate_pence_per_kwh)

        assert new.seg_tariff_pence_per_kwh == pytest.approx(octopus.rate_pence_per_kwh)
        assert new.homes == scenario.homes

    def test_it_refuses_a_rate_segtariff_refuses_as_it_sets_it(self) -> None:
        """A rate SEGTariff refuses is refused by the knob itself, naming the rate, not later by a sweep."""
        with pytest.raises(ConfigurationError, match=r"seg_tariff_pence_per_kwh=-1\.0.*at least 0"):
            knob_named("seg").apply(_default_fleet(), -1.0)


class TestTheDegradationKnob:
    """The degradation knob sets every home's PV degradation."""

    @pytest.mark.parametrize("name", ["degradation", "degradation_rate_per_year"])
    def test_it_sets_every_homes_pv_degradation(self, name: str) -> None:
        """Either name sets degradation_rate_per_year on every home's PV."""
        scenario = _default_fleet()

        new = knob_named(name).apply(scenario, 0.01)

        assert [home.pv_config.degradation_rate_per_year for home in new.homes] == [0.01] * len(scenario.homes)


def test_importing_the_registry_loads_neither_optimize_nor_the_cli() -> None:
    """The registry sits above config and below optimize and the CLI, so importing it loads neither; a CLI module would load its package."""
    loaded = package_modules_loaded_by_importing("solar_challenge.scenario_knobs")

    assert loaded.isdisjoint(frozenset({"solar_challenge.optimize", "solar_challenge.cli"}))


def test_importing_the_registry_loads_no_web_module() -> None:
    """The registry sits below the web, so importing it loads none of the web's modules."""
    assert web_modules_loaded_by_importing("solar_challenge.scenario_knobs") == frozenset()
