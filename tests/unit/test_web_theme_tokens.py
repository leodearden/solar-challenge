# SPDX-License-Identifier: AGPL-3.0-or-later
"""The theme token file, static/src/theme-tokens.json, is the one home of the dashboard's
colours (docs/prds/chart-panels-and-theme-tokens.md §Contract). Its chart section holds the
chart hues, each written #rrggbb, and the chart roles, each naming a hue; charts.py loads
them into COLOUR_PALETTE when it is imported, through theme_tokens.chart_colour_palette.

* No web source but the token file writes a hex colour: no template, script, hand-written
  stylesheet, Python module or JavaScript file at the package root, such as
  tailwind.config.js and build-favicon.js.
* The committed file loads to the colours the charts draw, each role in its hue's colour.
* A token file that is not a JSON object, or whose chart section, or the chart section's
  hues or roles, is missing or not a JSON object, is refused, naming the file and the section.
* A token file whose role names a hue it does not define, or whose hue is not written
  #rrggbb, is refused, naming them.
* A hue edit reaches every role that names it, and the figures that draw those roles.
"""

import dataclasses
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("jinja2")
pytest.importorskip("plotly")
from solar_challenge.home import calculate_summary
from solar_challenge.web import charts
from solar_challenge.web.theme_tokens import chart_colour_palette
from tests._dashboard_sources import (
    FAVICON_BUILDER_KEY,
    HAND_WRITTEN_STYLESHEET_KEY,
    TAILWIND_CONFIG_KEY,
    THEME_TOKENS_KEY,
    dashboard_python_sources,
    dashboard_script_sources,
    dashboard_template_sources,
    hand_written_stylesheet_source,
    package_root_javascript_sources,
    theme_tokens,
    theme_tokens_source,
)
from tests._finance_builders import make_sim_results
from tests._plotly_figure import drawn_colours, opaque, traces_by_name

_HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")

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

_TokenCopy = Callable[[object], Path]


def test_no_web_source_but_the_token_file_writes_a_hex_colour() -> None:
    """A hex colour is six hex digits after a hash, in any case, anywhere in a source, comments
    included; an eight-digit colour counts through its first six digits.

    static/dist, whose style.css and favicon.svg npm builds from these sources, and static/vendor
    are not sources.
    """
    python_sources = dashboard_python_sources()
    assert {"charts.py", "theme_tokens.py"} <= python_sources.keys(), (
        f"read the web Python modules {sorted(python_sources)}, without charts.py or "
        "theme_tokens.py, the modules that read and draw the chart colours, so this scan would "
        "pass without reading them: fix tests/_dashboard_sources.py's dashboard_python_sources"
    )
    script_sources = dashboard_script_sources()
    assert "static/js/chart-renderer.js" in script_sources, (
        f"read the scripts {sorted(script_sources)}, without static/js/chart-renderer.js, the "
        "script that colours every chart, so this scan would pass without reading it: fix "
        "tests/_dashboard_sources.py's dashboard_script_sources"
    )
    root_javascript = package_root_javascript_sources()
    assert {TAILWIND_CONFIG_KEY, FAVICON_BUILDER_KEY} <= root_javascript.keys(), (
        f"read the JavaScript files {sorted(root_javascript)} at the package root, without "
        f"{TAILWIND_CONFIG_KEY} or {FAVICON_BUILDER_KEY}, the files that build the Tailwind theme "
        "and draw the favicon in it, so this scan would pass without reading them: fix "
        "tests/_dashboard_sources.py's package_root_javascript_sources, or its key constant if "
        "the file was renamed"
    )
    sources = {
        THEME_TOKENS_KEY: theme_tokens_source(),
        **root_javascript,
        HAND_WRITTEN_STYLESHEET_KEY: hand_written_stylesheet_source(),
        **dashboard_template_sources(),
        **script_sources,
        **python_sources,
    }

    written = {
        path: hexes for path, source in sources.items() if (hexes := sorted(set(_HEX_COLOUR.findall(source))))
    }

    assert THEME_TOKENS_KEY in written, (
        f"read no hex colour from {THEME_TOKENS_KEY}, the home of the dashboard's colours, so this "
        "scan would pass vacuously"
    )
    elsewhere = {path: hexes for path, hexes in written.items() if path != THEME_TOKENS_KEY}
    listing = "".join(f"\n  {path}: {' '.join(hexes)}" for path, hexes in elsewhere.items())
    assert elsewhere == {}, (
        f"These web sources write hex colours, whose one home is {THEME_TOKENS_KEY}:{listing}\n"
        "A UI colour is reached through a Tailwind utility naming a palette of the token file's "
        "tailwind section, such as bg-primary-500, or on a pseudo-element an arbitrary variant "
        "such as [&::-webkit-slider-thumb]:bg-primary-500; then rebuild with "
        "`cd src/solar_challenge/web && npm ci && npm run build:css` and commit "
        "static/dist/style.css. A chart colour is reached through a role of the token file's "
        "chart section, read through charts.py's COLOUR_PALETTE. A chart's chrome colour, its "
        "text and grid, is named by the classes of components/macros.html's chart_panel "
        "container, and chart-renderer.js reads it from the container's computed style. The "
        "favicon is drawn in the theme's primary-500, which build-favicon.js reads through "
        "tailwindcss/resolveConfig; rebuild it with "
        "`cd src/solar_challenge/web && npm ci && npm run build:favicon` and commit "
        "static/dist/favicon.svg."
    )


@pytest.fixture
def token_copy(tmp_path: Path) -> _TokenCopy:
    """Writes tokens, a JSON value such as a tokens dict, to tmp_path / "theme-tokens.json", and returns the file's path."""

    def write(tokens: object) -> Path:
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


@pytest.mark.parametrize(
    ("tokens", "refusal"),
    [
        pytest.param(["chart"], "the top level must be a JSON object, got list", id="a top level that is a list"),
        pytest.param({"tailwind": {"primary": "amber"}}, "the 'chart' section is missing", id="no chart section"),
        pytest.param(
            {"chart": ["hues", "roles"]},
            "the 'chart' section must be a JSON object, got list",
            id="a chart section that is a list",
        ),
        pytest.param({"chart": {"roles": {}}}, "the 'chart.hues' section is missing", id="no hues"),
        pytest.param(
            {"chart": {"hues": "amber", "roles": {}}},
            "the 'chart.hues' section must be a JSON object, got str",
            id="hues that are a string",
        ),
        pytest.param({"chart": {"hues": {}}}, "the 'chart.roles' section is missing", id="no roles"),
        pytest.param(
            {"chart": {"hues": {}, "roles": ["summer"]}},
            "the 'chart.roles' section must be a JSON object, got list",
            id="roles that are a list",
        ),
    ],
)
def test_a_token_file_missing_a_section_or_holding_one_not_a_json_object_is_refused_naming_the_file_and_the_section(
    token_copy: _TokenCopy, tokens: object, refusal: str
) -> None:
    copy = token_copy(tokens)

    message = _refusal(copy)

    assert str(copy) in message and refusal in message, message


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
        pytest.param(lambda: charts.power_flow_timeline(make_sim_results()).content, "Generation", "line", id="pv_generation"),
        pytest.param(
            lambda: charts.seasonal_comparison(make_sim_results()).content, "Summer (Jun-Aug)", "marker", id="summer"
        ),
        pytest.param(
            lambda: charts.comparison_bar_chart([_a_days_summary()], ["Run A"]).content,
            "Run A",
            "marker",
            id="comparison_run_1",
        ),
    ],
)
def test_a_hue_edit_reaches_the_figure_of_each_role_that_names_the_hue(
    amber_recoloured: dict[str, str], draw: Callable[[], str | charts.ChartAbsence], trace: str, part: str
) -> None:
    """*trace* is the trace the figure draws in the role, and *part* the attribute, line or marker, holding its colour."""
    figure = draw()
    assert isinstance(figure, str), "the builder drew no figure, so this check would pass vacuously"

    assert traces_by_name(figure)[trace][part]["color"] == _RECOLOURED_AMBER
    assert _SHIPPED_AMBER not in {opaque(colour) for colour in drawn_colours(figure)}
