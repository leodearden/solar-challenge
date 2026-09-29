"""Tests for solar_challenge.web.simulation_params, called directly with parameter dicts."""

import pytest
pytest.importorskip("flask")

from solar_challenge.seg import SEGTariff
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


class TestParseDateRange:
    """Unit tests for the parse_date_range(data) helper."""

    def test_days_seven_returns_june_window(self) -> None:
        """days=7 returns a 7-day window starting 2024-06-01."""
        start, end = parse_date_range({"days": 7})
        assert start == "2024-06-01"
        assert end == "2024-06-07"

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


class TestParseSegTariff:
    """Unit tests for parse_seg_tariff(seg_data)."""

    def test_custom_preset_falls_through_to_explicit_rate(self) -> None:
        """preset 'custom' is the UI sentinel for "use the explicit rate", not a preset name."""
        tariff = parse_seg_tariff({"preset": "custom", "rate_pence_per_kwh": 5.5})
        assert tariff == SEGTariff(name="Custom", rate_pence_per_kwh=5.5)

    def test_null_rate_raises_type_error(self) -> None:
        """A null rate (the browser's NaN from a blank input) is refused, not ignored."""
        with pytest.raises(TypeError):
            parse_seg_tariff({"rate_pence_per_kwh": None})

    def test_unknown_preset_raises_value_error(self) -> None:
        """A preset name outside the SEG catalogue raises ValueError."""
        with pytest.raises(ValueError, match="Unknown SEG preset"):
            parse_seg_tariff({"preset": "NotASupplier"})


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
        assert home_config.seg_tariff.name == "Octopus Energy"

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
