# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for web.sweep_request: the web sweep's parameters and its request reader."""

import pytest

pytest.importorskip("flask")

from solar_challenge.config import ScenarioConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import SweepMode, SweepSpec
from solar_challenge.home import run_window
from solar_challenge.scenario_knobs import knob_named
from solar_challenge.web.fleet_components import FLEET_COMPONENTS
from solar_challenge.web.simulation_params import parse_home_config
from solar_challenge.web.sweep_request import (
    SWEEP_MAX_STEPS,
    SWEEP_PARAMETERS,
    SweepParameter,
    SweepRequest,
    read_sweep_request,
)


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


def _battery_body(**fields: object) -> dict[str, object]:
    """A battery_capacity_kwh sweep body from 1 to 4 in 3 steps, with *fields* sent beside or instead."""
    return {"parameter": "battery_capacity_kwh", "min": 1, "max": 4, "steps": 3, **fields}


class TestReadSweepRequest:
    """read_sweep_request reads a sweep request body into a SweepRequest, each field it omits taking the reader's default."""

    def test_a_body_without_a_mode_reads_as_the_sweep_specs_default_mode(self) -> None:
        sweep = read_sweep_request(_battery_body())

        assert sweep == SweepRequest(SWEEP_PARAMETERS["battery_capacity_kwh"], SweepSpec(1.0, 4.0, 3))
        assert sweep.values() == (1.0, 2.0, 4.0)

    def test_a_linear_mode_reads_as_linear(self) -> None:
        assert read_sweep_request(_battery_body(mode="linear")).spec.mode is SweepMode.LINEAR

    def test_a_null_mode_reads_as_omitted(self) -> None:
        assert read_sweep_request(_battery_body(mode=None)) == read_sweep_request(_battery_body())

    def test_an_empty_body_sweeps_the_first_parameter_over_its_starting_range_in_5_steps(self) -> None:
        sweep = read_sweep_request({})

        assert sweep.parameter is SWEEP_PARAMETERS["pv_capacity_kw"]
        assert (sweep.spec.min, sweep.spec.max, sweep.spec.steps) == (2.0, 8.0, 5)
        # 2 kW to 8 kW at a ratio of 4 ** (1 / 4), the square root of 2, between points
        assert sweep.values() == (2.0, 2.828, 4.0, 5.657, 8.0)

    def test_values_rounds_each_point_to_3_decimals_as_a_tuple(self) -> None:
        sweep = read_sweep_request({"min": 1, "max": 2, "steps": 4, "mode": "linear"})

        assert sweep.values() == (1.0, 1.333, 1.667, 2.0)
        assert isinstance(sweep.values(), tuple)


class TestReadSweepRequestRefusals:
    """Every refusal of read_sweep_request is a ConfigurationError naming the field it refuses."""

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            pytest.param({"parameter": 5}, "parameter must be a JSON string, got int", id="parameter-not-text"),
            pytest.param({"min": float("inf")}, "min must be a finite number, got inf", id="min-infinite"),
            pytest.param({"max": 10**400}, f"max must be a finite number, got {10**400!r}", id="max-too-large"),
            pytest.param({"steps": 1}, f"steps must be between 2 and {SWEEP_MAX_STEPS}, got 1", id="steps-too-few"),
            pytest.param(
                {"steps": SWEEP_MAX_STEPS + 1},
                f"steps must be between 2 and {SWEEP_MAX_STEPS}, got {SWEEP_MAX_STEPS + 1}",
                id="steps-too-many",
            ),
            pytest.param({"steps": 2.5}, "steps must be a whole number, got 2.5", id="steps-fraction"),
            pytest.param({"mode": "log"}, "mode must be linear or geometric, got 'log'", id="mode-unknown"),
            pytest.param({"mode": 5}, "mode must be a JSON string, got int", id="mode-not-text"),
        ],
    )
    def test_a_field_it_cannot_read_is_refused_naming_the_field(self, body: dict[str, object], message: str) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            read_sweep_request(body)

        assert str(refusal.value) == message

    def test_an_unknown_parameter_is_refused_naming_it_and_every_parameter(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            read_sweep_request({"parameter": "tilt"})

        assert "parameter" in str(refusal.value)
        assert "'tilt'" in str(refusal.value)
        for key in SWEEP_PARAMETERS:
            assert key in str(refusal.value)

    @pytest.mark.parametrize("key", tuple(SWEEP_PARAMETERS))
    @pytest.mark.parametrize("end", ["min", "max"])
    def test_an_end_outside_the_parameters_range_is_refused_naming_the_end_the_knob_and_the_range(
        self, key: str, end: str
    ) -> None:
        parameter = SWEEP_PARAMETERS[key]
        bounds = {"min": parameter.default_min, "max": parameter.default_max}
        outside = parameter.value_range.low - 1 if end == "min" else parameter.value_range.high + 1

        with pytest.raises(ConfigurationError) as refusal:
            read_sweep_request({"parameter": key, **bounds, end: outside, "steps": 3, "mode": "linear"})

        assert str(refusal.value) == f"{end} of a {key} sweep must be {parameter.value_range}, got {float(outside)!r}"

    def test_a_battery_max_of_200_is_refused_naming_the_knob_and_its_range(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            read_sweep_request(
                {"parameter": "battery_capacity_kwh", "min": 0, "max": 200, "steps": 3, "mode": "linear"}
            )

        assert str(refusal.value) == "max of a battery_capacity_kwh sweep must be between 0 and 100, got 200.0"

    def test_a_geometric_sweep_from_0_is_refused_with_the_sweep_specs_own_refusal(self) -> None:
        with pytest.raises(ConfigurationError) as spec_refusal:
            SweepSpec(0.0, 10.0, 3, SweepMode.GEOMETRIC)

        with pytest.raises(ConfigurationError) as refusal:
            read_sweep_request(_battery_body(min=0, max=10, mode="geometric"))

        assert str(refusal.value) == str(spec_refusal.value)


def test_a_sweep_request_built_in_code_is_held_to_its_parameters_range() -> None:
    with pytest.raises(ConfigurationError) as refusal:
        SweepRequest(SWEEP_PARAMETERS["pv_capacity_kw"], SweepSpec(5.0, 25.0, 3, SweepMode.LINEAR))

    assert str(refusal.value) == "max of a pv_capacity_kw sweep must be between 0.5 and 20, got 25.0"
