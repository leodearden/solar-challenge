# SPDX-License-Identifier: AGPL-3.0-or-later
"""The theme token file, static/src/theme-tokens.json, is the one home of the dashboard's
colours (docs/prds/chart-panels-and-theme-tokens.md §Contract). Its chart section holds the
chart hues, each written #rrggbb, and the chart roles, each naming a hue; charts.py loads
them into COLOUR_PALETTE when it is imported, through theme_tokens.chart_colour_palette.

* The committed file loads to the colours the charts draw, each role in its hue's colour.
* A token file whose role names a hue it does not define, or whose hue is not written
  #rrggbb, is refused, naming them.
* A hue edit reaches every role that names it, and the figures that draw those roles.
"""

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("jinja2")
pytest.importorskip("plotly")
from solar_challenge.home import calculate_summary
from solar_challenge.web import charts
from solar_challenge.web.theme_tokens import chart_colour_palette
from tests._dashboard_sources import theme_tokens
from tests._finance_builders import make_sim_results
from tests._plotly_figure import drawn_colours, opaque, traces_by_name

_CHART_ROLE_COLOURS = {
    "pv_generation": "#f5a623",
    "demand": "#d0021b",
    "self_consumption": "#7ed321",
    "grid_import": "#9b9b9b",
    "grid_export": "#4a90e2",
    "battery_charge": "#50e3c2",
    "heat_pump": "#9013fe",
    "cost": "#d0021b",
    "revenue": "#7ed321",
    "soc_low_threshold": "#d0021b",
    "soc_high_threshold": "#7ed321",
    "net_cost": "#4a90e2",
    "winter": "#4a90e2",
    "summer": "#f5a623",
    "comparison_run_1": "#f5a623",
    "comparison_run_2": "#4a90e2",
    "comparison_run_3": "#7ed321",
    "comparison_run_4": "#9013fe",
    "unpriced_note": "#888888",
    "sankey_node_outline": "#000000",
}
_SHIPPED_AMBER = "#f5a623"
_RECOLOURED_AMBER = "#0000aa"

_TokenCopy = Callable[[dict[str, Any]], Path]


@pytest.fixture
def token_copy(tmp_path: Path) -> _TokenCopy:
    """Writes a tokens dict as JSON to tmp_path / "theme-tokens.json", and returns the file's path."""

    def write(tokens: dict[str, Any]) -> Path:
        copy = tmp_path / "theme-tokens.json"
        copy.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
        return copy

    return write


def _refusal(tokens_file: Path) -> str:
    """The message of the ValueError chart_colour_palette raises for *tokens_file*."""
    with pytest.raises(ValueError) as refused:
        chart_colour_palette(tokens_file)
    return str(refused.value)


def test_colour_palette_holds_each_chart_role_in_its_hues_colour() -> None:
    """These are the colours the charts draw, so recolouring a role is a deliberate edit of this table."""
    assert dict(charts.COLOUR_PALETTE) == _CHART_ROLE_COLOURS


def test_a_role_naming_a_hue_the_token_file_does_not_define_is_refused_naming_the_role_and_the_hue(
    token_copy: _TokenCopy,
) -> None:
    tokens = theme_tokens()
    tokens["chart"]["roles"]["summer"] = "gold"

    message = _refusal(token_copy(tokens))

    assert "'summer'" in message and "'gold'" in message, message


@pytest.mark.parametrize(
    "written",
    [
        pytest.param("#f5a62", id="five hex digits"),
        pytest.param("black", id="a colour name"),
    ],
)
def test_a_hue_not_written_rrggbb_is_refused_naming_the_hue_and_its_value(
    token_copy: _TokenCopy, written: str
) -> None:
    tokens = theme_tokens()
    tokens["chart"]["hues"]["amber"] = written

    message = _refusal(token_copy(tokens))

    assert "'amber'" in message and repr(written) in message, message


@pytest.fixture
def install_palette_from(
    token_copy: _TokenCopy, monkeypatch: pytest.MonkeyPatch
) -> Callable[[dict[str, Any]], dict[str, str]]:
    """Installs in charts.COLOUR_PALETTE, for the test, the palette a token file holding a tokens dict loads to, and returns it."""

    def install(tokens: dict[str, Any]) -> dict[str, str]:
        palette = chart_colour_palette(token_copy(tokens))
        assert palette.keys() == charts.COLOUR_PALETTE.keys(), (
            f"the token copy loads the roles {sorted(palette)}, where COLOUR_PALETTE has "
            f"{sorted(charts.COLOUR_PALETTE)}, so installing it would not recolour every role"
        )
        for role, colour in palette.items():
            monkeypatch.setitem(charts.COLOUR_PALETTE, role, colour)
        return palette

    return install


@pytest.fixture
def amber_recoloured(install_palette_from: Callable[[dict[str, Any]], dict[str, str]]) -> dict[str, str]:
    """The palette, installed for the test, of the committed token file with its hue amber recoloured."""
    tokens = theme_tokens()
    tokens["chart"]["hues"]["amber"] = _RECOLOURED_AMBER
    return install_palette_from(tokens)


def test_a_hue_edit_recolours_exactly_the_roles_that_name_the_hue(amber_recoloured: dict[str, str]) -> None:
    recoloured = {role for role, colour in amber_recoloured.items() if colour == _RECOLOURED_AMBER}

    assert recoloured == {"pv_generation", "summer", "comparison_run_1"}
    assert _SHIPPED_AMBER not in amber_recoloured.values()


def _a_days_summary() -> dict[str, Any]:
    return dataclasses.asdict(calculate_summary(make_sim_results(days=1)))


@pytest.mark.parametrize(
    ("draw", "trace", "part"),
    [
        pytest.param(lambda: charts.power_flow_timeline(make_sim_results()), "Generation", "line", id="pv_generation"),
        pytest.param(
            lambda: charts.seasonal_comparison(make_sim_results()), "Summer (Jun-Aug)", "marker", id="summer"
        ),
        pytest.param(
            lambda: charts.comparison_bar_chart([_a_days_summary()], ["Run A"]),
            "Run A",
            "marker",
            id="comparison_run_1",
        ),
    ],
)
def test_a_hue_edit_reaches_the_figure_of_each_role_that_names_the_hue(
    amber_recoloured: dict[str, str], draw: Callable[[], str | None], trace: str, part: str
) -> None:
    """*trace* is the trace the figure draws in the role, and *part* the attribute, line or marker, holding its colour."""
    figure = draw()
    assert figure is not None, "the builder drew no figure, so this check would pass vacuously"

    assert traces_by_name(figure)[trace][part]["color"] == _RECOLOURED_AMBER
    assert _SHIPPED_AMBER not in {opaque(colour) for colour in drawn_colours(figure)}
