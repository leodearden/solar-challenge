# SPDX-License-Identifier: AGPL-3.0-or-later
"""A read's outcome, as tests compare two reads of one rule: the type and value it returns, or the type and message of the ConfigurationError it raises.

Two readers that share a rule, such as a field read under a named interval and the public
helper that reads under it, are then compared value by value: the same value of the same
type, or a refusal with the same message. The comparison does not depend on which values the
rule admits, so it holds when the rule changes and both readers change with it, and fails
when only one of them does.

Usage::

    from tests._read_outcomes import outcome_of

    @pytest.mark.parametrize("value", [-0.1, 0, 1e-9, 5, "5", 1e9])
    def test_battery_kwh_is_read_as_battery_reads_a_capacity_setting(value: object) -> None:
        assert outcome_of(
            lambda: ConfigPoint(pv_kwp=4.0, battery_kwh=value, inverter_kw=3.68).battery_kwh
        ) == outcome_of(lambda: require_valid_capacity_setting(value, "battery_kwh"))
"""

from collections.abc import Callable

from solar_challenge.errors import ConfigurationError


def outcome_of(read: Callable[[], object]) -> tuple[type, object]:
    """The type and value *read* returns, or the type and message of the ConfigurationError it raises."""
    try:
        value = read()
    except ConfigurationError as refusal:
        return type(refusal), str(refusal)
    return type(value), value
