# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for web.sweep_request: the web sweep's parameters and its request reader."""

import pytest

pytest.importorskip("flask")

from solar_challenge.config import ScenarioConfig
from solar_challenge.home import run_window
from solar_challenge.scenario_knobs import knob_named
from solar_challenge.web.fleet_components import FLEET_COMPONENTS
from solar_challenge.web.simulation_params import parse_home_config
from solar_challenge.web.sweep_request import SWEEP_PARAMETERS, SweepParameter


def _single_home_scenario(body: dict[str, object]) -> ScenarioConfig:
    """The single-home scenario of the home parse_home_config reads from *body*, over the window it reads."""
    home, start, end, _ = parse_home_config(body)
    return ScenarioConfig(name="sweep base", period=run_window(home.location, start, end), home=home)


class TestSweepParameters:
    """SWEEP_PARAMETERS, the parameters the sweep page offers, and what each row sets."""

    def test_the_parameters_are_the_pages_options_in_order(self) -> None:
        assert list(SWEEP_PARAMETERS) == ["pv_capacity_kw", "battery_capacity_kwh", "annual_consumption_kwh"]

    @pytest.mark.parametrize(
        ("key", "label", "starting_range", "component_key"),
        [
            pytest.param("pv_capacity_kw", "PV Capacity (kW)", (2.0, 8.0), "pv", id="pv"),
            pytest.param("battery_capacity_kwh", "Battery Capacity (kWh)", (0.0, 13.5), "battery", id="battery"),
            pytest.param("annual_consumption_kwh", "Annual Consumption (kWh)", (2000.0, 5000.0), "load", id="load"),
        ],
    )
    def test_each_parameter_carries_its_knob_label_starting_range_and_component_range(
        self, key: str, label: str, starting_range: tuple[float, float], component_key: str
    ) -> None:
        parameter = SWEEP_PARAMETERS[key]

        assert parameter.knob is knob_named(key)
        assert parameter.label == label
        assert (parameter.default_min, parameter.default_max) == starting_range
        assert parameter.value_range == FLEET_COMPONENTS[component_key].value_range

    @pytest.mark.parametrize("parameter", tuple(SWEEP_PARAMETERS.values()), ids=tuple(SWEEP_PARAMETERS))
    def test_each_knob_sets_the_value_its_component_reads(self, parameter: SweepParameter) -> None:
        base = _single_home_scenario({"days": 7})

        swept = parameter.knob.apply(base, parameter.default_max)

        assert parameter.component.value_of(swept.simulated_homes()[0]) == parameter.default_max


class TestSweepParameterRefusals:
    """A SweepParameter construction refuses names the offending field and value."""

    def test_a_knob_that_does_not_set_each_home_is_refused(self) -> None:
        seg = knob_named("seg")

        with pytest.raises(ValueError) as refusal:
            SweepParameter(seg, FLEET_COMPONENTS["pv"], 2.0, 8.0)

        assert "knob" in str(refusal.value)
        assert seg.name in str(refusal.value)

    @pytest.mark.parametrize(
        ("default_min", "default_max", "field", "value"),
        [
            pytest.param(-1.0, 13.5, "default_min", "-1.0", id="default-min-below-the-range"),
            pytest.param(0.0, 101.0, "default_max", "101.0", id="default-max-above-the-range"),
        ],
    )
    def test_a_starting_range_outside_the_components_range_is_refused(
        self, default_min: float, default_max: float, field: str, value: str
    ) -> None:
        with pytest.raises(ValueError) as refusal:
            SweepParameter(knob_named("battery_capacity_kwh"), FLEET_COMPONENTS["battery"], default_min, default_max)

        assert field in str(refusal.value)
        assert value in str(refusal.value)

    @pytest.mark.parametrize("default_min", [8.0, 9.0], ids=["equal", "above"])
    def test_a_default_min_not_below_the_default_max_is_refused(self, default_min: float) -> None:
        with pytest.raises(ValueError) as refusal:
            SweepParameter(knob_named("pv_capacity_kw"), FLEET_COMPONENTS["pv"], default_min, 8.0)

        assert "default_min" in str(refusal.value)
        assert str(default_min) in str(refusal.value)
