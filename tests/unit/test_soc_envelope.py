# SPDX-License-Identifier: AGPL-3.0-or-later
"""The SOH-derated SOC envelope, read without building a Battery: docs/prds/dispatch-configuration-below-config.md §9 row 11.

The PRD's §5.4 δ bullet specifies it: battery.SocEnvelope holds a battery's effective capacity and its SOC limits
within it, in kWh, and its target_kwh(fraction) holds γ's cap, so a target above the ceiling is the ceiling.
"""

import dataclasses
import math
import re

import pytest
from solar_challenge.battery import SocEnvelope
from solar_challenge.errors import ConfigurationError

_ROW_11_ENVELOPE = SocEnvelope(effective_capacity_kwh=7.0, min_soc_kwh=1.4, max_soc_kwh=5.6)
"""Row 11's envelope built directly: a 10 kWh battery at SOH 0.7 with SOC limits of 0.2 and 0.8."""


class TestSocEnvelope:
    """A SocEnvelope built directly holds an effective capacity and the SOC limits within it, and caps a target at its ceiling."""

    def test_a_target_is_its_fraction_of_the_effective_capacity(self) -> None:
        assert _ROW_11_ENVELOPE.target_kwh(0.5) == pytest.approx(3.5)

    def test_a_target_at_the_ceiling_is_the_ceiling(self) -> None:
        assert _ROW_11_ENVELOPE.target_kwh(0.8) == pytest.approx(5.6)

    def test_a_target_above_the_ceiling_is_the_ceiling(self) -> None:
        assert _ROW_11_ENVELOPE.target_kwh(0.95) == _ROW_11_ENVELOPE.max_soc_kwh == 5.6

    def test_a_field_cannot_be_assigned(self) -> None:
        envelope = SocEnvelope(effective_capacity_kwh=7.0, min_soc_kwh=1.4, max_soc_kwh=5.6)
        with pytest.raises(dataclasses.FrozenInstanceError):
            envelope.max_soc_kwh = 6.0

    def test_whole_numbers_are_held_as_the_floats_they_equal(self) -> None:
        envelope = SocEnvelope(10, 1, 9)
        assert dataclasses.astuple(envelope) == (10.0, 1.0, 9.0)
        assert [type(value) for value in dataclasses.astuple(envelope)] == [float, float, float]

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("effective_capacity_kwh", 0.0),
            ("effective_capacity_kwh", math.nan),
            ("min_soc_kwh", -0.1),
            ("min_soc_kwh", math.inf),
            ("max_soc_kwh", math.nan),
        ],
    )
    def test_a_field_that_is_not_a_finite_number_in_its_range_is_refused_naming_it_and_the_value(
        self, field: str, value: float
    ) -> None:
        with pytest.raises(ConfigurationError, match=f"{re.escape(field)}.*{re.escape(repr(value))}"):
            dataclasses.replace(_ROW_11_ENVELOPE, **{field: value})

    @pytest.mark.parametrize(
        ("min_soc_kwh", "max_soc_kwh"),
        [
            pytest.param(6.0, 5.6, id="min-above-max"),
            pytest.param(1.4, 7.5, id="max-above-the-effective-capacity"),
        ],
    )
    def test_limits_out_of_order_are_refused_naming_all_three_values(
        self, min_soc_kwh: float, max_soc_kwh: float
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            SocEnvelope(effective_capacity_kwh=7.0, min_soc_kwh=min_soc_kwh, max_soc_kwh=max_soc_kwh)
        named = (("effective_capacity_kwh", 7.0), ("min_soc_kwh", min_soc_kwh), ("max_soc_kwh", max_soc_kwh))
        for field, value in named:
            assert f"{field}={value!r}" in str(refusal.value)

    @pytest.mark.parametrize(
        ("min_soc_kwh", "max_soc_kwh"),
        [
            pytest.param(5.6, 5.6, id="min-at-max"),
            pytest.param(1.4, 7.0, id="max-at-the-effective-capacity"),
            pytest.param(0.0, 5.6, id="min-at-zero"),
        ],
    )
    def test_limits_at_their_bounds_are_accepted(self, min_soc_kwh: float, max_soc_kwh: float) -> None:
        """The order is not strict: two SOC fractions a Battery admits can round to the same kWh."""
        envelope = SocEnvelope(effective_capacity_kwh=7.0, min_soc_kwh=min_soc_kwh, max_soc_kwh=max_soc_kwh)
        assert (envelope.min_soc_kwh, envelope.max_soc_kwh) == (min_soc_kwh, max_soc_kwh)
