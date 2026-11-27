# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.form_choices, the typed-block choices a dashboard page's form offers, as it shows, starts and reads them."""

from typing import Any

import pytest

pytest.importorskip("flask")

from solar_challenge.errors import ConfigurationError
from solar_challenge.number_fields import Interval
from solar_challenge.web.fleet_components import page_limits
from solar_challenge.web.form_choices import FormChoice, FormSetting, SettingInput, flat_rate_choice


def _peak_rate(value: Any, path: str) -> Any:
    return ("peak", value, path)


def _off_peak_rate(value: Any, path: str) -> Any:
    return ("off-peak", value, path)


_TWO_RATES = FormChoice(
    "two_rates",
    "Two Rates",
    (
        FormSetting("peak_rate", "Peak", Interval(0, 2), 0.01, 0.3, _peak_rate),
        FormSetting("windows", "Windows", Interval(0, 24), 1, ((1, 2),), _off_peak_rate, SettingInput.CLOCK_OR_WINDOW),
    ),
)


class TestFormChoice:
    def test_its_held_type_is_its_type_and_each_settings_reader_by_its_key_in_its_order(self) -> None:
        held = _TWO_RATES.held_type()

        assert held.type == "two_rates"
        assert list(held.settings.items()) == [("peak_rate", _peak_rate), ("windows", _off_peak_rate)]

    def test_its_starting_block_is_its_type_under_the_type_key_and_each_settings_start(self) -> None:
        assert _TWO_RATES.starting_block("type") == {"type": "two_rates", "peak_rate": 0.3, "windows": ((1, 2),)}

    def test_its_json_is_its_type_and_each_settings_key_input_and_start_with_each_tuple_a_list(self) -> None:
        assert _TWO_RATES.as_json() == {
            "type": "two_rates",
            "settings": [
                {"key": "peak_rate", "input": "number", "start": 0.3},
                {"key": "windows", "input": "clock_or_window", "start": [[1, 2]]},
            ],
        }


@pytest.mark.parametrize("page", ["fleet page", "builder"])
class TestFlatRateChoice:
    def test_its_rate_starts_at_the_flat_rate_start(self, page: str) -> None:
        assert flat_rate_choice(page).starting_block("type") == {
            "type": "flat_rate",
            "rate_per_kwh": page_limits().flat_rate_start,
        }

    def test_its_rate_left_out_is_refused_naming_its_path_and_the_page(self, page: str) -> None:
        read_rate = flat_rate_choice(page).held_type().settings["rate_per_kwh"]

        with pytest.raises(ConfigurationError) as refusal:
            read_rate(None, "tariff.rate_per_kwh")

        assert str(refusal.value) == f"tariff.rate_per_kwh must be set: the {page} always sets it"
