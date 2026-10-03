"""Tests for solar_challenge.web.simulation_params, called directly with parameter dicts."""

import re
from collections.abc import Callable
from operator import attrgetter

import pytest
pytest.importorskip("flask")

from solar_challenge.config import ConfigurationError
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.seg import SEG_PRESETS, SEGTariff
from solar_challenge.web.shared import NotAJsonObject
from solar_challenge.web.simulation_params import (
    parse_date_range,
    parse_home_config,
    parse_seg_tariff,
)


VALID_HOME_PAYLOAD: dict = {
    "pv_kw": 4.0,
    "battery_kwh": 5.0,
    "occupants": 3,
    "location": "bristol",
    "days": 7,
    "name": "Test Home",
}

FORM_PAYLOAD_BATTERY_ON: dict = {
    "pv_kw": 4.0,
    "azimuth": 180.0,
    "tilt": 35.0,
    "system_age_years": 5.0,
    "degradation_rate_per_year": 0.005,
    "battery_kwh": 5.0,
    "max_charge_kw": 2.5,
    "max_discharge_kw": 2.5,
    "efficiency_pct": 90.0,
    "consumption_kwh": 3200.0,
    "occupants": 3,
    "stochastic": False,
    "location": "bristol",
    "name": "Every panel",
    "days": 7,
    "heat_pump": {"type": "ASHP", "thermal_capacity_kw": 8.0, "annual_heat_demand_kwh": 8000.0},
    "tariff": {"type": "flat_rate", "rate_per_kwh": 0.30},
    "seg": {"preset": "Octopus"},
    "dispatch_strategy": {"strategy_type": "tou_optimized", "peak_hours": [[16, 19]]},
}

FORM_PAYLOAD_BATTERY_OFF: dict = {
    "pv_kw": 4.0,
    "azimuth": 180.0,
    "tilt": 35.0,
    "system_age_years": 0.0,
    "degradation_rate_per_year": 0.005,
    "battery_kwh": 0,
    "max_charge_kw": None,
    "max_discharge_kw": None,
    "efficiency_pct": None,
    "consumption_kwh": 3200.0,
    "occupants": 3,
    "stochastic": False,
    "location": "bristol",
    "name": "Web Simulation",
    "start": "2024-03-01",
    "end": "2024-03-05",
}


class TestParseDateRange:
    """Unit tests for the parse_date_range(data) helper."""

    def test_days_seven_returns_june_window(self) -> None:
        """days=7 returns a 7-day window starting 2024-06-01."""
        start, end = parse_date_range({"days": 7})
        assert start == "2024-06-01"
        assert end == "2024-06-07"

    def test_days_one_is_a_single_day_window(self) -> None:
        """days=1 starts and ends on the same day."""
        assert parse_date_range({"days": 1}) == ("2024-06-01", "2024-06-01")

    def test_days_365_returns_full_year(self) -> None:
        """days=365 is the special case: returns the full 2024 calendar year."""
        start, end = parse_date_range({"days": 365})
        assert start == "2024-01-01"
        assert end == "2024-12-31"

    def test_explicit_start_end_returned_verbatim(self) -> None:
        """Explicit start/end strings are returned as-is."""
        start, end = parse_date_range({"start": "2024-03-01", "end": "2024-03-05"})
        assert start == "2024-03-01"
        assert end == "2024-03-05"

    def test_empty_data_returns_full_year_defaults(self) -> None:
        """Empty dict returns the default full-year window."""
        start, end = parse_date_range({})
        assert start == "2024-01-01"
        assert end == "2024-12-31"

    def test_days_zero_raises_value_error(self) -> None:
        """days=0 is not a valid window; must raise ValueError."""
        with pytest.raises(ValueError, match="positive"):
            parse_date_range({"days": 0})

    def test_days_negative_raises_value_error(self) -> None:
        """Negative days must raise ValueError."""
        with pytest.raises(ValueError, match="positive"):
            parse_date_range({"days": -7})


class TestParseHomeConfigKeys:
    """Which top-level keys parse_home_config accepts."""

    def test_unrecognised_keys_are_refused_by_name(self) -> None:
        """The home form's Alpine field names are refused by name, and the error lists the recognised keys."""
        with pytest.raises(ValueError) as exc_info:
            parse_home_config({**VALID_HOME_PAYLOAD, "period_days": 1, "battery_enabled": False})
        message = str(exc_info.value)
        assert "period_days" in message
        assert "battery_enabled" in message
        assert "battery_kwh" in message
        assert "start" in message

    @pytest.mark.parametrize(
        ("home_config", "type_name"),
        [
            pytest.param([1], "list", id="array"),
            pytest.param("x", "str", id="string"),
            pytest.param(1, "int", id="number"),
            pytest.param(True, "bool", id="boolean"),
            pytest.param(None, "NoneType", id="null"),
        ],
    )
    def test_home_config_that_is_not_an_object_is_refused_naming_its_type(
        self, home_config: object, type_name: str
    ) -> None:
        """A JSON value that is not an object is refused with the web's shared NotAJsonObject, naming the type sent."""
        with pytest.raises(NotAJsonObject) as exc_info:
            parse_home_config(home_config)
        assert str(exc_info.value) == f"Home config must be a JSON object, got {type_name}"

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(FORM_PAYLOAD_BATTERY_ON, id="battery-on"),
            pytest.param(FORM_PAYLOAD_BATTERY_OFF, id="battery-off"),
        ],
    )
    def test_payloads_of_recognised_keys_are_accepted(self, payload: dict) -> None:
        """Bodies shaped like the home form's buildPayload() output parse."""
        _home_config, _start, _end, name = parse_home_config(payload)
        assert name == payload["name"]


class TestParseSegTariff:
    """parse_seg_tariff adapts config.parse_seg_rate; config/test_tariff_blocks.py::TestScenarioSegBlock covers that grammar case by case."""

    def test_absent_seg_is_no_tariff(self) -> None:
        """A null seg value, like an absent one, means no SEG."""
        assert parse_seg_tariff(None) is None

    def test_preset_reads_as_a_tariff_at_the_supplier_rate(self) -> None:
        """A preset reads as a tariff at that supplier's export rate."""
        assert parse_seg_tariff({"preset": "Octopus"}) == SEGTariff(
            name="", rate_pence_per_kwh=SEG_PRESETS["Octopus"].rate_pence_per_kwh
        )

    def test_explicit_rate_reads_as_a_tariff_at_that_rate(self) -> None:
        """An explicit rate_pence_per_kwh reads as a tariff at that rate."""
        assert parse_seg_tariff({"rate_pence_per_kwh": 5.5}) == SEGTariff(
            name="", rate_pence_per_kwh=5.5
        )

    @pytest.mark.parametrize(
        "seg",
        [
            pytest.param({"preset": "NotASupplier"}, id="unknown-preset"),
            pytest.param({"rate_pence_per_kwh": float("nan")}, id="nan-rate"),
        ],
    )
    def test_refused_seg_raises_value_error_from_the_grammar_error(self, seg: object) -> None:
        """A value the grammar refuses raises ValueError chained from its ConfigurationError, carrying that message."""
        with pytest.raises(ValueError) as exc_info:
            parse_seg_tariff(seg)
        grammar_error = exc_info.value.__cause__
        assert isinstance(grammar_error, ConfigurationError)
        assert str(exc_info.value) == str(grammar_error)


class TestParseHomeConfigCapabilities:
    """Boundary tests calling parse_home_config directly."""

    def test_heat_pump_fields_populate_home_config(self) -> None:
        """heat_pump dict in payload populates HomeConfig.heat_pump_config."""
        payload = {
            **VALID_HOME_PAYLOAD,
            "heat_pump": {
                "type": "ASHP",
                "thermal_capacity_kw": 8.0,
                "annual_heat_demand_kwh": 8000,
            },
        }
        home_config, _start, _end, _name = parse_home_config(payload)
        assert home_config.heat_pump_config is not None
        assert home_config.heat_pump_config.heat_pump_type == "ASHP"
        assert home_config.heat_pump_config.thermal_capacity_kw == 8.0

    def test_tariff_fields_populate_home_config(self) -> None:
        """tariff dict in payload populates HomeConfig.tariff_config."""
        payload = {
            **VALID_HOME_PAYLOAD,
            "tariff": {
                "type": "flat_rate",
                "rate_per_kwh": 0.30,
            },
        }
        home_config, _start, _end, _name = parse_home_config(payload)
        assert home_config.tariff_config is not None
        # flat_rate TariffConfig has at least one period
        assert len(home_config.tariff_config.periods) > 0

    def test_combined_heat_pump_tariff_dispatch_populate_home_config(self) -> None:
        """heat_pump + tariff + dispatch_strategy all populate when battery is enabled."""
        payload = {
            **VALID_HOME_PAYLOAD,
            "battery_kwh": 5.0,
            "heat_pump": {
                "type": "ASHP",
                "thermal_capacity_kw": 8.0,
                "annual_heat_demand_kwh": 8000,
            },
            "tariff": {
                "type": "flat_rate",
                "rate_per_kwh": 0.30,
            },
            "dispatch_strategy": {
                "strategy_type": "self_consumption",
            },
        }
        home_config, _start, _end, _name = parse_home_config(payload)
        assert home_config.heat_pump_config is not None
        assert home_config.tariff_config is not None
        assert home_config.battery_config is not None
        assert home_config.battery_config.dispatch_strategy is not None
        assert home_config.battery_config.dispatch_strategy.strategy_type == "self_consumption"

    def test_dispatch_strategy_ignored_without_battery(self) -> None:
        """dispatch_strategy is silently ignored when no battery is enabled."""
        payload = {
            **VALID_HOME_PAYLOAD,
            "battery_kwh": 0,
            "dispatch_strategy": {
                "strategy_type": "self_consumption",
            },
        }
        home_config, _start, _end, _name = parse_home_config(payload)
        assert home_config.battery_config is None  # no battery => no dispatch either


class TestParseHomeConfigHeatPumpBlock:
    """The heat_pump block: the web form's keys, defaulted when omitted; a value that is not a mapping is refused."""

    @pytest.mark.parametrize(
        ("value", "type_name"),
        [
            pytest.param("ASHP", "str", id="string"),
            pytest.param(True, "bool", id="boolean"),
            pytest.param(["ASHP"], "list", id="array"),
            pytest.param(5, "int", id="number"),
        ],
    )
    def test_heat_pump_that_is_not_a_mapping_is_refused_naming_its_type(
        self, value: object, type_name: str
    ) -> None:
        """A heat_pump that is not an object is refused with a ValueError naming heat_pump and the type sent."""
        with pytest.raises(
            ValueError, match=re.escape(f"heat_pump must be a mapping, got {type_name}")
        ):
            parse_home_config({**VALID_HOME_PAYLOAD, "heat_pump": value})

    def test_empty_heat_pump_is_the_default_heat_pump(self) -> None:
        """An empty heat_pump is a mapping whose every key defaults: an 8 kW ASHP with 8000 kWh annual heat demand."""
        home_config, _start, _end, _name = parse_home_config(
            {**VALID_HOME_PAYLOAD, "heat_pump": {}}
        )
        assert home_config.heat_pump_config == HeatPumpConfig(
            heat_pump_type="ASHP", thermal_capacity_kw=8.0, annual_heat_demand_kwh=8000.0
        )


# Each nested block's key, and the HomeConfig field its parsed value fills.
# VALID_HOME_PAYLOAD has a battery, so parse_home_config reads dispatch_strategy.
NESTED_BLOCK_FIELDS: dict[str, Callable[[HomeConfig], object]] = {
    "heat_pump": attrgetter("heat_pump_config"),
    "seg": attrgetter("seg_tariff"),
    "tariff": attrgetter("tariff_config"),
    "dispatch_strategy": attrgetter("battery_config.dispatch_strategy"),
}


class TestParseHomeConfigNestedBlockPresence:
    """One presence rule for the four nested blocks: null means none; any other value must be a mapping its grammar reads."""

    @pytest.mark.parametrize(
        ("key", "parsed_block"),
        [pytest.param(key, field, id=key) for key, field in NESTED_BLOCK_FIELDS.items()],
    )
    def test_null_block_means_none(
        self, key: str, parsed_block: Callable[[HomeConfig], object]
    ) -> None:
        """A null block, like an absent one, means none."""
        home_config, _start, _end, _name = parse_home_config({**VALID_HOME_PAYLOAD, key: None})
        assert parsed_block(home_config) is None

    @pytest.mark.parametrize(
        ("value", "type_name"),
        [
            pytest.param("", "str", id="empty-string"),
            pytest.param(False, "bool", id="false"),
            pytest.param(0, "int", id="zero"),
            pytest.param([], "list", id="empty-array"),
        ],
    )
    @pytest.mark.parametrize("key", list(NESTED_BLOCK_FIELDS))
    def test_falsy_block_is_refused_naming_it_and_its_type(
        self, key: str, value: object, type_name: str
    ) -> None:
        """A falsy value other than null is not a mapping, so it is refused with a ValueError naming the block and the type sent."""
        with pytest.raises(ValueError, match=re.escape(f"{key} must be a mapping, got {type_name}")):
            parse_home_config({**VALID_HOME_PAYLOAD, key: value})

    @pytest.mark.parametrize("key", ["seg", "tariff", "dispatch_strategy"])
    def test_empty_block_is_refused_by_its_grammar(self, key: str) -> None:
        """An empty block is a mapping its grammar reads; a grammar that requires a key refuses it, and the ValueError carries that grammar's ConfigurationError message."""
        with pytest.raises(ValueError) as exc_info:
            parse_home_config({**VALID_HOME_PAYLOAD, key: {}})
        grammar_error = exc_info.value.__cause__
        assert isinstance(grammar_error, ConfigurationError)
        assert str(exc_info.value) == str(grammar_error)


class TestParseHomeConfigBatteryEfficiency:
    """The form's round-trip efficiency percentage reaches BatteryConfig as a fraction."""

    @pytest.mark.parametrize(
        ("efficiency_pct", "round_trip"),
        [
            pytest.param(90, 0.9, id="form-default"),
            pytest.param(100, 1.0, id="lossless"),
        ],
    )
    def test_efficiency_pct_becomes_round_trip_fraction(
        self, efficiency_pct: float, round_trip: float
    ) -> None:
        """The percentage becomes the fraction of energy a full charge-discharge cycle keeps."""
        home_config, _start, _end, _name = parse_home_config(
            {**VALID_HOME_PAYLOAD, "battery_kwh": 5.0, "efficiency_pct": efficiency_pct}
        )
        battery = home_config.battery_config
        assert battery is not None
        assert battery.efficiency == pytest.approx(round_trip)
        assert battery.charge_efficiency * battery.discharge_efficiency == pytest.approx(round_trip)

    def test_out_of_range_efficiency_pct_is_refused_in_the_units_sent(self) -> None:
        """An out-of-range percentage is reported as sent (150), not as BatteryConfig's 1.5."""
        with pytest.raises(ValueError, match="got 150"):
            parse_home_config({**VALID_HOME_PAYLOAD, "battery_kwh": 5.0, "efficiency_pct": 150})


class TestParseHomeConfigPVAge:
    """PV-age boundary tests: form→PVConfig threading (§D contract)."""

    def test_direct_parse_sets_both_age_fields(self) -> None:
        """parse_home_config with explicit age values sets both PVConfig fields."""
        payload = {
            **VALID_HOME_PAYLOAD,
            "system_age_years": 15,
            "degradation_rate_per_year": 0.01,
        }
        home_config, _start, _end, _name = parse_home_config(payload)
        assert home_config.pv_config.system_age_years == 15.0
        assert home_config.pv_config.degradation_rate_per_year == 0.01

    def test_absent_age_keys_yield_pv_config_defaults(self) -> None:
        """parse_home_config with no age keys yields PVConfig default values."""
        home_config, _start, _end, _name = parse_home_config(VALID_HOME_PAYLOAD)
        assert home_config.pv_config.system_age_years == 0.0
        assert home_config.pv_config.degradation_rate_per_year == 0.005


class TestParseHomeConfigSEG:
    """Boundary tests for the SEG export-rate field round-trip (task #21).

    Scope (per PRD §14): validates field population only — not end-to-end
    simulation pricing (which is task #2's already-proven math).
    """

    def test_preset_resolves_to_correct_seg_tariff(self) -> None:
        """'seg': {'preset': 'Octopus'} yields SEGTariff with Octopus Energy rate."""
        home_config, _start, _end, _name = parse_home_config(
            {**VALID_HOME_PAYLOAD, "seg": {"preset": "Octopus"}}
        )
        assert home_config.seg_tariff is not None
        assert home_config.seg_tariff.rate_pence_per_kwh == pytest.approx(4.1)

    def test_explicit_rate_populates_seg_tariff(self) -> None:
        """'seg': {'rate_pence_per_kwh': 5.5} yields SEGTariff with that rate."""
        home_config, _start, _end, _name = parse_home_config(
            {**VALID_HOME_PAYLOAD, "seg": {"rate_pence_per_kwh": 5.5}}
        )
        assert home_config.seg_tariff is not None
        assert home_config.seg_tariff.rate_pence_per_kwh == pytest.approx(5.5)

    def test_absent_seg_key_yields_none(self) -> None:
        """Plain VALID_HOME_PAYLOAD (no 'seg' key) gives seg_tariff=None (back-compat)."""
        home_config, _start, _end, _name = parse_home_config(VALID_HOME_PAYLOAD)
        assert home_config.seg_tariff is None

    def test_malformed_seg_is_refused_with_value_error(self) -> None:
        """A malformed seg is refused with the ValueError every web caller answers with HTTP 400."""
        with pytest.raises(ValueError, match="seg"):
            parse_home_config({**VALID_HOME_PAYLOAD, "seg": [1, 2]})
