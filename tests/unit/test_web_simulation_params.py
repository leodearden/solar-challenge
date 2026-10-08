"""Tests for solar_challenge.web.simulation_params, called directly with parameter dicts."""

import re
from collections.abc import Callable
from operator import attrgetter

import pytest
pytest.importorskip("flask")

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import ConfigurationError
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.seg import SEG_PRESETS, SEGTariff
from solar_challenge.web.shared import NotAJsonObject
from solar_challenge.web.simulation_params import (
    MAX_WINDOW_DAYS,
    parse_date_range,
    parse_home_config,
    parse_seg_tariff,
    with_default_days,
)
from tests._unusable_numbers import UNUSABLE_NUMBERS


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

    def test_days_max_window_days_is_the_longest_window(self) -> None:
        """days=MAX_WINDOW_DAYS is the longest window, a year of days from 2024-06-01."""
        assert parse_date_range({"days": MAX_WINDOW_DAYS}) == ("2024-06-01", "2025-06-01")

    def test_full_leap_year_is_the_longest_start_end_window(self) -> None:
        """The full 2024 leap year, 366 days, is the longest start/end window, and is accepted."""
        assert parse_date_range({"start": "2024-01-01", "end": "2024-12-31"}) == (
            "2024-01-01",
            "2024-12-31",
        )

    def test_single_day_window_is_accepted(self) -> None:
        """A start/end window that starts and ends on the same day is accepted."""
        assert parse_date_range({"start": "2024-06-01", "end": "2024-06-01"}) == (
            "2024-06-01",
            "2024-06-01",
        )

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            pytest.param(
                {"start": "2024-06-02", "end": "2024-06-01"},
                "end must not be before start, got start '2024-06-02' and end '2024-06-01'",
                id="one-day-reversed",
            ),
            pytest.param(
                {"end": "2023-12-31"},
                "end must not be before start, got start '2024-01-01' and end '2023-12-31'",
                id="end-before-the-default-start",
            ),
            pytest.param(
                {"start": "2024-01-01", "end": "2025-01-01"},
                f"start to end must span at most {MAX_WINDOW_DAYS} days, "
                "got start '2024-01-01' and end '2025-01-01', 367 days",
                id="one-day-past-the-longest-window",
            ),
        ],
    )
    def test_window_it_cannot_run_is_refused_naming_start_and_end(
        self, data: dict, message: str
    ) -> None:
        """A window that ends before it starts, or spans more than MAX_WINDOW_DAYS days, is refused with a ValueError naming start and end as read."""
        with pytest.raises(ValueError) as exc_info:
            parse_date_range(data)
        assert str(exc_info.value) == message

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            pytest.param(
                {"days": 7, "start": "2024-01-01", "end": "2024-03-31"},
                "days must not be sent with start or end, "
                "got days 7 with start '2024-01-01' and end '2024-03-31'",
                id="days-with-start-and-end",
            ),
            pytest.param(
                {"days": 7, "start": "2024-03-01"},
                "days must not be sent with start or end, got days 7 with start '2024-03-01'",
                id="days-with-start",
            ),
            pytest.param(
                {"days": 365, "end": "2024-03-31"},
                "days must not be sent with start or end, got days 365 with end '2024-03-31'",
                id="full-year-days-with-end",
            ),
        ],
    )
    def test_days_sent_with_start_or_end_is_refused_naming_each_value_sent(
        self, data: dict, message: str
    ) -> None:
        """A body that sets its window by days and by a start or end is refused with a ValueError naming days and each date as sent."""
        with pytest.raises(ValueError) as exc_info:
            parse_date_range(data)
        assert str(exc_info.value) == message

    @pytest.mark.parametrize(
        ("data", "window"),
        [
            pytest.param(
                {"days": None, "start": "2024-03-01", "end": "2024-03-05"},
                ("2024-03-01", "2024-03-05"),
                id="null-days-with-start-and-end",
            ),
            pytest.param(
                {"days": 7, "start": "", "end": ""},
                ("2024-06-01", "2024-06-07"),
                id="days-with-empty-start-and-end",
            ),
            pytest.param(
                {"days": 7, "start": None, "end": None},
                ("2024-06-01", "2024-06-07"),
                id="days-with-null-start-and-end",
            ),
        ],
    )
    def test_null_days_and_empty_or_null_start_and_end_read_as_not_sent(
        self, data: dict, window: tuple[str, str]
    ) -> None:
        """A null days, and an empty or null start or end, read as not sent, so the body runs the window it does send."""
        assert parse_date_range(data) == window

    @pytest.mark.parametrize(
        ("days", "message"),
        [
            pytest.param(float("inf"), "days must be an integer, got inf", id="infinity"),
            pytest.param(
                float("-inf"), "days must be an integer, got -inf", id="negative-infinity"
            ),
            pytest.param(float("nan"), "days must be an integer, got nan", id="nan"),
            pytest.param("seven", "days must be an integer, got 'seven'", id="non-numeric-string"),
            pytest.param(0, f"days must be between 1 and {MAX_WINDOW_DAYS}, got 0", id="zero"),
            pytest.param(
                -7, f"days must be between 1 and {MAX_WINDOW_DAYS}, got -7", id="negative"
            ),
            pytest.param(
                MAX_WINDOW_DAYS + 1,
                f"days must be between 1 and {MAX_WINDOW_DAYS}, got {MAX_WINDOW_DAYS + 1}",
                id="one-past-the-longest-window",
            ),
            pytest.param(
                200000,
                f"days must be between 1 and {MAX_WINDOW_DAYS}, got 200000",
                id="past-pandas-timedelta-range",
            ),
            pytest.param(
                1e300, f"days must be between 1 and {MAX_WINDOW_DAYS}, got 1e+300", id="huge-float"
            ),
        ],
    )
    def test_days_it_cannot_use_is_refused_naming_days_and_the_value_sent(
        self, days: object, message: str
    ) -> None:
        """A days that int() cannot read, or one outside 1 to MAX_WINDOW_DAYS, is refused with a ValueError naming days and the value as sent."""
        with pytest.raises(ValueError) as exc_info:
            parse_date_range({"days": days})
        assert str(exc_info.value) == message

    @pytest.mark.parametrize("field", ["start", "end"])
    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("2024/06/01", id="slashes"),
            pytest.param("2024-06-01T12:00", id="time-of-day"),
            pytest.param("2024-02-30", id="no-such-day"),
            pytest.param("NaT", id="pandas-not-a-time"),
            pytest.param(20240601, id="number"),
            pytest.param(0, id="zero"),
            pytest.param(False, id="false"),
            pytest.param([], id="empty-array"),
        ],
    )
    def test_date_it_cannot_read_is_refused_naming_the_field_and_the_value_sent(
        self, field: str, value: object
    ) -> None:
        """A start or end that is not an ISO 8601 date is refused with a ValueError naming the field and the value as sent."""
        with pytest.raises(ValueError) as exc_info:
            parse_date_range({field: value})
        assert str(exc_info.value) == f"{field} must be an ISO 8601 date (YYYY-MM-DD), got {value!r}"


class TestWithDefaultDays:
    """with_default_days adds a consumer's default days only to a body that sends no window, as parse_date_range reads one."""

    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            pytest.param({}, {"days": 7}, id="nothing"),
            pytest.param({"pv_kw": 4.0}, {"pv_kw": 4.0, "days": 7}, id="other-keys-only"),
            pytest.param({"days": None}, {"days": 7}, id="null-days"),
            pytest.param({"start": None}, {"start": None, "days": 7}, id="null-start"),
            pytest.param({"end": ""}, {"end": "", "days": 7}, id="empty-end"),
            pytest.param(
                {"start": "", "end": None},
                {"start": "", "end": None, "days": 7},
                id="empty-and-null-dates",
            ),
        ],
    )
    def test_a_body_that_sends_no_window_gets_the_default_days(
        self, data: dict, expected: dict
    ) -> None:
        """A body parse_date_range reads as sending no window, as it reads {}, gets the default days, and the body itself is unchanged."""
        sent = dict(data)
        assert parse_date_range(data) == parse_date_range({})
        assert with_default_days(data, 7) == expected
        assert data == sent

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param({"days": 30}, id="days"),
            pytest.param({"days": ""}, id="empty-days"),
            pytest.param({"start": "2024-03-01"}, id="start"),
            pytest.param({"end": "2024-03-05"}, id="end"),
            pytest.param(
                {"days": None, "start": "2024-03-01", "end": "2024-03-05"},
                id="null-days-with-start-and-end",
            ),
            pytest.param({"days": 30, "start": "2024-03-01"}, id="days-with-start"),
            pytest.param({"start": False}, id="false-start"),
        ],
    )
    def test_a_body_that_sends_a_window_is_returned_as_sent(self, data: dict) -> None:
        """A body that sends a days, or a start or end, is returned as sent, so parse_date_range reads or refuses the window it sends, never the default days."""
        assert with_default_days(data, 7) == data


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

    def test_valid_dispatch_strategy_without_battery_makes_no_battery(self) -> None:
        """A valid dispatch_strategy makes no battery when there is none."""
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
NESTED_BLOCK_FIELDS: dict[str, Callable[[HomeConfig], object]] = {
    "heat_pump": attrgetter("heat_pump_config"),
    "seg": attrgetter("seg_tariff"),
    "tariff": attrgetter("tariff_config"),
    "dispatch_strategy": attrgetter("battery_config.dispatch_strategy"),
}


class TestParseHomeConfigNestedBlockPresence:
    """One presence rule for the four nested blocks: null means none; any other value must be a mapping its grammar reads.

    The rule governs all four blocks whatever battery_kwh is.
    """

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


# One value each battery-setting reader refuses; each grammar's full refusal matrix is tested where that grammar lives.
MALFORMED_BATTERY_SETTINGS = [
    pytest.param("dispatch_strategy", "", id="dispatch_strategy-empty-string"),
    pytest.param(
        "dispatch_strategy", {"strategy_type": "bogus"}, id="dispatch_strategy-unknown-type"
    ),
    pytest.param("efficiency_pct", 150, id="efficiency_pct-above-100"),
    pytest.param("max_charge_kw", "abc", id="max_charge_kw-not-a-number"),
    pytest.param("max_charge_kw", -1, id="max_charge_kw-negative"),
    pytest.param("max_discharge_kw", float("nan"), id="max_discharge_kw-nan"),
]


class TestParseHomeConfigBatterySettings:
    """max_charge_kw, max_discharge_kw, efficiency_pct and dispatch_strategy are read whatever battery_kwh is, and applied only to a battery."""

    @pytest.mark.parametrize(("key", "value"), MALFORMED_BATTERY_SETTINGS)
    def test_setting_a_battery_refuses_is_refused_without_one(
        self, key: str, value: object
    ) -> None:
        """A battery setting refused with a battery is refused, with the same message, without one."""
        with pytest.raises(ValueError) as with_battery:
            parse_home_config({**VALID_HOME_PAYLOAD, key: value})
        with pytest.raises(ValueError) as without_battery:
            parse_home_config({**VALID_HOME_PAYLOAD, "battery_kwh": 0, key: value})
        assert str(without_battery.value) == str(with_battery.value)

    def test_settings_without_a_battery_make_no_battery(self) -> None:
        """Valid battery settings sent without a battery are accepted, and make no battery."""
        home_config, _start, _end, _name = parse_home_config(
            {**FORM_PAYLOAD_BATTERY_ON, "battery_kwh": 0}
        )
        assert home_config.battery_config is None

    def test_power_limits_reach_their_own_battery_fields(self) -> None:
        """With a battery, max_charge_kw and max_discharge_kw each set their own BatteryConfig field."""
        home_config, _start, _end, _name = parse_home_config(
            {**VALID_HOME_PAYLOAD, "max_charge_kw": 3.0, "max_discharge_kw": 4.0}
        )
        assert home_config.battery_config == BatteryConfig(
            capacity_kwh=VALID_HOME_PAYLOAD["battery_kwh"], max_charge_kw=3.0, max_discharge_kw=4.0
        )

    def test_null_settings_leave_the_battery_defaults(self) -> None:
        """A null battery setting, like an absent one, is unset, leaving BatteryConfig's default."""
        home_config, _start, _end, _name = parse_home_config(
            {
                **VALID_HOME_PAYLOAD,
                "max_charge_kw": None,
                "max_discharge_kw": None,
                "efficiency_pct": None,
                "dispatch_strategy": None,
            }
        )
        assert home_config.battery_config == BatteryConfig(
            capacity_kwh=VALID_HOME_PAYLOAD["battery_kwh"]
        )


class TestParseHomeConfigNumberFields:
    """Each number field parse_home_config reads is refused, naming the field and the value sent, when it is not a number the field can hold."""

    @pytest.mark.parametrize("value", UNUSABLE_NUMBERS)
    @pytest.mark.parametrize(
        "field",
        [
            "pv_kw",
            "azimuth",
            "tilt",
            "system_age_years",
            "degradation_rate_per_year",
            "battery_kwh",
            "max_charge_kw",
            "max_discharge_kw",
            "efficiency_pct",
            "consumption_kwh",
        ],
    )
    def test_top_level_field_that_is_not_a_finite_number_is_refused_naming_it(
        self, field: str, value: object
    ) -> None:
        """A top-level float field holding a number too large for a float, an infinity, NaN or a boolean is refused naming the field."""
        with pytest.raises(ValueError) as exc_info:
            parse_home_config({**VALID_HOME_PAYLOAD, field: value})
        assert str(exc_info.value) == f"{field} must be a finite number, got {value!r}"

    @pytest.mark.parametrize("value", UNUSABLE_NUMBERS)
    @pytest.mark.parametrize("key", ["thermal_capacity_kw", "annual_heat_demand_kwh"])
    def test_heat_pump_field_that_is_not_a_finite_number_is_refused_naming_it_in_its_block(
        self, key: str, value: object
    ) -> None:
        """A heat_pump number too large for a float, an infinity, NaN or a boolean is refused naming it as heat_pump.<key>."""
        with pytest.raises(ValueError) as exc_info:
            parse_home_config({**VALID_HOME_PAYLOAD, "heat_pump": {key: value}})
        assert str(exc_info.value) == f"heat_pump.{key} must be a finite number, got {value!r}"

    @pytest.mark.parametrize(
        "value",
        [pytest.param(float("inf"), id="infinity"), pytest.param(float("nan"), id="nan")],
    )
    def test_occupants_int_cannot_read_is_refused_naming_it(self, value: float) -> None:
        """An occupants value int() cannot read is refused naming occupants and the value sent."""
        with pytest.raises(ValueError) as exc_info:
            parse_home_config({**VALID_HOME_PAYLOAD, "occupants": value})
        assert str(exc_info.value) == f"occupants must be an integer, got {value!r}"


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
