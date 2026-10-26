# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards three invariants of the chart colours, whose one home is the chart section of the
theme token file, static/src/theme-tokens.json, which charts.py loads into COLOUR_PALETTE:
a token edit reaches every chart colour a chart draws; the palette holds only colours a
chart draws, so it reads as the list of them; and no chart draws Plotly's default template's
bar outline, a colour outside the palette. That no other web source writes out a chart
colour is test_web_theme_tokens.py's to guard.

The charts take their colours from COLOUR_PALETTE as strings, which Plotly needs. Four
checks enforce the invariants:

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
* No chart outlines its bars: Plotly's default template, which every figure carries,
  outlines each bar in its own plot background colour, #E5ECF6, which no figure draws, so
  every bar trace of every _FIGURES case must set its own outline width to 0.
* All three of those checks read the figures of every public function of charts.py, each
  chart builder and each page's tab assembler: each case names the function it draws with
  and reads the figure of every panel the function returns, every panel of every tab for an
  assembler, and a public function that no case names fails, so a new builder cannot go
  unread. A name charts.py imports, such as make_subplots, is not a builder.
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
from solar_challenge.web.charts import COLOUR_PALETTE, ChartPanel, ChartTab
from tests._dashboard_sources import THEME_TOKENS_KEY, theme_tokens
from tests._finance_builders import make_fleet_results, make_home_config, make_sim_results
from tests._plotly_figure import Rgb, colour_literals, drawn_colours, traces


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


def _panels_of(tabs: tuple[ChartTab, ...]) -> tuple[ChartPanel, ...]:
    """Every panel of *tabs*, tab by tab."""
    return tuple(panel for tab in tabs for panel in tab.panels)


@dataclasses.dataclass(frozen=True)
class _FigureCase:
    """Figures the palette checks read: *draw* draws their panels with *builder*, which it is passed."""

    builder: Callable[..., Any]
    draw: Callable[[Callable[..., Any]], tuple[ChartPanel, ...]]

    def figures(self) -> list[str]:
        """The JSON of each panel's figure, drawn now, with the palette as it stands."""
        panels = self.draw(self.builder)
        absent = [panel.dom_id for panel in panels if not isinstance(panel.content, str)]
        assert panels and absent == [], (
            f"{self.builder.__name__} drew no figure for {absent or 'any panel'}, so a check reading"
            " its figures would pass vacuously"
        )
        return [panel.content for panel in panels if isinstance(panel.content, str)]


_FIGURES: dict[str, _FigureCase] = {
    "power_flow_timeline": _FigureCase(charts.power_flow_timeline, lambda build: (build(_year()),)),
    "battery_soc_chart": _FigureCase(
        charts.battery_soc_chart, lambda build: (build(_year(), battery_config=_TEN_KWH_BATTERY),)
    ),
    "sankey_diagram": _FigureCase(charts.sankey_diagram, lambda build: (build(_SUMMARY),)),
    "daily_energy_balance": _FigureCase(charts.daily_energy_balance, lambda build: (build(_year()),)),
    "monthly_summary": _FigureCase(charts.monthly_summary, lambda build: (build(_year()),)),
    "financial_breakdown": _FigureCase(charts.financial_breakdown, lambda build: (build(_year()),)),
    "seasonal_comparison": _FigureCase(charts.seasonal_comparison, lambda build: (build(_year()),)),
    "heat_pump_analysis": _FigureCase(charts.heat_pump_analysis, lambda build: build(_year_with_heat_pump())),
    "comparison_bar_chart": _FigureCase(
        charts.comparison_bar_chart, lambda build: (build([dataclasses.asdict(_SUMMARY)] * 5, _FIVE_RUNS),)
    ),
    "comparison_radar": _FigureCase(
        charts.comparison_radar, lambda build: (build([dataclasses.asdict(_SUMMARY)] * 5, _FIVE_RUNS),)
    ),
    "fleet_aggregate_timeline": _FigureCase(charts.fleet_aggregate_timeline, lambda build: (build(_fleet_year()),)),
    "fleet_grid_impact": _FigureCase(charts.fleet_grid_impact, lambda build: (build(_fleet_year()),)),
    "fleet_heatmap": _FigureCase(charts.fleet_heatmap, lambda build: (build([_SUMMARY] * 3),)),
    "fleet_box_plots": _FigureCase(charts.fleet_box_plots, lambda build: (build([_SUMMARY] * 3),)),
    "fleet_distribution_histograms": _FigureCase(
        charts.fleet_distribution_histograms, lambda build: (build([_SUMMARY] * 3),)
    ),
    "sweep_parameter_chart": _FigureCase(
        charts.sweep_parameter_chart,
        lambda build: (build([2.0, 4.0, 6.0], [50.0, 70.0, 65.0], "PV Capacity (kW)", "Self-Consumption (%)"),),
    ),
    "home_results_tabs": _FigureCase(
        charts.home_results_tabs,
        lambda build: _panels_of(
            build(make_home_config(battery_config=_TEN_KWH_BATTERY), _year_with_heat_pump(), _SUMMARY)
        ),
    ),
    "fleet_results_tabs": _FigureCase(
        charts.fleet_results_tabs, lambda build: _panels_of(build(_fleet_year(), [_SUMMARY] * 3))
    ),
    "comparison_tabs": _FigureCase(
        charts.comparison_tabs,
        lambda build: _panels_of(build([dataclasses.asdict(_SUMMARY)] * 5, _FIVE_RUNS)),
    ),
}


@pytest.mark.parametrize("case", _FIGURES.values(), ids=_FIGURES.keys())
def test_a_palette_edit_reaches_every_palette_colour_a_chart_draws(
    case: _FigureCase, recolouring: _Recolouring
) -> None:
    stale = sorted(
        {
            colour
            for figure in case.figures()
            for colour, rgb in drawn_colours(figure).items()
            if rgb in recolouring.shipped
        }
    )

    assert stale == [], (
        f"With every COLOUR_PALETTE role recoloured, the chart still draws {', '.join(stale)}, "
        f"a chart hue of {THEME_TOKENS_KEY}, so a token edit does not reach it. Draw the colour "
        "through its role in COLOUR_PALETTE, giving the token file's chart section a role for it "
        "if it has none, or derive a translucent form from its palette entry."
    )


def test_every_palette_role_is_drawn_by_some_chart(recolouring: _Recolouring) -> None:
    assert COLOUR_PALETTE, "COLOUR_PALETTE holds no role, so this guard would pass vacuously"

    drawn = {
        rgb for case in _FIGURES.values() for figure in case.figures() for rgb in drawn_colours(figure).values()
    }
    undrawn = sorted(role for role, substitute in recolouring.substitutes.items() if substitute not in drawn)

    assert undrawn == [], (
        f"No chart draws these COLOUR_PALETTE roles: {', '.join(undrawn)}. The palette reads as "
        "the list of the colours the charts draw, and the palette-edit check never reads a role "
        f"no chart draws. Delete the role from {THEME_TOKENS_KEY}'s chart section, or draw it in "
        "a chart builder. If a builder draws it only for some inputs, give _FIGURES a case with "
        "those inputs."
    )


def test_no_chart_outlines_its_bars() -> None:
    """Plotly's default template, which every figure carries, outlines each bar 0.5 px in its plot background colour, #E5ECF6.

    No figure draws that background, so the outline showed as a light rim round every bar on the dark card
    (task 1046). A bar trace's own outline width of 0 overrides the template's.
    """
    bars = [
        (case_name, trace["name"], trace.get("marker", {}).get("line", {}).get("width"))
        for case_name, case in _FIGURES.items()
        for figure in case.figures()
        for trace in traces(figure)
        if trace["type"] == "bar"
    ]
    assert bars, "no _FIGURES case draws a bar, so this check would pass vacuously"

    outlined = sorted(
        f"{case_name}: {name!r} (outline width {width})" for case_name, name, width in bars if width != 0
    )

    assert outlined == [], (
        "These bar traces keep the outline of Plotly's default template, #E5ECF6 at 0.5 px, a light rim "
        f"on the dark card: {', '.join(outlined)}. Build each bar with charts.py's bar helper, _bar, which "
        "sets its outline width, marker.line.width, to 0."
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
