# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards two invariants of the chart colours, whose one home is the chart section of the
theme token file, static/src/theme-tokens.json, which charts.py loads into COLOUR_PALETTE:
a token edit reaches every copy of a chart colour, and the palette holds only colours a
chart draws, so it reads as the list of them.

The charts take their colours from COLOUR_PALETTE as strings, which Plotly needs. Four
checks enforce the invariants:

* No dashboard source writes out a chart colour, one of the token file's chart hues: not
  tailwind.config.js, not a template, not the hand-written stylesheet and not a script. A
  colour counts as written where its hex literal appears in a source, matched
  case-insensitively anywhere, comments included, so an eight-digit #rrggbbaa copy counts
  through its prefix. Not read: the compiled dist/style.css, which derives from the
  templates and the theme, and rgb() or rgba() forms in those sources.
* Every chart colour a chart builder draws follows a palette edit: with each palette role
  recoloured, no builder's figure still draws a chart hue as #rrggbb, rgb() or rgba(), so
  a translucent fill or a reused hue that charts.py writes out by hand fails. A colour that
  no hue has is not flagged, and a fully transparent colour, such as the charts'
  transparent backgrounds, is not read, as it draws nothing. Nor is Plotly's default
  template, which no builder chooses.
* Every palette role is drawn by some chart: with each role recoloured with a colour no
  other role has, the figures of all the _FIGURES cases together must draw every role's
  colour, so a role no chart reads fails. Only those figures are read, so a role a builder
  draws only for inputs no case gives is reported too.
* Both of those checks read a figure from every chart builder: each of its cases names the
  builder it draws with, and a public function of charts.py that no case names fails, so a
  new builder cannot go unread. A name charts.py imports, such as make_subplots, is not a
  builder.
"""

import dataclasses
import inspect
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

import pandas as pd
import pytest

pytest.importorskip("jinja2")
pytest.importorskip("plotly")
from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults
from solar_challenge.home import SimulationResults, SummaryStatistics
from solar_challenge.web import charts
from solar_challenge.web.charts import COLOUR_PALETTE
from tests._dashboard_sources import (
    HAND_WRITTEN_STYLESHEET_KEY,
    TAILWIND_CONFIG_KEY,
    THEME_TOKENS_KEY,
    dashboard_script_sources,
    dashboard_template_sources,
    hand_written_stylesheet_source,
    tailwind_config_source,
    theme_tokens,
)
from tests._finance_builders import make_fleet_results, make_sim_results
from tests._plotly_figure import Rgb, colour_literals, drawn_colours

_CHART_COLOURS = frozenset(colour.lower() for colour in theme_tokens()["chart"]["hues"].values())


def _written_chart_colours(source: str) -> list[str]:
    """The chart colours *source* writes out, sorted."""
    lowered = source.lower()
    return sorted(colour for colour in _CHART_COLOURS if colour in lowered)


def test_no_dashboard_source_writes_out_a_chart_colour() -> None:
    assert _CHART_COLOURS, f"{THEME_TOKENS_KEY}'s chart section defines no hue, so this guard would pass vacuously"
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
        f"These dashboard sources write out chart colours, whose one home is {THEME_TOKENS_KEY}'s "
        f"chart section, so a token edit does not reach them:{listing}\n"
        "The charts take their colours from COLOUR_PALETTE, which charts.py loads from that "
        "section, because Plotly needs colour strings rather than Tailwind classes. Delete the "
        "copy. If a page must show a chart colour, pass it from COLOUR_PALETTE to the page."
    )


@dataclasses.dataclass(frozen=True)
class _Recolouring:
    """The red, green and blue of each chart hue the token file ships, and of each role's substitute."""

    shipped: frozenset[Rgb]
    substitutes: Mapping[str, Rgb]


@pytest.fixture
def recolouring(monkeypatch: pytest.MonkeyPatch) -> _Recolouring:
    """Recolours every palette role with a colour of its own, for the test.

    The role at 1-based index i becomes #0000ii, so each role's substitute is shared by no
    other role and equals no shipped hue. A figure that draws a substitute therefore
    names the one role it reads, even where several shipped roles share one hue.
    """
    shipped = frozenset(
        rgb for colour in theme_tokens()["chart"]["hues"].values() for _, rgb in colour_literals(colour)
    )
    for index, role in enumerate(list(COLOUR_PALETTE), start=1):
        monkeypatch.setitem(COLOUR_PALETTE, role, f"#0000{index:02x}")
    substitutes = {
        role: rgb for role, colour in COLOUR_PALETTE.items() for _, rgb in colour_literals(colour)
    }
    assert shipped.isdisjoint(substitutes.values()), (
        "a substitute colour equals a shipped one, so the check is blind to it"
    )
    return _Recolouring(shipped=shipped, substitutes=MappingProxyType(substitutes))


def _year() -> SimulationResults:
    return make_sim_results(self_kwh=2000.0, export_kwh=800.0, import_kwh=1200.0, discharge_kwh=100.0)


def _year_with_heat_pump() -> SimulationResults:
    year = _year()
    return dataclasses.replace(year, heat_pump_load=pd.Series(0.3, index=year.demand.index))


def _fleet_year() -> FleetResults:
    return make_fleet_results(n_homes=2)


_SUMMARY = SummaryStatistics(
    total_generation_kwh=100.0,
    total_demand_kwh=80.0,
    total_self_consumption_kwh=50.0,
    total_grid_import_kwh=30.0,
    total_grid_export_kwh=40.0,
    total_battery_charge_kwh=10.0,
    total_battery_discharge_kwh=8.0,
    peak_generation_kw=4.0,
    peak_demand_kw=2.5,
    self_consumption_ratio=0.5,
    grid_dependency_ratio=0.375,
    export_ratio=0.4,
    simulation_days=1,
    total_import_cost_gbp=0.0,
    total_export_revenue_gbp=0.0,
    net_cost_gbp=0.0,
    total_grid_charge_kwh=4.0,
)
_FIVE_RUNS = ["Run A", "Run B", "Run C", "Run D", "Run E"]
_TEN_KWH_BATTERY = BatteryConfig(capacity_kwh=10.0)


@dataclasses.dataclass(frozen=True)
class _FigureCase:
    """A figure the palette checks read: *draw* draws it with *builder*, which it is passed."""

    builder: Callable[..., Any]
    draw: Callable[[Callable[..., Any]], str | None]

    def figure(self) -> str:
        """The figure's JSON, drawn now, with the palette as it stands."""
        figure = self.draw(self.builder)
        assert figure is not None and figure != "{}", (
            f"{self.builder.__name__} drew no figure, so a check reading the figure would pass vacuously"
        )
        return figure


_FIGURES: dict[str, _FigureCase] = {
    "power_flow_timeline": _FigureCase(charts.power_flow_timeline, lambda build: build(_year())),
    "battery_soc_chart": _FigureCase(
        charts.battery_soc_chart, lambda build: build(_year(), battery_config=_TEN_KWH_BATTERY)
    ),
    "sankey_diagram": _FigureCase(charts.sankey_diagram, lambda build: build(_SUMMARY)),
    "daily_energy_balance": _FigureCase(charts.daily_energy_balance, lambda build: build(_year())),
    "monthly_summary": _FigureCase(charts.monthly_summary, lambda build: build(_year())),
    "financial_breakdown": _FigureCase(charts.financial_breakdown, lambda build: build(_year())),
    "seasonal_comparison": _FigureCase(charts.seasonal_comparison, lambda build: build(_year())),
    "heat_pump_load_profile": _FigureCase(
        charts.heat_pump_analysis, lambda build: build(_year_with_heat_pump()).load_profile_chart
    ),
    "heat_pump_share": _FigureCase(
        charts.heat_pump_analysis, lambda build: build(_year_with_heat_pump()).load_share_chart
    ),
    "comparison_bar_chart": _FigureCase(
        charts.comparison_bar_chart, lambda build: build([dataclasses.asdict(_SUMMARY)] * 5, _FIVE_RUNS)
    ),
    "comparison_radar": _FigureCase(
        charts.comparison_radar, lambda build: build([dataclasses.asdict(_SUMMARY)] * 5, _FIVE_RUNS)
    ),
    "fleet_aggregate_timeline": _FigureCase(charts.fleet_aggregate_timeline, lambda build: build(_fleet_year())),
    "fleet_grid_impact": _FigureCase(charts.fleet_grid_impact, lambda build: build(_fleet_year())),
    "fleet_heatmap": _FigureCase(charts.fleet_heatmap, lambda build: build([_SUMMARY] * 3)),
    "fleet_box_plots": _FigureCase(charts.fleet_box_plots, lambda build: build([_SUMMARY] * 3)),
    "fleet_distribution_histograms": _FigureCase(
        charts.fleet_distribution_histograms, lambda build: build([_SUMMARY] * 3)
    ),
    "sweep_parameter_chart": _FigureCase(
        charts.sweep_parameter_chart,
        lambda build: build([2.0, 4.0, 6.0], [50.0, 70.0, 65.0], "PV Capacity (kW)", "Self-Consumption (%)"),
    ),
}


@pytest.mark.parametrize("case", _FIGURES.values(), ids=_FIGURES.keys())
def test_a_palette_edit_reaches_every_palette_colour_a_chart_draws(
    case: _FigureCase, recolouring: _Recolouring
) -> None:
    stale = sorted(
        colour for colour, rgb in drawn_colours(case.figure()).items() if rgb in recolouring.shipped
    )

    assert stale == [], (
        f"With every COLOUR_PALETTE role recoloured, the chart still draws {', '.join(stale)}, "
        f"a chart hue of {THEME_TOKENS_KEY}, so a token edit does not reach it. Draw the colour "
        "through its role in COLOUR_PALETTE, giving the token file's chart section a role for it "
        "if it has none, or derive a translucent form from its palette entry."
    )


def test_every_palette_role_is_drawn_by_some_chart(recolouring: _Recolouring) -> None:
    assert COLOUR_PALETTE, "COLOUR_PALETTE holds no role, so this guard would pass vacuously"

    drawn = {rgb for case in _FIGURES.values() for rgb in drawn_colours(case.figure()).values()}
    undrawn = sorted(role for role, substitute in recolouring.substitutes.items() if substitute not in drawn)

    assert undrawn == [], (
        f"No chart draws these COLOUR_PALETTE roles: {', '.join(undrawn)}. The palette reads as "
        "the list of the colours the charts draw, and the palette-edit check never reads a role "
        f"no chart draws. Delete the role from {THEME_TOKENS_KEY}'s chart section, or draw it in "
        "a chart builder. If a builder draws it only for some inputs, give _FIGURES a case with "
        "those inputs."
    )


def _public_chart_builders() -> frozenset[Callable[..., Any]]:
    """Each public function charts.py defines; a name it imports, such as make_subplots, is not one."""
    return frozenset(
        routine
        for name, routine in inspect.getmembers(charts, inspect.isroutine)
        if not name.startswith("_") and getattr(routine, "__module__", None) == charts.__name__
    )


def test_every_public_chart_builder_has_a_figure_case() -> None:
    builders = _public_chart_builders()
    assert builders, "charts.py defines no public function, so this guard would pass vacuously"

    exercised = {case.builder for case in _FIGURES.values()}
    unexercised = sorted(builder.__name__ for builder in builders - exercised)

    assert unexercised == [], (
        "No _FIGURES case draws a figure with these public charts.py functions: "
        f"{', '.join(unexercised)}. Neither palette check reads the colours they draw. "
        "Add each to _FIGURES with inputs that make it draw a figure."
    )


def test_a_translucent_chart_colour_refuses_a_palette_colour_not_written_rrggbb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(COLOUR_PALETTE, "battery_charge", "#5e3")

    with pytest.raises(ValueError, match="#5e3"):
        charts.battery_soc_chart(_year(), battery_config=_TEN_KWH_BATTERY)
