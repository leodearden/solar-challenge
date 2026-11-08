# SPDX-License-Identifier: AGPL-3.0-or-later
"""The refusal of a fleet whose proportional_to names a source not drawn earlier for every home that draws it, as the fleet tests expect it.

A fleet's proportional_to may scale only a number or count field that every home drawing the
dependent drew before it. The refusal names the dependent's path, its source and, in draw
order, the sources it may name.

Usage::

    from tests._proportional_source_refusals import proportional_source_refusal

    with pytest.raises(ConfigurationError) as refusal:
        parse_fleet_distribution_config(fleet)
    assert str(refusal.value) == proportional_source_refusal(
        "fleet_distribution.battery.capacity_kwh", "pv.capacity", ["pv.capacity_kw"]
    )
"""


def proportional_source_refusal(path: str, source: str, sources: list[str]) -> str:
    """The refusal of *source*, the source of the proportional_to at *path*, where *sources*, in draw order, are those it may name."""
    return (
        f"Invalid {path} source {source!r}; valid sources: a number or count field drawn earlier "
        f"for every home that draws it, one of {sources!r}"
    )
