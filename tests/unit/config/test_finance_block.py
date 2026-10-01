# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the finance: block and the FinanceConfig it parses into."""

import dataclasses
import pickle
from pathlib import Path

import pytest

from solar_challenge.config import (
    ConfigurationError,
    FinanceConfig,
    ScenarioConfig,
    SimulationPeriod,
    load_scenarios,
    parse_finance_config,
)
from solar_challenge.gridservices import EventWindow, GridServicesEventsConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig


class TestFinanceConfig:
    """Tests for FinanceConfig dataclass construction, defaults, and immutability."""

    def test_construction_with_required_arg(self) -> None:
        """FinanceConfig can be constructed with only standing_charge_pence_per_day."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.standing_charge_pence_per_day == 60.0

    _DECLARED_DEFAULTS: dict[str, object] = {
        "vat_rate": 0.05,
        "retail_baseline_rate_pence_per_kwh": 23.0,
        "self_consumption_override": None,
        "pv_cost_per_kwp_gbp": 1000.0,
        "roof_fit_cost_gbp": 1000.0,
        "battery_cost_per_kwh_gbp": 250.0,
        "inverter_cost_per_kw_gbp": 0.0,
        "grant_gbp": 250000.0,
        "equity_fraction": 0.75,
        "loan_term_years": 15,
        "loan_rate": 0.07,
        "opex_per_home_per_year_gbp": 131.0,
        "asset_life_years": 25,
        "own_use_rate_pence_per_kwh": 15.0,
        "retained_cash_floor_per_home_per_year_gbp": 27.0,
        "grid_services_income_per_kw_per_year_gbp": 0.0,
        "grid_services_model": "flat",
        "grid_services_events": None,
    }

    @pytest.mark.parametrize(
        ("field_name", "declared_default"),
        list(_DECLARED_DEFAULTS.items()),
        ids=list(_DECLARED_DEFAULTS),
    )
    def test_declared_default(self, field_name: str, declared_default: object) -> None:
        """A FinanceConfig given only the standing charge holds each field's declared default."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert getattr(fc, field_name) == declared_default

    def test_declared_defaults_cover_every_optional_field(self) -> None:
        """Every FinanceConfig field but the required standing charge has a row in _DECLARED_DEFAULTS."""
        optional_fields = {f.name for f in dataclasses.fields(FinanceConfig)} - {
            "standing_charge_pence_per_day"
        }
        assert set(self._DECLARED_DEFAULTS) == optional_fields, (
            "every optional FinanceConfig field needs a row in _DECLARED_DEFAULTS, "
            "and every row must name a FinanceConfig field"
        )

    def test_defaults_vat_rate(self) -> None:
        """Default vat_rate is 0.05."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.vat_rate == 0.05

    def test_defaults_retail_baseline_rate(self) -> None:
        """Default retail_baseline_rate_pence_per_kwh is 23.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.retail_baseline_rate_pence_per_kwh == 23.0

    def test_defaults_self_consumption_override_is_none(self) -> None:
        """Default self_consumption_override is None."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.self_consumption_override is None

    def test_defaults_pv_cost_per_kwp(self) -> None:
        """Default pv_cost_per_kwp_gbp is 1000.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.pv_cost_per_kwp_gbp == 1000.0

    def test_defaults_roof_fit_cost(self) -> None:
        """Default roof_fit_cost_gbp is 1000.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.roof_fit_cost_gbp == 1000.0

    def test_defaults_battery_cost_per_kwh(self) -> None:
        """Default battery_cost_per_kwh_gbp is 250.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.battery_cost_per_kwh_gbp == 250.0

    def test_defaults_grant_gbp(self) -> None:
        """Default grant_gbp is 250000.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.grant_gbp == 250000.0

    def test_defaults_equity_fraction(self) -> None:
        """Default equity_fraction is 0.75."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.equity_fraction == 0.75

    def test_defaults_loan_term_years(self) -> None:
        """Default loan_term_years is 15."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.loan_term_years == 15

    def test_defaults_loan_rate(self) -> None:
        """Default loan_rate is 0.07."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.loan_rate == 0.07

    def test_defaults_opex_per_home_per_year(self) -> None:
        """Default opex_per_home_per_year_gbp is 131.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.opex_per_home_per_year_gbp == 131.0

    def test_defaults_asset_life_years(self) -> None:
        """Default asset_life_years is 25."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.asset_life_years == 25

    def test_defaults_inverter_cost_per_kw_is_zero(self) -> None:
        """Default inverter_cost_per_kw_gbp is 0.0 (opt-in, zero-allowed)."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.inverter_cost_per_kw_gbp == 0.0

    def test_defaults_own_use_rate_pence_per_kwh(self) -> None:
        """Default own_use_rate_pence_per_kwh is 15.0 (CBS transfer price)."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.own_use_rate_pence_per_kwh == 15.0

    def test_defaults_retained_cash_floor_per_home_per_year_gbp(self) -> None:
        """Default retained_cash_floor_per_home_per_year_gbp is 27.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.retained_cash_floor_per_home_per_year_gbp == 27.0

    def test_defaults_grid_services_income_per_kw_per_year_gbp(self) -> None:
        """Default grid_services_income_per_kw_per_year_gbp is 0.0 (theta-safe seam)."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.grid_services_income_per_kw_per_year_gbp == 0.0

    def test_frozen_raises_on_assignment(self) -> None:
        """FinanceConfig is frozen: attribute assignment raises FrozenInstanceError."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            fc.vat_rate = 0.20  # type: ignore[misc]

    def test_standing_charge_is_required(self) -> None:
        """standing_charge_pence_per_day has no default; omitting it raises TypeError."""
        with pytest.raises(TypeError):
            FinanceConfig()  # type: ignore[call-arg]

    def test_custom_values_round_trip(self) -> None:
        """All fields can be set to custom values and are retrievable."""
        fc = FinanceConfig(
            standing_charge_pence_per_day=75.0,
            vat_rate=0.20,
            retail_baseline_rate_pence_per_kwh=28.0,
            self_consumption_override=0.80,
            pv_cost_per_kwp_gbp=900.0,
            roof_fit_cost_gbp=1200.0,
            battery_cost_per_kwh_gbp=300.0,
            inverter_cost_per_kw_gbp=200.0,
            grant_gbp=200000.0,
            equity_fraction=0.60,
            loan_term_years=20,
            loan_rate=0.06,
            opex_per_home_per_year_gbp=150.0,
            asset_life_years=25,
            own_use_rate_pence_per_kwh=12.0,
            retained_cash_floor_per_home_per_year_gbp=30.0,
            grid_services_income_per_kw_per_year_gbp=5.0,
        )
        assert fc.standing_charge_pence_per_day == 75.0
        assert fc.vat_rate == 0.20
        assert fc.retail_baseline_rate_pence_per_kwh == 28.0
        assert fc.self_consumption_override == 0.80
        assert fc.pv_cost_per_kwp_gbp == 900.0
        assert fc.roof_fit_cost_gbp == 1200.0
        assert fc.battery_cost_per_kwh_gbp == 300.0
        assert fc.inverter_cost_per_kw_gbp == 200.0
        assert fc.grant_gbp == 200000.0
        assert fc.equity_fraction == 0.60
        assert fc.loan_term_years == 20
        assert fc.loan_rate == 0.06
        assert fc.opex_per_home_per_year_gbp == 150.0
        assert fc.asset_life_years == 25
        assert fc.own_use_rate_pence_per_kwh == 12.0
        assert fc.retained_cash_floor_per_home_per_year_gbp == 30.0
        assert fc.grid_services_income_per_kw_per_year_gbp == 5.0


class TestFinanceConfigValidation:
    """Tests for FinanceConfig.__post_init__ validation (raises ConfigurationError)."""

    _BASE = dict(standing_charge_pence_per_day=60.0)

    # ---- vat_rate ----

    def test_vat_rate_too_high_raises(self) -> None:
        """vat_rate > 1 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, vat_rate=2.0)

    def test_vat_rate_negative_raises(self) -> None:
        """vat_rate < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, vat_rate=-0.1)

    def test_vat_rate_zero_ok(self) -> None:
        """vat_rate == 0 is valid (VAT-exempt scenario)."""
        fc = FinanceConfig(**self._BASE, vat_rate=0.0)
        assert fc.vat_rate == 0.0

    def test_vat_rate_one_ok(self) -> None:
        """vat_rate == 1 is valid (100% VAT, boundary)."""
        fc = FinanceConfig(**self._BASE, vat_rate=1.0)
        assert fc.vat_rate == 1.0

    # ---- equity_fraction ----

    def test_equity_fraction_too_high_raises(self) -> None:
        """equity_fraction > 1 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, equity_fraction=1.5)

    def test_equity_fraction_negative_raises(self) -> None:
        """equity_fraction < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, equity_fraction=-0.1)

    def test_equity_fraction_zero_ok(self) -> None:
        """equity_fraction == 0 is valid (fully debt-financed)."""
        fc = FinanceConfig(**self._BASE, equity_fraction=0.0)
        assert fc.equity_fraction == 0.0

    def test_equity_fraction_one_ok(self) -> None:
        """equity_fraction == 1 is valid (fully equity-financed)."""
        fc = FinanceConfig(**self._BASE, equity_fraction=1.0)
        assert fc.equity_fraction == 1.0

    # ---- self_consumption_override ----

    def test_self_consumption_override_zero_raises(self) -> None:
        """self_consumption_override == 0 raises ConfigurationError (must be > 0)."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, self_consumption_override=0.0)

    def test_self_consumption_override_too_high_raises(self) -> None:
        """self_consumption_override > 1 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, self_consumption_override=1.5)

    def test_self_consumption_override_one_ok(self) -> None:
        """self_consumption_override == 1 is valid (100% self-consumed)."""
        fc = FinanceConfig(**self._BASE, self_consumption_override=1.0)
        assert fc.self_consumption_override == 1.0

    def test_self_consumption_override_none_ok(self) -> None:
        """self_consumption_override == None skips override validation."""
        fc = FinanceConfig(**self._BASE, self_consumption_override=None)
        assert fc.self_consumption_override is None

    # ---- loan_term_years ----

    def test_loan_term_years_zero_raises(self) -> None:
        """loan_term_years == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, loan_term_years=0)

    def test_loan_term_years_negative_raises(self) -> None:
        """loan_term_years < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, loan_term_years=-1)

    # ---- loan_rate ----

    def test_loan_rate_negative_raises(self) -> None:
        """loan_rate < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, loan_rate=-0.01)

    def test_loan_rate_zero_ok(self) -> None:
        """loan_rate == 0 is valid (interest-free loan)."""
        fc = FinanceConfig(**self._BASE, loan_rate=0.0)
        assert fc.loan_rate == 0.0

    # ---- asset_life_years vs loan_term_years ----

    def test_asset_life_less_than_loan_term_raises(self) -> None:
        """asset_life_years < loan_term_years raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, asset_life_years=10, loan_term_years=15)

    def test_asset_life_equals_loan_term_ok(self) -> None:
        """asset_life_years == loan_term_years is valid (equality allowed)."""
        fc = FinanceConfig(**self._BASE, asset_life_years=15, loan_term_years=15)
        assert fc.asset_life_years == 15

    # ---- cost fields (must be > 0) ----

    def test_standing_charge_zero_raises(self) -> None:
        """standing_charge_pence_per_day == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(standing_charge_pence_per_day=0.0)

    def test_retail_baseline_rate_zero_raises(self) -> None:
        """retail_baseline_rate_pence_per_kwh == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, retail_baseline_rate_pence_per_kwh=0.0)

    def test_pv_cost_per_kwp_zero_raises(self) -> None:
        """pv_cost_per_kwp_gbp == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, pv_cost_per_kwp_gbp=0.0)

    def test_roof_fit_cost_negative_raises(self) -> None:
        """roof_fit_cost_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, roof_fit_cost_gbp=-1.0)

    def test_battery_cost_per_kwh_zero_raises(self) -> None:
        """battery_cost_per_kwh_gbp == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, battery_cost_per_kwh_gbp=0.0)

    def test_opex_per_home_per_year_negative_raises(self) -> None:
        """opex_per_home_per_year_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, opex_per_home_per_year_gbp=-1.0)

    # ---- grant_gbp (must be >= 0) ----

    def test_grant_negative_raises(self) -> None:
        """grant_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, grant_gbp=-1.0)

    def test_grant_zero_ok(self) -> None:
        """grant_gbp == 0 is valid (no grant received)."""
        fc = FinanceConfig(**self._BASE, grant_gbp=0.0)
        assert fc.grant_gbp == 0.0

    # ---- inverter_cost_per_kw_gbp (must be >= 0) ----

    def test_inverter_cost_negative_raises(self) -> None:
        """inverter_cost_per_kw_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, inverter_cost_per_kw_gbp=-5.0)

    def test_inverter_cost_zero_accepted(self) -> None:
        """inverter_cost_per_kw_gbp == 0.0 is valid (opt-in with zero default)."""
        fc = FinanceConfig(**self._BASE, inverter_cost_per_kw_gbp=0.0)
        assert fc.inverter_cost_per_kw_gbp == 0.0

    # ---- own_use_rate_pence_per_kwh (must be >= 0) ----

    def test_own_use_rate_negative_raises(self) -> None:
        """own_use_rate_pence_per_kwh < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, own_use_rate_pence_per_kwh=-1.0)

    def test_own_use_rate_zero_ok(self) -> None:
        """own_use_rate_pence_per_kwh == 0.0 is valid (zero transfer price allowed)."""
        fc = FinanceConfig(**self._BASE, own_use_rate_pence_per_kwh=0.0)
        assert fc.own_use_rate_pence_per_kwh == 0.0

    # ---- retained_cash_floor_per_home_per_year_gbp (must be >= 0) ----

    def test_retained_cash_floor_negative_raises(self) -> None:
        """retained_cash_floor_per_home_per_year_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, retained_cash_floor_per_home_per_year_gbp=-1.0)

    def test_retained_cash_floor_zero_ok(self) -> None:
        """retained_cash_floor_per_home_per_year_gbp == 0.0 is valid (no floor allowed)."""
        fc = FinanceConfig(**self._BASE, retained_cash_floor_per_home_per_year_gbp=0.0)
        assert fc.retained_cash_floor_per_home_per_year_gbp == 0.0

    # ---- grid_services_income_per_kw_per_year_gbp (must be >= 0) ----

    def test_grid_services_income_negative_raises(self) -> None:
        """grid_services_income_per_kw_per_year_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, grid_services_income_per_kw_per_year_gbp=-1.0)

    def test_grid_services_income_zero_ok(self) -> None:
        """grid_services_income_per_kw_per_year_gbp == 0.0 is valid (theta-safe default)."""
        fc = FinanceConfig(**self._BASE, grid_services_income_per_kw_per_year_gbp=0.0)
        assert fc.grid_services_income_per_kw_per_year_gbp == 0.0


class TestFinanceConfigParsing:
    """Tests for parse_finance_config parser function."""

    def test_none_returns_none(self) -> None:
        """parse_finance_config(None) returns None (no finance block in YAML)."""
        assert parse_finance_config(None) is None

    def test_minimal_dict_uses_defaults(self) -> None:
        """Dict with only standing_charge_pence_per_day uses all other defaults."""
        result = parse_finance_config({"standing_charge_pence_per_day": 60.0})
        assert result == FinanceConfig(standing_charge_pence_per_day=60.0)

    def test_full_dict_round_trips(self) -> None:
        """All fields supplied in the dict are reflected on the returned FinanceConfig."""
        data = {
            "standing_charge_pence_per_day": 70.0,
            "vat_rate": 0.08,
            "retail_baseline_rate_pence_per_kwh": 28.5,
            "self_consumption_override": 0.70,
            "pv_cost_per_kwp_gbp": 950.0,
            "roof_fit_cost_gbp": 1100.0,
            "battery_cost_per_kwh_gbp": 280.0,
            "inverter_cost_per_kw_gbp": 200.0,
            "grant_gbp": 200000.0,
            "equity_fraction": 0.60,
            "loan_term_years": 20,
            "loan_rate": 0.065,
            "opex_per_home_per_year_gbp": 140.0,
            "asset_life_years": 25,
            "own_use_rate_pence_per_kwh": 12.0,
            "retained_cash_floor_per_home_per_year_gbp": 30.0,
            "grid_services_income_per_kw_per_year_gbp": 5.0,
        }
        result = parse_finance_config(data)
        assert result is not None
        assert result.standing_charge_pence_per_day == 70.0
        assert result.vat_rate == 0.08
        assert result.retail_baseline_rate_pence_per_kwh == 28.5
        assert result.self_consumption_override == 0.70
        assert result.pv_cost_per_kwp_gbp == 950.0
        assert result.roof_fit_cost_gbp == 1100.0
        assert result.battery_cost_per_kwh_gbp == 280.0
        assert result.inverter_cost_per_kw_gbp == 200.0
        assert result.grant_gbp == 200000.0
        assert result.equity_fraction == 0.60
        assert result.loan_term_years == 20
        assert result.loan_rate == 0.065
        assert result.opex_per_home_per_year_gbp == 140.0
        assert result.asset_life_years == 25
        assert result.own_use_rate_pence_per_kwh == 12.0
        assert result.retained_cash_floor_per_home_per_year_gbp == 30.0
        assert result.grid_services_income_per_kw_per_year_gbp == 5.0

    def test_inverter_cost_omission_defaults_zero(self) -> None:
        """Parser with no inverter_cost_per_kw_gbp key returns 0.0 (acceptance guard)."""
        result = parse_finance_config({"standing_charge_pence_per_day": 60.0})
        assert result is not None
        assert result.inverter_cost_per_kw_gbp == 0.0

    def test_inverter_cost_key_round_trips(self) -> None:
        """inverter_cost_per_kw_gbp in dict is reflected on the returned FinanceConfig."""
        result = parse_finance_config(
            {"standing_charge_pence_per_day": 60.0, "inverter_cost_per_kw_gbp": 200.0}
        )
        assert result is not None
        assert result.inverter_cost_per_kw_gbp == 200.0

    def test_negative_inverter_cost_propagates_configuration_error(self) -> None:
        """negative inverter_cost_per_kw_gbp in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config(
                {"standing_charge_pence_per_day": 60.0, "inverter_cost_per_kw_gbp": -5.0}
            )

    def test_out_of_range_propagates_configuration_error(self) -> None:
        """An out-of-range field (vat_rate=2.0) raises ConfigurationError via __post_init__."""
        with pytest.raises(ConfigurationError):
            parse_finance_config(
                {"standing_charge_pence_per_day": 60.0, "vat_rate": 2.0}
            )

    def test_zero_grant_accepted(self) -> None:
        """grant_gbp=0 is accepted by the parser (non-negative allowed)."""
        result = parse_finance_config(
            {"standing_charge_pence_per_day": 60.0, "grant_gbp": 0.0}
        )
        assert result is not None
        assert result.grant_gbp == 0.0

    def test_missing_standing_charge_raises(self) -> None:
        """Finance block without standing_charge_pence_per_day raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="standing_charge_pence_per_day"):
            parse_finance_config({"vat_rate": 0.05})

    def test_int_coercion_of_year_fields(self) -> None:
        """loan_term_years/asset_life_years given as floats in the dict are coerced to int."""
        result = parse_finance_config(
            {
                "standing_charge_pence_per_day": 60.0,
                "loan_term_years": 20.0,
                "asset_life_years": 25.0,
            }
        )
        assert result is not None
        assert result.loan_term_years == 20
        assert isinstance(result.loan_term_years, int)
        assert result.asset_life_years == 25
        assert isinstance(result.asset_life_years, int)

    def test_non_numeric_value_raises_configuration_error(self) -> None:
        """A non-numeric string for a numeric field raises ConfigurationError (not ValueError)."""
        with pytest.raises(ConfigurationError, match="non-numeric"):
            parse_finance_config(
                {"standing_charge_pence_per_day": 60.0, "vat_rate": "not-a-number"}
            )

    def test_negative_own_use_rate_propagates_configuration_error(self) -> None:
        """negative own_use_rate_pence_per_kwh in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config(
                {"standing_charge_pence_per_day": 60.0, "own_use_rate_pence_per_kwh": -1.0}
            )

    def test_negative_retained_cash_floor_propagates_configuration_error(self) -> None:
        """negative retained_cash_floor_per_home_per_year_gbp in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config(
                {
                    "standing_charge_pence_per_day": 60.0,
                    "retained_cash_floor_per_home_per_year_gbp": -1.0,
                }
            )

    def test_negative_grid_services_income_propagates_configuration_error(self) -> None:
        """negative grid_services_income_per_kw_per_year_gbp in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config(
                {
                    "standing_charge_pence_per_day": 60.0,
                    "grid_services_income_per_kw_per_year_gbp": -1.0,
                }
            )


class TestScenarioFinance:
    """Tests for ScenarioConfig.finance field and _parse_scenario wiring."""

    _MINIMAL_PERIOD = {
        "start_date": "2024-01-01",
        "end_date": "2024-01-07",
    }
    _MINIMAL_HOME = {
        "pv": {"capacity_kw": 4.0},
        "load": {"annual_consumption_kwh": 3400},
    }

    def test_scenario_config_finance_defaults_to_none(self) -> None:
        """ScenarioConfig.finance is None when not provided (constructed directly)."""
        home = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
        )
        sc = ScenarioConfig(
            name="test",
            period=SimulationPeriod(**self._MINIMAL_PERIOD),
            home=home,
        )
        assert sc.finance is None

    def test_load_scenarios_with_finance_block_populates_field(self, tmp_path: Path) -> None:
        """YAML with a top-level finance: block → scenarios[0].finance is FinanceConfig."""
        yaml_content = (
            "name: Finance Test\n"
            "period:\n"
            "  start_date: '2024-01-01'\n"
            "  end_date: '2024-01-07'\n"
            "home:\n"
            "  pv:\n"
            "    capacity_kw: 4.0\n"
            "  load:\n"
            "    annual_consumption_kwh: 3400\n"
            "finance:\n"
            "  standing_charge_pence_per_day: 65.0\n"
            "  vat_rate: 0.08\n"
            "  self_consumption_override: 0.75\n"
        )
        path = tmp_path / "scenario.yaml"
        path.write_text(yaml_content)

        scenarios = load_scenarios(path)
        assert len(scenarios) == 1
        assert scenarios[0].finance == FinanceConfig(
            standing_charge_pence_per_day=65.0,
            vat_rate=0.08,
            self_consumption_override=0.75,
        )

    def test_load_scenarios_without_finance_block_is_none(self, tmp_path: Path) -> None:
        """YAML without a finance: block → scenarios[0].finance is None."""
        yaml_content = (
            "name: No Finance Test\n"
            "period:\n"
            "  start_date: '2024-01-01'\n"
            "  end_date: '2024-01-07'\n"
            "home:\n"
            "  pv:\n"
            "    capacity_kw: 4.0\n"
            "  load:\n"
            "    annual_consumption_kwh: 3400\n"
        )
        path = tmp_path / "scenario.yaml"
        path.write_text(yaml_content)

        scenarios = load_scenarios(path)
        assert len(scenarios) == 1
        assert scenarios[0].finance is None

    def test_load_scenarios_with_cost_recovery_fields_round_trip(self, tmp_path: Path) -> None:
        """YAML finance: block with the three cost-recovery keys round-trips into FinanceConfig."""
        yaml_content = (
            "name: Cost Recovery Test\n"
            "period:\n"
            "  start_date: '2024-01-01'\n"
            "  end_date: '2024-01-07'\n"
            "home:\n"
            "  pv:\n"
            "    capacity_kw: 4.0\n"
            "  load:\n"
            "    annual_consumption_kwh: 3400\n"
            "finance:\n"
            "  standing_charge_pence_per_day: 65.0\n"
            "  own_use_rate_pence_per_kwh: 12.5\n"
            "  retained_cash_floor_per_home_per_year_gbp: 30.0\n"
            "  grid_services_income_per_kw_per_year_gbp: 8.0\n"
        )
        path = tmp_path / "scenario.yaml"
        path.write_text(yaml_content)

        scenarios = load_scenarios(path)
        assert len(scenarios) == 1
        assert scenarios[0].finance == FinanceConfig(
            standing_charge_pence_per_day=65.0,
            own_use_rate_pence_per_kwh=12.5,
            retained_cash_floor_per_home_per_year_gbp=30.0,
            grid_services_income_per_kw_per_year_gbp=8.0,
        )


class TestFinanceConfigGridServicesModel:
    """FinanceConfig.grid_services_model + grid_services_events fields."""

    _BASE: dict = {"standing_charge_pence_per_day": 60.0}

    def test_default_grid_services_model_is_flat(self) -> None:
        """Default grid_services_model is 'flat'."""
        fc = FinanceConfig(**self._BASE)
        assert fc.grid_services_model == "flat"

    def test_default_grid_services_events_is_none(self) -> None:
        """Default grid_services_events is None."""
        fc = FinanceConfig(**self._BASE)
        assert fc.grid_services_events is None

    def test_all_pre_existing_defaults_unchanged(self) -> None:
        """Adding new fields does not disturb any pre-existing FinanceConfig defaults."""
        fc = FinanceConfig(**self._BASE)
        assert fc.vat_rate == 0.05
        assert fc.retail_baseline_rate_pence_per_kwh == 23.0
        assert fc.self_consumption_override is None
        assert fc.pv_cost_per_kwp_gbp == 1000.0
        assert fc.grid_services_income_per_kw_per_year_gbp == 0.0

    def test_frozen_with_new_fields(self) -> None:
        """FinanceConfig is still frozen after adding new fields."""
        fc = FinanceConfig(**self._BASE)
        with pytest.raises(dataclasses.FrozenInstanceError):
            fc.grid_services_model = "capacity_at_events"  # type: ignore[misc]

    def test_picklable_with_new_fields(self) -> None:
        """FinanceConfig is picklable when grid_services_events is None."""
        fc = FinanceConfig(**self._BASE)
        assert pickle.loads(pickle.dumps(fc)) == fc

    def test_capacity_at_events_model_with_config(self) -> None:
        """Constructing with grid_services_model='capacity_at_events' + GridServicesEventsConfig round-trips."""
        events_cfg = GridServicesEventsConfig()
        fc = FinanceConfig(
            **self._BASE,
            grid_services_model="capacity_at_events",
            grid_services_events=events_cfg,
        )
        assert fc.grid_services_model == "capacity_at_events"
        assert fc.grid_services_events == events_cfg
        assert pickle.loads(pickle.dumps(fc)) == fc

    def test_unknown_grid_services_model_raises(self) -> None:
        """Unknown grid_services_model raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, grid_services_model="foo")

    def test_capacity_at_events_without_config_ok(self) -> None:
        """grid_services_model='capacity_at_events' with grid_services_events=None still constructs."""
        fc = FinanceConfig(**self._BASE, grid_services_model="capacity_at_events")
        assert fc.grid_services_model == "capacity_at_events"
        assert fc.grid_services_events is None


class TestFinanceConfigParsingGridServices:
    """Tests for parse_finance_config with grid_services_model + grid_services_events."""

    _BASE = {"standing_charge_pence_per_day": 60.0}

    def test_omitting_model_defaults_flat(self) -> None:
        """Finance dict omitting grid_services_model yields 'flat' + None events."""
        result = parse_finance_config(self._BASE)
        assert result is not None
        assert result.grid_services_model == "flat"
        assert result.grid_services_events is None

    def test_capacity_at_events_with_nested_events_block(self) -> None:
        """grid_services_model='capacity_at_events' + events block parses fully."""
        data = {
            **self._BASE,
            "grid_services_model": "capacity_at_events",
            "grid_services_events": {
                "band": "high",
                "aggregator_share": 0.1,
                "utilisation_factor": 0.8,
                "availability_gbp_per_kw_per_event": 2.5,
                "utilisation_gbp_per_mwh": 80.0,
                "event_windows": [
                    {
                        "months": [11, 12, 1, 2],
                        "weekdays": [0, 1, 2, 3, 4],
                        "hours": [16, 17, 18],
                        "events_per_year": 12,
                        "event_hours": 3.0,
                    }
                ],
            },
        }
        result = parse_finance_config(data)
        assert result is not None
        assert result.grid_services_model == "capacity_at_events"
        assert isinstance(result.grid_services_events, GridServicesEventsConfig)
        cfg = result.grid_services_events
        assert cfg.band == "high"
        assert cfg.aggregator_share == 0.1
        assert cfg.utilisation_factor == 0.8
        assert cfg.availability_gbp_per_kw_per_event == 2.5
        assert cfg.utilisation_gbp_per_mwh == 80.0
        assert len(cfg.event_windows) == 1
        ew = cfg.event_windows[0]
        assert isinstance(ew, EventWindow)
        assert set(ew.months) == {11, 12, 1, 2}
        assert set(ew.weekdays) == {0, 1, 2, 3, 4}
        assert set(ew.hours) == {16, 17, 18}
        assert ew.events_per_year == 12
        assert ew.event_hours == 3.0

    def test_unknown_model_raises_configuration_error(self) -> None:
        """Unknown grid_services_model in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config({**self._BASE, "grid_services_model": "unknown"})

    def test_nested_negative_override_raises(self) -> None:
        """Negative availability override in nested block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "central",
                    "aggregator_share": 0.25,
                    "utilisation_factor": 0.6,
                    "availability_gbp_per_kw_per_event": -1.0,
                    "event_windows": [
                        {"months": [12], "weekdays": [0], "hours": [17],
                         "events_per_year": 1, "event_hours": 1.0}
                    ],
                },
            })

    def test_nested_aggregator_share_one_raises(self) -> None:
        """aggregator_share=1 in nested block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "central",
                    "aggregator_share": 1.0,
                    "utilisation_factor": 0.6,
                    "event_windows": [
                        {"months": [12], "weekdays": [0], "hours": [17],
                         "events_per_year": 1, "event_hours": 1.0}
                    ],
                },
            })

    def test_nested_empty_event_windows_raises(self) -> None:
        """Empty event_windows list in nested block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "central",
                    "aggregator_share": 0.25,
                    "utilisation_factor": 0.6,
                    "event_windows": [],
                },
            })

    def test_nested_unknown_band_raises(self) -> None:
        """Unknown band in nested block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "extreme",
                    "aggregator_share": 0.25,
                    "utilisation_factor": 0.6,
                    "event_windows": [
                        {"months": [12], "weekdays": [0], "hours": [17],
                         "events_per_year": 1, "event_hours": 1.0}
                    ],
                },
            })

    # ---- Robustness: malformed nested values ----

    def test_non_dict_grid_services_events_raises(self) -> None:
        """grid_services_events as a string (not a dict) raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="mapping"):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": "central",  # wrong type
            })

    def test_non_numeric_event_hours_raises(self) -> None:
        """event_hours='abc' (non-numeric string) raises ConfigurationError, not raw ValueError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "central",
                    "aggregator_share": 0.25,
                    "utilisation_factor": 0.6,
                    "event_windows": [
                        {"months": [12], "weekdays": [0], "hours": [17],
                         "events_per_year": 1, "event_hours": "abc"},
                    ],
                },
            })

    def test_missing_required_event_window_key_raises(self) -> None:
        """event_window dict missing a required key raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="requires 'hours'"):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "central",
                    "aggregator_share": 0.25,
                    "utilisation_factor": 0.6,
                    "event_windows": [
                        # 'hours' key intentionally omitted
                        {"months": [12], "weekdays": [0],
                         "events_per_year": 1, "event_hours": 1.0},
                    ],
                },
            })

    def test_non_dict_event_window_entry_raises(self) -> None:
        """A non-dict entry in event_windows list raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="mapping"):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "central",
                    "aggregator_share": 0.25,
                    "utilisation_factor": 0.6,
                    "event_windows": ["not-a-dict"],  # list entry is a string
                },
            })
