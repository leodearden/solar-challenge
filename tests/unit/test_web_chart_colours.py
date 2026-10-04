# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that charts.py's COLOUR_PALETTE is the one home of the chart
colours, so a palette edit reaches every copy of a chart colour.

The charts take their colours from COLOUR_PALETTE as strings, which Plotly needs. Three
checks enforce the invariant:

* No dashboard source writes out a palette colour: not tailwind.config.js, not a
  template, not the hand-written stylesheet and not a script. A colour counts as written
  where its hex literal appears in a source, matched case-insensitively anywhere,
  comments included, so an eight-digit #rrggbbaa copy counts through its prefix. Not
  read: the compiled dist/style.css, which derives from the templates and the theme, and
  rgb() or rgba() forms in those sources.
* Every palette colour a chart builder draws follows a palette edit: with each palette
  entry recoloured, no builder's figure still draws a shipped palette colour as #rrggbb,
  rgb() or rgba(), so a translucent fill or a reused hue that charts.py writes out by hand
  fails. A colour that no palette entry has, such as the transparent backgrounds, is not
  flagged. Plotly's default template, which no builder chooses, is not read.
* Every palette colour is written #rrggbb, the form charts.py derives translucent colours
  from. charts.py refuses any other form only when it draws a chart that needs one; this
  check refuses it for the whole palette.
"""

import dataclasses
import json
import re
from collections.abc import Callable, Iterator

import pandas as pd
import pytest

pytest.importorskip("jinja2")
pytest.importorskip("plotly")
from solar_challenge.home import SimulationResults
from solar_challenge.web import charts
from solar_challenge.web.charts import COLOUR_PALETTE
from tests._dashboard_sources import (
    HAND_WRITTEN_STYLESHEET_KEY,
    TAILWIND_CONFIG_KEY,
    dashboard_script_sources,
    dashboard_template_sources,
    hand_written_stylesheet_source,
    tailwind_config_source,
)
from tests._finance_builders import make_sim_results

_CHART_COLOURS = frozenset(colour.lower() for colour in COLOUR_PALETTE.values())


def _written_chart_colours(source: str) -> list[str]:
    """The chart colours *source* writes out, sorted."""
    lowered = source.lower()
    return sorted(colour for colour in _CHART_COLOURS if colour in lowered)


def test_no_dashboard_source_writes_out_a_chart_colour() -> None:
    assert _CHART_COLOURS, "COLOUR_PALETTE defines no colour, so this guard would pass vacuously"
    sources = {
        TAILWIND_CONFIG_KEY: tailwind_config_source(),
        **dashboard_template_sources(),
        HAND_WRITTEN_STYLESHEET_KEY: hand_written_stylesheet_source(),
        **dashboard_script_sources(),
    }

    written = {
        path: colours
        for path, source in sources.items()
        if (colours := _written_chart_colours(source))
    }

    listing = "".join(f"\n  {path}: {' '.join(colours)}" for path, colours in written.items())
    assert written == {}, (
        "These dashboard sources write out colours that charts.py's COLOUR_PALETTE defines, "
        f"so a palette edit does not reach them:{listing}\n"
        "The charts take their colours from COLOUR_PALETTE, because Plotly needs colour "
        "strings rather than Tailwind classes. Delete the copy. If a page must show a chart "
        "colour, pass it from COLOUR_PALETTE to the page."
    )


Rgb = tuple[int, int, int]
_COLOUR_LITERAL = re.compile(
    r"#(?P<hex>[0-9a-f]{6})"
    r"|rgba?\(\s*(?P<red>\d+)\s*,\s*(?P<green>\d+)\s*,\s*(?P<blue>\d+)\s*(?:,\s*[\d.]+\s*)?\)",
    re.IGNORECASE,
)


def _colour_literals(text: str) -> Iterator[tuple[str, Rgb]]:
    """Each #rrggbb, rgb() or rgba() colour written in *text*, with its red, green and blue."""
    for match in _COLOUR_LITERAL.finditer(text):
        if match["hex"] is not None:
            red, green, blue = bytes.fromhex(match["hex"])
        else:
            red, green, blue = (int(match[channel]) for channel in ("red", "green", "blue"))
        yield match.group(), (red, green, blue)


def _strings(node: object) -> Iterator[str]:
    """Every string leaf of the dicts and lists under *node*."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _drawn_colours(figure_json: str) -> dict[str, Rgb]:
    """Each colour *figure_json* draws, by how it is written; Plotly's default template is skipped."""
    figure = json.loads(figure_json)
    figure["layout"].pop("template", None)
    return dict(literal for text in _strings(figure) for literal in _colour_literals(text))


@pytest.fixture
def shipped_rgbs(monkeypatch: pytest.MonkeyPatch) -> frozenset[Rgb]:
    """The red, green and blue of each shipped palette colour.

    For the test, each palette entry is recoloured with a colour that no shipped entry has.
    """
    shipped = frozenset(rgb for colour in COLOUR_PALETTE.values() for _, rgb in _colour_literals(colour))
    for index, role in enumerate(list(COLOUR_PALETTE), start=1):
        monkeypatch.setitem(COLOUR_PALETTE, role, f"#0000{index:02x}")
    recoloured = {rgb for colour in COLOUR_PALETTE.values() for _, rgb in _colour_literals(colour)}
    assert not shipped & recoloured, "a substitute colour equals a shipped one, so the check is blind to it"
    return shipped


def _year() -> SimulationResults:
    return make_sim_results(self_kwh=2000.0, export_kwh=800.0, import_kwh=1200.0, discharge_kwh=100.0)


def _year_with_heat_pump() -> SimulationResults:
    year = _year()
    return dataclasses.replace(year, heat_pump_load=pd.Series(0.3, index=year.demand.index))


_SUMMARY = {
    "total_generation_kwh": 100.0,
    "total_demand_kwh": 80.0,
    "total_self_consumption_kwh": 50.0,
    "total_grid_import_kwh": 30.0,
    "total_grid_export_kwh": 40.0,
    "total_battery_charge_kwh": 10.0,
    "total_battery_discharge_kwh": 8.0,
    "self_consumption_ratio": 0.5,
    "grid_dependency_ratio": 0.375,
    "export_ratio": 0.4,
}
_FIVE_RUNS = ["Run A", "Run B", "Run C", "Run D", "Run E"]

_FIGURES: dict[str, Callable[[], str | None]] = {
    "power_flow_timeline": lambda: charts.power_flow_timeline(_year()),
    "battery_soc_chart": lambda: charts.battery_soc_chart(_year(), battery_capacity_kwh=10.0),
    "sankey_diagram": lambda: charts.sankey_diagram(_SUMMARY),
    "daily_energy_balance": lambda: charts.daily_energy_balance(_year()),
    "monthly_summary": lambda: charts.monthly_summary(_year()),
    "financial_breakdown": lambda: charts.financial_breakdown(_year()),
    "seasonal_comparison": lambda: charts.seasonal_comparison(_year()),
    "heat_pump_load_profile": lambda: charts.heat_pump_analysis(_year_with_heat_pump())["cop_chart"],
    "heat_pump_share": lambda: charts.heat_pump_analysis(_year_with_heat_pump())["load_share_chart"],
    "overlaid_power_flows": lambda: charts.overlaid_power_flows([_year()] * 5, _FIVE_RUNS),
    "comparison_bar_chart": lambda: charts.comparison_bar_chart([_SUMMARY] * 5, _FIVE_RUNS),
    "comparison_radar": lambda: charts.comparison_radar([_SUMMARY] * 5, _FIVE_RUNS),
    "fleet_aggregate_timeline": lambda: charts.fleet_aggregate_timeline(_year()),
    "fleet_grid_impact": lambda: charts.fleet_grid_impact(_year()),
    "fleet_heatmap": lambda: charts.fleet_heatmap([_SUMMARY] * 3),
    "fleet_box_plots": lambda: charts.fleet_box_plots([_SUMMARY] * 3),
    "fleet_distribution_histograms": lambda: charts.fleet_distribution_histograms([_SUMMARY] * 3),
    "sweep_parameter_chart": lambda: charts.sweep_parameter_chart(
        [2.0, 4.0, 6.0], [50.0, 70.0, 65.0], "PV Capacity (kW)", "Self-Consumption (%)"
    ),
}


@pytest.mark.parametrize("draw", _FIGURES.values(), ids=_FIGURES.keys())
def test_a_palette_edit_reaches_every_palette_colour_a_chart_draws(
    draw: Callable[[], str | None], shipped_rgbs: frozenset[Rgb]
) -> None:
    figure = draw()
    assert figure not in (None, "{}"), "the chart drew no figure, so this check would pass vacuously"

    stale = sorted(colour for colour, rgb in _drawn_colours(figure).items() if rgb in shipped_rgbs)

    assert stale == [], (
        f"With every COLOUR_PALETTE entry recoloured, the chart still draws {', '.join(stale)}, "
        "so a palette edit does not reach it. Name the colour's role in COLOUR_PALETTE, or derive "
        "a translucent form from its palette entry."
    )


def test_every_palette_colour_is_written_rrggbb() -> None:
    assert COLOUR_PALETTE, "COLOUR_PALETTE defines no colour, so this guard would pass vacuously"

    not_rrggbb = {
        role: colour
        for role, colour in COLOUR_PALETTE.items()
        if not re.fullmatch(r"#[0-9a-f]{6}", colour, re.IGNORECASE)
    }

    listing = "".join(f"\n  {role}: {colour!r}" for role, colour in not_rrggbb.items())
    assert not_rrggbb == {}, (
        f"These COLOUR_PALETTE entries are not written #rrggbb:{listing}\n"
        "charts.py derives each translucent chart colour from a #rrggbb palette colour, and "
        "raises when it draws a chart whose colour is written another way, such as #rgb "
        "shorthand, a colour name or rgba()."
    )


def test_a_translucent_chart_colour_refuses_a_palette_colour_not_written_rrggbb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(COLOUR_PALETTE, "battery_charge", "#5e3")

    with pytest.raises(ValueError, match="#5e3"):
        charts.battery_soc_chart(_year(), battery_capacity_kwh=10.0)
