# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the finance: block and the FinanceConfig it parses into."""

import dataclasses
import itertools
import math
import pickle
import re
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pytest

from solar_challenge.config import (
    ScenarioConfig,
    load_config,
    load_scenarios,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import FinanceConfig
from solar_challenge.gridservices import (
    DEFAULT_EVENT_WINDOWS,
    EventWindow,
    FlatGridServices,
    GridServicesBand,
    GridServicesEventsConfig,
    GridServicesModel,
    NoGridServices,
)
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_blocks import parse_finance_config
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow
from tests._construction_refusals import construction_refusal, prefixed_construction_refusal
from tests._repository_paths import SCENARIOS_DIR
from tests._unusable_numbers import UNUSABLE_NUMBERS

_YEAR_FIELDS = ("loan_term_years", "asset_life_years")
_FLOAT_FIELDS = tuple(
    f.name
    for f in dataclasses.fields(FinanceConfig)
    if f.name not in {*_YEAR_FIELDS, "grid_services_model"}
)
_NUMERIC_FIELDS = tuple(
    f.name
    for f in dataclasses.fields(FinanceConfig)
    if f.name in {*_FLOAT_FIELDS, *_YEAR_FIELDS}
)
_TOO_LARGE_FOR_A_FLOAT = 10**400


def _finance_refusal(block: dict[str, object]) -> str:
    """The refusal parse_finance_config gives *block*: FinanceConfig's own, prefixed by the block's path, "finance"."""
    return prefixed_construction_refusal("finance", lambda: FinanceConfig(**block))


class TestFinanceConfig:
    """Tests for FinanceConfig dataclass construction, defaults, immutability, and pickling."""

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
        "grid_services_model": NoGridServices(),
    }

    def test_construction_with_required_arg(self) -> None:
        """FinanceConfig can be constructed with only standing_charge_pence_per_day."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.standing_charge_pence_per_day == 60.0

    def test_whole_number_amounts_are_held_as_the_floats_they_read(self) -> None:
        fc = FinanceConfig(standing_charge_pence_per_day=60, grant_gbp=250000)
        assert fc.standing_charge_pence_per_day == 60.0
        assert type(fc.standing_charge_pence_per_day) is float
        assert fc.grant_gbp == 250000.0
        assert type(fc.grant_gbp) is float

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
        """Every FinanceConfig field that declares a default has a row in _DECLARED_DEFAULTS."""
        optional_fields = {
            f.name
            for f in dataclasses.fields(FinanceConfig)
            if f.default is not dataclasses.MISSING
            or f.default_factory is not dataclasses.MISSING
        }
        assert set(self._DECLARED_DEFAULTS) == optional_fields, (
            "every FinanceConfig field that declares a default needs a row in "
            "_DECLARED_DEFAULTS, and every row must name such a field"
        )

    def test_frozen_raises_on_assignment(self) -> None:
        """FinanceConfig is frozen: attribute assignment raises FrozenInstanceError."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            fc.vat_rate = 0.20  # type: ignore[misc]

    def test_default_config_round_trips_through_pickle(self) -> None:
        """A FinanceConfig given only the standing charge survives a pickle round-trip equal to the original."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert pickle.loads(pickle.dumps(fc)) == fc

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
            grid_services_model=FlatGridServices(5.0),
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
        assert fc.grid_services_model == FlatGridServices(5.0)


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

    # ---- year counts (whole numbers) ----

    @pytest.mark.parametrize("field", _YEAR_FIELDS)
    @pytest.mark.parametrize(
        ("value", "requirement"),
        [
            pytest.param(20.5, "a whole number", id="fraction"),
            pytest.param(True, "a finite number", id="bool"),
            pytest.param(np.True_, "a finite number", id="numpy-bool"),
        ],
    )
    def test_a_year_count_that_is_not_a_whole_number_is_refused(
        self, field: str, value: object, requirement: str
    ) -> None:
        """A fractional or boolean year count is refused, naming the field and the value."""
        with pytest.raises(ConfigurationError) as exc_info:
            FinanceConfig(**self._BASE, **{field: value})
        assert str(exc_info.value) == f"{field} must be {requirement}, got {value!r}"

    @pytest.mark.parametrize("field", _YEAR_FIELDS)
    @pytest.mark.parametrize(
        "value", [pytest.param(20.0, id="float"), pytest.param(np.int64(20), id="numpy-int64")]
    )
    def test_a_whole_number_year_count_of_another_numeric_type_is_held_as_an_int(
        self, field: str, value: object
    ) -> None:
        """A whole-number float or numpy integer year count is held as the int it equals."""
        config = FinanceConfig(**self._BASE, **{field: value})

        assert getattr(config, field) == 20
        assert type(getattr(config, field)) is int

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

    # ---- every number (finite) ----

    @pytest.mark.parametrize("field", _NUMERIC_FIELDS)
    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(math.nan, id="nan"),
            pytest.param(math.inf, id="inf"),
            pytest.param(-math.inf, id="-inf"),
        ],
    )
    def test_a_number_that_is_not_finite_is_refused_naming_its_field(
        self, field: str, value: float
    ) -> None:
        """A NaN or infinite value for any numeric field is refused, naming the field and the value."""
        with pytest.raises(
            ConfigurationError,
            match=rf"^{re.escape(field)} must be .+, got {re.escape(str(value))}$",
        ):
            FinanceConfig(**{**self._BASE, field: value})

    @pytest.mark.parametrize("field", _NUMERIC_FIELDS)
    @pytest.mark.parametrize("value", [*UNUSABLE_NUMBERS, pytest.param("x", id="word")])
    def test_a_number_that_is_not_a_finite_number_is_refused_naming_it(
        self, field: str, value: object
    ) -> None:
        """A NaN, an infinity, an int too large for a float, a bool or a word is refused by name, before any range is checked."""
        with pytest.raises(ConfigurationError) as exc_info:
            FinanceConfig(**{**self._BASE, field: value})
        assert str(exc_info.value) == f"{field} must be a finite number, got {value!r}"

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            pytest.param(
                "standing_charge_pence_per_day",
                0.0,
                "standing_charge_pence_per_day must be greater than 0, got 0.0",
                id="standing-charge-zero",
            ),
            pytest.param("vat_rate", 2.0, "vat_rate must be between 0 and 1, got 2.0", id="vat-above-1"),
            pytest.param(
                "self_consumption_override",
                0.0,
                "self_consumption_override must be greater than 0 and at most 1, got 0.0",
                id="override-zero",
            ),
            pytest.param(
                "equity_fraction",
                1.5,
                "equity_fraction must be between 0 and 1, got 1.5",
                id="equity-above-1",
            ),
            pytest.param(
                "loan_term_years", 0, "loan_term_years must be greater than 0, got 0", id="loan-term-zero"
            ),
            pytest.param("grant_gbp", -1.0, "grant_gbp must be at least 0, got -1.0", id="grant-negative"),
        ],
    )
    def test_a_number_outside_its_range_is_refused_naming_the_range(
        self, field: str, value: float, message: str
    ) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            FinanceConfig(**{**self._BASE, field: value})
        assert str(exc_info.value) == message


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
            "grid_services_model": {"type": "flat", "income_per_kw_per_year_gbp": 5.0},
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
        assert result.grid_services_model == FlatGridServices(5.0)

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
        """Finance block without standing_charge_pence_per_day is refused, naming the block at its path."""
        with pytest.raises(ConfigurationError) as refusal:
            parse_finance_config({"vat_rate": 0.05})
        with pytest.raises(ConfigurationError) as refusal_in_a_scenario:
            parse_finance_config({"vat_rate": 0.05}, block_path="scenarios[0].finance")

        assert str(refusal.value) == "finance: requires 'standing_charge_pence_per_day'"
        assert str(refusal_in_a_scenario.value) == "scenarios[0].finance: requires 'standing_charge_pence_per_day'"

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

    def test_a_word_for_a_numeric_field_is_refused_as_finance_config_refuses_it(self) -> None:
        """A word for a numeric field is refused as FinanceConfig refuses it, prefixed by the block's path."""
        block: dict[str, object] = {"standing_charge_pence_per_day": 60.0, "vat_rate": "not-a-number"}

        assert construction_refusal(lambda: parse_finance_config(block)) == _finance_refusal(block)

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

    @pytest.mark.parametrize(
        "key",
        [k for k in (*_FLOAT_FIELDS, *_YEAR_FIELDS) if k != "self_consumption_override"],
    )
    def test_null_numeric_value_raises_configuration_error(self, key: str) -> None:
        """A null for a numeric key is refused as FinanceConfig refuses it, not read as the field's default."""
        block: dict[str, object] = {"standing_charge_pence_per_day": 60.0, key: None}

        assert construction_refusal(lambda: parse_finance_config(block)) == _finance_refusal(block)

    @pytest.mark.parametrize("key", _FLOAT_FIELDS)
    def test_fractional_value_reaches_float_field(self, key: str) -> None:
        """A fractional value set for a float key reaches FinanceConfig unchanged."""
        block = {"standing_charge_pence_per_day": 60.0, key: 0.5}
        assert parse_finance_config(block) == FinanceConfig(**block)

    def test_null_self_consumption_override_parses_to_no_override(self) -> None:
        """A null self_consumption_override parses to a FinanceConfig with no override."""
        assert parse_finance_config(
            {"standing_charge_pence_per_day": 60.0, "self_consumption_override": None}
        ) == FinanceConfig(standing_charge_pence_per_day=60.0)

    @pytest.mark.parametrize(("first", "second"), list(itertools.pairwise(_NUMERIC_FIELDS)))
    def test_first_declared_of_two_non_numeric_values_is_reported(
        self, first: str, second: str
    ) -> None:
        """Of two non-numeric values, the error names the field FinanceConfig declares first.

        The block lists the later-declared field first, so the block's key order cannot decide it.
        """
        block: dict[str, object] = {
            second: f"not-a-number:{second}",
            first: f"not-a-number:{first}",
        }
        block.setdefault("standing_charge_pence_per_day", 60.0)
        with pytest.raises(ConfigurationError, match=f"'not-a-number:{first}'"):
            parse_finance_config(block)

    @pytest.mark.parametrize("key", _NUMERIC_FIELDS)
    @pytest.mark.parametrize("value", [True, False])
    def test_a_boolean_numeric_value_is_refused(self, key: str, value: bool) -> None:
        """A boolean for a numeric key is refused as FinanceConfig refuses it, not read as 1.0 or 0.0."""
        block: dict[str, object] = {"standing_charge_pence_per_day": 60.0, key: value}

        assert construction_refusal(lambda: parse_finance_config(block)) == _finance_refusal(block)

    @pytest.mark.parametrize("field", _YEAR_FIELDS)
    def test_a_fractional_year_count_is_refused_not_truncated(self, field: str) -> None:
        """A fractional year count reaches FinanceConfig, which refuses it, rather than being truncated to a whole year."""
        with pytest.raises(
            ConfigurationError, match=re.escape(f"{field} must be a whole number, got 20.7")
        ):
            parse_finance_config({"standing_charge_pence_per_day": 60.0, field: 20.7})

    @pytest.mark.parametrize("key", _NUMERIC_FIELDS)
    def test_a_number_too_large_for_a_float_is_refused_as_a_configuration_error(
        self, key: str
    ) -> None:
        """An integer too large for a float, as YAML can hold, is refused as FinanceConfig refuses it, prefixed by the block's path, not as a raw OverflowError."""
        block: dict[str, object] = {"standing_charge_pence_per_day": 60.0, key: _TOO_LARGE_FOR_A_FLOAT}

        assert construction_refusal(lambda: parse_finance_config(block)) == _finance_refusal(block)


class TestScenarioFinance:
    """Tests for ScenarioConfig.finance field and parse_scenario wiring."""

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
            period=SimulationWindow(date(2024, 1, 1), date(2024, 1, 7), ONE_MINUTE, "Europe/London"),
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
            "  grid_services_model:\n"
            "    type: flat\n"
            "    income_per_kw_per_year_gbp: 8.0\n"
        )
        path = tmp_path / "scenario.yaml"
        path.write_text(yaml_content)

        scenarios = load_scenarios(path)
        assert len(scenarios) == 1
        assert scenarios[0].finance == FinanceConfig(
            standing_charge_pence_per_day=65.0,
            own_use_rate_pence_per_kwh=12.5,
            retained_cash_floor_per_home_per_year_gbp=30.0,
            grid_services_model=FlatGridServices(8.0),
        )

    def test_load_scenarios_refuses_a_nan_finance_cost_naming_its_key(self, tmp_path: Path) -> None:
        """A YAML .nan finance cost is refused, naming its key and the value, rather than read as NaN."""
        yaml_content = (
            "name: NaN Cost Test\n"
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
            "  pv_cost_per_kwp_gbp: .nan\n"
        )
        path = tmp_path / "scenario.yaml"
        path.write_text(yaml_content)

        with pytest.raises(
            ConfigurationError,
            match=re.escape("pv_cost_per_kwp_gbp must be a finite number, got nan"),
        ):
            load_scenarios(path)


_SCENARIO_FINANCE_BASE: dict[str, object] = {
    "standing_charge_pence_per_day": 60.0,
    "own_use_rate_pence_per_kwh": 15.0,
    "retained_cash_floor_per_home_per_year_gbp": 27.0,
}

_RETIRED_FINANCE_KEYS = ("grid_services_income_per_kw_per_year_gbp", "grid_services_events")


class TestCommittedScenarioFinance:
    """The committed scenario files name their pricing once, in grid_services_model, and keep the FinanceConfig they meant before (C11)."""

    @pytest.mark.parametrize(
        ("file_name", "pricing"),
        [
            pytest.param("bristol-phase1.yaml", NoGridServices(), id="bristol-phase1"),
            pytest.param(
                "bristol-phase1-flex.yaml",
                GridServicesEventsConfig(
                    band=GridServicesBand.CENTRAL,
                    aggregator_share=0.25,
                    utilisation_factor=0.6,
                    event_windows=DEFAULT_EVENT_WINDOWS,
                ),
                id="bristol-phase1-flex",
            ),
        ],
    )
    def test_the_finance_block_parses_to_the_finance_it_meant(self, file_name: str, pricing: GridServicesModel) -> None:
        finance = parse_finance_config(load_config(SCENARIOS_DIR / file_name)["finance"])

        assert finance == FinanceConfig(**_SCENARIO_FINANCE_BASE, grid_services_model=pricing)  # type: ignore[arg-type]

    @pytest.mark.parametrize("file_name", ["bristol-phase1.yaml", "bristol-phase1-flex.yaml"])
    def test_the_finance_block_holds_no_retired_key(self, file_name: str) -> None:
        block = load_config(SCENARIOS_DIR / file_name)["finance"]

        assert [key for key in _RETIRED_FINANCE_KEYS if key in block] == []

    def test_the_flex_finance_block_names_the_capacity_at_events_type(self) -> None:
        block = load_config(SCENARIOS_DIR / "bristol-phase1-flex.yaml")["finance"]

        assert block["grid_services_model"]["type"] == "capacity_at_events"


class TestFinanceGridServicesModelBlock:
    """parse_finance_config reads one grid_services_model block tagged by type, and refuses the retired forms naming the form to write."""

    _BASE: dict[str, object] = {"standing_charge_pence_per_day": 60.0}

    def _parse(self, model: object, *, block_path: str = "finance") -> Optional[FinanceConfig]:
        return parse_finance_config({**self._BASE, "grid_services_model": model}, block_path=block_path)

    def _refusal(self, model: object, *, block_path: str = "finance") -> str:
        with pytest.raises(ConfigurationError) as refusal:
            self._parse(model, block_path=block_path)
        return str(refusal.value)

    def test_an_absent_block_is_no_grid_services(self) -> None:
        assert parse_finance_config(dict(self._BASE)) == FinanceConfig(
            standing_charge_pence_per_day=60.0, grid_services_model=NoGridServices()
        )

    def test_a_null_block_is_no_grid_services(self) -> None:
        assert self._parse(None) == FinanceConfig(standing_charge_pence_per_day=60.0, grid_services_model=NoGridServices())

    def test_a_flat_block_is_the_flat_pricing_at_its_rate(self) -> None:
        assert self._parse({"type": "flat", "income_per_kw_per_year_gbp": 12.0}) == FinanceConfig(
            standing_charge_pence_per_day=60.0, grid_services_model=FlatGridServices(12.0)
        )

    def test_a_flat_block_without_its_rate_is_refused_naming_the_missing_key(self) -> None:
        assert self._refusal({"type": "flat"}) == "finance.grid_services_model: requires 'income_per_kw_per_year_gbp'"

    @pytest.mark.parametrize("rate", [0, 0.0, -1.0])
    def test_a_flat_rate_flat_grid_services_refuses_is_refused_as_it_refuses_it(self, rate: float) -> None:
        """Zero income is NoGridServices, so a zero flat rate is refused as FlatGridServices refuses it, not read as none."""
        assert construction_refusal(
            lambda: self._parse({"type": "flat", "income_per_kw_per_year_gbp": rate})
        ) == prefixed_construction_refusal("finance.grid_services_model", lambda: FlatGridServices(rate))

    def test_a_band_in_a_flat_block_is_refused_as_an_unrecognised_key(self) -> None:
        """A flat block states its rate; it does not resolve one through the rate table (PRD §12 tactical Q2)."""
        message = self._refusal({"type": "flat", "income_per_kw_per_year_gbp": 12.0, "band": "central"})

        assert message.startswith("finance.grid_services_model: unrecognised keys 'band'"), message

    def test_an_events_block_is_the_events_pricing(self) -> None:
        assert self._parse({"type": "capacity_at_events", "band": "high"}) == FinanceConfig(
            standing_charge_pence_per_day=60.0, grid_services_model=GridServicesEventsConfig(band=GridServicesBand.HIGH)
        )

    @pytest.mark.parametrize(
        "model",
        [
            pytest.param({"type": "none"}, id="none"),
            pytest.param({"type": 5}, id="not-a-name"),
        ],
    )
    def test_an_unknown_type_is_refused_naming_the_supported_types_and_the_omission_that_means_none(
        self, model: dict[str, object]
    ) -> None:
        """No grid services is written by omitting the block, so no type names it (PRD §12 tactical Q1), and the refusal of a guess such as type: none says so."""
        message = self._refusal(model)

        assert message.startswith("finance.grid_services_model.type: "), message
        assert repr(model["type"]) in message
        assert "flat" in message
        assert "capacity_at_events" in message
        assert message.endswith("; omit finance.grid_services_model for no grid services"), message

    def test_a_block_without_a_type_is_refused_naming_the_type(self) -> None:
        assert self._refusal({}) == "finance.grid_services_model: requires 'type'"

    @pytest.mark.parametrize("model", [pytest.param(5, id="number"), pytest.param(["flat"], id="list")])
    def test_a_block_that_is_no_mapping_is_refused_naming_its_path(self, model: object) -> None:
        assert self._refusal(model) == f"finance.grid_services_model: must be a mapping, got {type(model).__name__}"

    @pytest.mark.parametrize(
        ("selector", "form"),
        [("flat", "type: flat"), ("capacity_at_events", "type: capacity_at_events")],
    )
    def test_a_retired_string_selector_is_refused_naming_the_form_to_write(self, selector: str, form: str) -> None:
        message = self._refusal(selector)

        assert message.startswith("finance.grid_services_model: "), message
        assert form in message
        assert "omit it for no grid services" in message

    @pytest.mark.parametrize(
        ("key", "value", "form"),
        [
            pytest.param("grid_services_income_per_kw_per_year_gbp", 12.0, "type: flat", id="flat-rate"),
            pytest.param("grid_services_income_per_kw_per_year_gbp", 0.0, "type: flat", id="zero-flat-rate"),
            pytest.param("grid_services_income_per_kw_per_year_gbp", None, "type: flat", id="null-flat-rate"),
            pytest.param("grid_services_events", {"band": "central"}, "type: capacity_at_events", id="events"),
            pytest.param("grid_services_events", None, "type: capacity_at_events", id="null-events"),
        ],
    )
    def test_a_retired_key_is_refused_naming_the_block_and_the_form_to_write(
        self, key: str, value: object, form: str
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            parse_finance_config({**self._BASE, key: value})

        message = str(refusal.value)
        assert message.startswith(f"finance.{key}: "), message
        assert "finance.grid_services_model" in message
        assert form in message

    def test_the_flex_files_retired_finance_block_is_refused_on_its_first_retired_key(self) -> None:
        """The flex scenario's finance block as it was written before grid_services_model held the pricing."""
        legacy_block = {
            **_SCENARIO_FINANCE_BASE,
            "grid_services_model": "capacity_at_events",
            "grid_services_events": {
                "band": "central",
                "aggregator_share": 0.25,
                "utilisation_factor": 0.6,
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

        with pytest.raises(ConfigurationError) as refusal:
            parse_finance_config(legacy_block)

        message = str(refusal.value)
        assert "finance.grid_services_model" in message
        assert "type: capacity_at_events" in message

    @pytest.mark.parametrize("block_path", ["finance", "scenarios[0].finance", "scenario.finance"])
    def test_a_refusal_names_the_grid_services_model_of_the_block_at_its_own_path(self, block_path: str) -> None:
        with pytest.raises(ConfigurationError) as retired_key:
            parse_finance_config({**self._BASE, "grid_services_events": None}, block_path=block_path)

        assert f"{block_path}.grid_services_model" in str(retired_key.value)
        assert self._refusal("flat", block_path=block_path).startswith(f"{block_path}.grid_services_model: ")
        assert self._refusal({"type": "none"}, block_path=block_path).startswith(
            f"{block_path}.grid_services_model.type: "
        )


_EVENTS_NUMERIC_KEYS = tuple(
    f.name
    for f in dataclasses.fields(GridServicesEventsConfig)
    if f.name not in {"band", "event_windows", "delivery_baseline"}
)


class TestFinanceConfigParsingGridServices:
    """Tests for parse_finance_config with a grid_services_model block of type capacity_at_events."""

    _BASE = {"standing_charge_pence_per_day": 60.0}
    _WINDOW: dict[str, object] = {
        "months": [12],
        "weekdays": [0],
        "hours": [17],
        "events_per_year": 1,
        "event_hours": 1.0,
    }
    _EVENTS_BLOCK: dict[str, object] = {
        "band": "high",
        "event_windows": [_WINDOW],
        "aggregator_share": 0.1,
        "utilisation_factor": 0.8,
        "availability_gbp_per_kw_per_event": 2.5,
        "utilisation_gbp_per_mwh": 80.0,
        "delivery_baseline": "capacity",
    }
    _EVENTS_FIELDS: dict[str, object] = {
        **_EVENTS_BLOCK,
        "event_windows": (
            EventWindow(months=(12,), weekdays=(0,), hours=(17,), events_per_year=1, event_hours=1.0),
        ),
    }

    def _parse_events_block(
        self, block: dict[str, object], *, block_path: str = "finance"
    ) -> Optional[FinanceConfig]:
        return parse_finance_config(
            {**self._BASE, "grid_services_model": {"type": "capacity_at_events", **block}},
            block_path=block_path,
        )

    def _events_refusal(self, key: str, value: object) -> str:
        """The refusal of _EVENTS_BLOCK with *key* set to *value*: GridServicesEventsConfig's own, prefixed by the block's path."""
        return prefixed_construction_refusal(
            "finance.grid_services_model",
            lambda: GridServicesEventsConfig(**{**self._EVENTS_FIELDS, key: value}),
        )

    def _window_refusal(self, window_values: dict[str, object]) -> str:
        """The refusal of _WINDOW with *window_values* set, as the events block's one window: EventWindow's own, prefixed by the window's path."""
        return prefixed_construction_refusal(
            "finance.grid_services_model.event_windows[0]",
            lambda: EventWindow(**{**self._WINDOW, **window_values}),
        )

    def test_capacity_at_events_block_parses_fully(self) -> None:
        """A capacity_at_events block with every key parses to the GridServicesEventsConfig it describes."""
        result = self._parse_events_block(
            {
                "band": "high",
                "aggregator_share": 0.1,
                "utilisation_factor": 0.8,
                "availability_gbp_per_kw_per_event": 2.5,
                "utilisation_gbp_per_mwh": 80.0,
                "delivery_baseline": "capacity",
                "event_windows": [
                    {
                        "months": [11, 12, 1, 2],
                        "weekdays": [0, 1, 2, 3, 4],
                        "hours": [16, 17, 18],
                        "events_per_year": 12,
                        "event_hours": 3.0,
                    }
                ],
            }
        )
        assert result is not None
        assert isinstance(result.grid_services_model, GridServicesEventsConfig)
        cfg = result.grid_services_model
        assert cfg.band is GridServicesBand.HIGH
        assert cfg.aggregator_share == 0.1
        assert cfg.utilisation_factor == 0.8
        assert cfg.availability_gbp_per_kw_per_event == 2.5
        assert cfg.utilisation_gbp_per_mwh == 80.0
        assert cfg.delivery_baseline == "capacity"
        assert len(cfg.event_windows) == 1
        ew = cfg.event_windows[0]
        assert isinstance(ew, EventWindow)
        assert set(ew.months) == {11, 12, 1, 2}
        assert set(ew.weekdays) == {0, 1, 2, 3, 4}
        assert set(ew.hours) == {16, 17, 18}
        assert ew.events_per_year == 12
        assert ew.event_hours == 3.0

    def test_nested_negative_override_raises(self) -> None:
        """Negative availability override in the events block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            self._parse_events_block({**self._EVENTS_BLOCK, "availability_gbp_per_kw_per_event": -1.0})

    def test_nested_aggregator_share_one_raises(self) -> None:
        """aggregator_share=1 in the events block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            self._parse_events_block({**self._EVENTS_BLOCK, "aggregator_share": 1.0})

    def test_nested_empty_event_windows_raises(self) -> None:
        """Empty event_windows list in the events block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            self._parse_events_block({**self._EVENTS_BLOCK, "event_windows": []})

    def test_nested_unknown_band_raises(self) -> None:
        """Unknown band in the events block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            self._parse_events_block({**self._EVENTS_BLOCK, "band": "extreme"})

    # ---- Robustness: malformed nested values ----

    def test_non_numeric_event_hours_raises(self) -> None:
        """event_hours='abc' (non-numeric string) raises ConfigurationError, not raw ValueError."""
        with pytest.raises(ConfigurationError):
            self._parse_events_block(
                {**self._EVENTS_BLOCK, "event_windows": [{**self._WINDOW, "event_hours": "abc"}]}
            )

    def test_missing_required_event_window_key_raises(self) -> None:
        """event_window dict missing a required key raises ConfigurationError."""
        window = {key: value for key, value in self._WINDOW.items() if key != "hours"}
        with pytest.raises(
            ConfigurationError, match=re.escape("finance.grid_services_model.event_windows[0]: requires 'hours'")
        ):
            self._parse_events_block({**self._EVENTS_BLOCK, "event_windows": [window]})

    def test_non_dict_event_window_entry_raises(self) -> None:
        """A non-dict entry in event_windows list raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="mapping"):
            self._parse_events_block({**self._EVENTS_BLOCK, "event_windows": ["not-a-dict"]})

    @pytest.mark.parametrize("key", ["band", "aggregator_share", "utilisation_factor", "delivery_baseline"])
    def test_null_events_value_is_refused(self, key: str) -> None:
        """A null for an events key whose declared default is not None is refused as GridServicesEventsConfig refuses it, not read as that default."""
        assert construction_refusal(
            lambda: self._parse_events_block({**self._EVENTS_BLOCK, key: None})
        ) == self._events_refusal(key, None)

    def test_null_event_windows_is_refused_as_not_a_list(self) -> None:
        """A null event_windows is refused as not a list of windows, not read as the default schedule."""
        with pytest.raises(
            ConfigurationError,
            match=re.escape("finance.grid_services_model.event_windows: must be a list, got NoneType"),
        ):
            self._parse_events_block({**self._EVENTS_BLOCK, "event_windows": None})

    def test_an_unknown_delivery_baseline_is_refused_naming_both_values(self) -> None:
        """An unknown delivery_baseline is refused by the events configuration's own check."""
        with pytest.raises(ConfigurationError) as exc_info:
            self._parse_events_block({**self._EVENTS_BLOCK, "delivery_baseline": "metered"})

        assert (
            "GridServicesEventsConfig.delivery_baseline must be one of operational, capacity, got 'metered'"
            in str(exc_info.value)
        )

    @pytest.mark.parametrize(
        "key", ["availability_gbp_per_kw_per_event", "utilisation_gbp_per_mwh"]
    )
    def test_null_rate_override_parses_to_no_override(self, key: str) -> None:
        """A null rate override parses to a GridServicesEventsConfig with no override."""
        assert self._parse_events_block({**self._EVENTS_BLOCK, key: None}) == FinanceConfig(
            **self._BASE,
            grid_services_model=GridServicesEventsConfig(**{**self._EVENTS_FIELDS, key: None}),  # type: ignore[arg-type]
        )

    @pytest.mark.parametrize(
        "band",
        [pytest.param(["high"], id="list"), pytest.param({"name": "high"}, id="mapping")],
    )
    def test_unhashable_band_is_refused_as_an_unknown_band(self, band: object) -> None:
        """A list or mapping band, as malformed YAML can give, is refused by the events configuration's own band check."""
        with pytest.raises(ConfigurationError, match="band must be one of"):
            self._parse_events_block({**self._EVENTS_BLOCK, "band": band})

    @pytest.mark.parametrize(
        ("first", "second"), list(itertools.pairwise(_EVENTS_NUMERIC_KEYS))
    )
    def test_first_declared_of_two_non_numeric_events_values_is_reported(
        self, first: str, second: str
    ) -> None:
        """Of two non-numeric events values, the error names the field GridServicesEventsConfig declares first.

        The block lists the later-declared field first, so the block's key order cannot decide it.
        """
        block = {
            second: f"not-a-number:{second}",
            first: f"not-a-number:{first}",
            "event_windows": [self._WINDOW],
        }
        with pytest.raises(ConfigurationError, match=f"'not-a-number:{first}'"):
            self._parse_events_block(block)

    def test_malformed_event_window_is_reported_before_a_non_numeric_events_value(self) -> None:
        """A malformed event window is reported before a non-numeric scalar of the events block."""
        block = {
            "aggregator_share": "not-a-number:aggregator_share",
            "event_windows": [{**self._WINDOW, "event_hours": "not-a-number:event_hours"}],
        }
        with pytest.raises(ConfigurationError, match="'not-a-number:event_hours'"):
            self._parse_events_block(block)

    @pytest.mark.parametrize(
        ("windows", "message"),
        [
            pytest.param(
                "winter",
                "scenario.finance.grid_services_model.event_windows: must be a list, got str",
                id="not-a-list",
            ),
            pytest.param(
                {"months": [12]},
                "scenario.finance.grid_services_model.event_windows: must be a list, got dict",
                id="a-mapping",
            ),
            pytest.param(
                [{"months": [12], "weekdays": [0], "events_per_year": 1, "event_hours": 1.0}],
                "scenario.finance.grid_services_model.event_windows[0]: requires 'hours'",
                id="missing-key",
            ),
        ],
    )
    def test_malformed_event_windows_are_refused_naming_their_path_in_the_file(
        self, windows: object, message: str
    ) -> None:
        """An event_windows refusal names the list's path, taken from the finance block's own path."""
        with pytest.raises(ConfigurationError, match=re.escape(message)):
            self._parse_events_block({"event_windows": windows}, block_path="scenario.finance")

    def test_a_window_its_type_refuses_is_refused_prefixed_by_its_path_in_the_file(self) -> None:
        """A window EventWindow refuses is refused as it refuses it, prefixed by the window's path, taken from the finance block's own path."""
        window = {**self._WINDOW, "event_hours": "abc"}

        assert construction_refusal(
            lambda: self._parse_events_block({"event_windows": [window]}, block_path="scenario.finance")
        ) == prefixed_construction_refusal(
            "scenario.finance.grid_services_model.event_windows[0]", lambda: EventWindow(**window)
        )

    @pytest.mark.parametrize("omitted", list(_EVENTS_BLOCK))
    def test_omitted_events_key_takes_its_declared_default(self, omitted: str) -> None:
        """A key the capacity_at_events block omits takes GridServicesEventsConfig's declared default.

        An omitted event_windows is the default schedule, DEFAULT_EVENT_WINDOWS, not an error.
        """
        block = {key: value for key, value in self._EVENTS_BLOCK.items() if key != omitted}
        fields = {key: value for key, value in self._EVENTS_FIELDS.items() if key != omitted}
        assert self._parse_events_block(block) == FinanceConfig(
            **self._BASE,
            grid_services_model=GridServicesEventsConfig(**fields),  # type: ignore[arg-type]
        )

    def test_a_block_naming_only_its_type_parses_to_the_declared_defaults(self) -> None:
        """A capacity_at_events block that sets no other key is the default events config, where an absent block is no grid services."""
        assert self._parse_events_block({}) == FinanceConfig(
            **self._BASE,
            grid_services_model=GridServicesEventsConfig(),
        )

    @pytest.mark.parametrize("key", _EVENTS_NUMERIC_KEYS)
    @pytest.mark.parametrize("value", [True, False])
    def test_a_boolean_events_value_is_refused(self, key: str, value: bool) -> None:
        """A boolean for a numeric events key is refused as GridServicesEventsConfig refuses it, not read as 1.0 or 0.0."""
        assert construction_refusal(
            lambda: self._parse_events_block({**self._EVENTS_BLOCK, key: value})
        ) == self._events_refusal(key, value)

    @pytest.mark.parametrize("value", [True, False])
    def test_a_boolean_event_hours_is_refused(self, value: bool) -> None:
        """A boolean event_hours is refused as EventWindow refuses it, not read as 1.0 or 0.0."""
        assert construction_refusal(
            lambda: self._parse_events_block(
                {**self._EVENTS_BLOCK, "event_windows": [{**self._WINDOW, "event_hours": value}]}
            )
        ) == self._window_refusal({"event_hours": value})

    @pytest.mark.parametrize("key", _EVENTS_NUMERIC_KEYS)
    def test_an_events_value_too_large_for_a_float_is_refused_as_a_configuration_error(
        self, key: str
    ) -> None:
        """An events value too large for a float is refused as GridServicesEventsConfig refuses it, prefixed by the block's path, not as a raw OverflowError."""
        assert construction_refusal(
            lambda: self._parse_events_block({**self._EVENTS_BLOCK, key: _TOO_LARGE_FOR_A_FLOAT})
        ) == self._events_refusal(key, _TOO_LARGE_FOR_A_FLOAT)

    @pytest.mark.parametrize(
        "window_values",
        [
            pytest.param({"event_hours": _TOO_LARGE_FOR_A_FLOAT}, id="event_hours-too-large-for-a-float"),
            pytest.param({"events_per_year": math.inf}, id="infinite-events_per_year"),
            pytest.param({"hours": [math.inf]}, id="infinite-hour"),
        ],
    )
    def test_an_event_window_number_too_large_for_its_type_is_refused_as_a_configuration_error(
        self, window_values: dict[str, object]
    ) -> None:
        """An event-window number too large for its type is refused as EventWindow refuses it, prefixed by the window's path, not as a raw OverflowError."""
        assert construction_refusal(
            lambda: self._parse_events_block(
                {**self._EVENTS_BLOCK, "event_windows": [{**self._WINDOW, **window_values}]}
            )
        ) == self._window_refusal(window_values)
