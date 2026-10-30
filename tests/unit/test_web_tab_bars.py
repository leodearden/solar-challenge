# SPDX-License-Identifier: AGPL-3.0-or-later
"""components/macros.html's tab_bar draws the dashboard's tab bars: the home form's
configuration tabs, and the results and compare pages' chart tabs, through chart_tabs.
Each bar is a tablist named for what it switches, ruled off below its tabs by a divider,
and the server draws its first tab selected. Each tab carries its bar's layout and its
selection's colours: one pair that every bar shares, whose dark hover colours mirror its
light ones (shade n to 900 - n: hover text slate-700 to slate-200, hover underline
slate-300 to slate-600), as the dashboard's other hover colours do. Every bar's list
scrolls sideways inside the bar, its scrollbar hidden, and its tabs do not shrink, so a
bar wider than its page leaves the page its width; tests/e2e/test_mobile_responsive.py
checks that on a phone. The tab markup is written once, in tab_bar.

The written-once guard reads each source's raw text for the tab markup as
components/macros.html spells it, so it misses tab markup spelled any other way: a colour
pair in another order, role='tab' in single quotes, or a role a script sets with
setAttribute.
"""

from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

import pytest

pytest.importorskip("flask")

from flask.testing import FlaskClient

from solar_challenge.web.storage import RunStorage
from tests._dashboard_sources import dashboard_script_sources, dashboard_template_sources
from tests._finance_builders import make_fleet_results, make_home_config, make_sim_results
from tests._html_page import element_attributes
from tests._web_runs import store_fleet_run, store_home_run

_TAB_BAR_MACROS_KEY = "templates/components/macros.html"
_TAB_MARKUP = (
    'role="tablist"',
    'role="tab"',
    "border-primary-500 text-primary-600 dark:text-primary-400",
    "border-transparent text-slate-500",
)

_SELECTED_TAB_CLASSES = frozenset({"border-primary-500", "text-primary-600", "dark:text-primary-400"})
_UNSELECTED_TAB_CLASSES = frozenset(
    {
        "border-transparent",
        "text-slate-500",
        "dark:text-slate-400",
        "hover:text-slate-700",
        "dark:hover:text-slate-200",
        "hover:border-slate-300",
        "dark:hover:border-slate-600",
    }
)
_TAB_LAYOUT = frozenset(
    {"whitespace-nowrap", "flex-shrink-0", "py-3", "border-b-2", "font-medium", "text-sm", "transition-colors"}
)
_CONFIGURATION_TAB_LAYOUT = _TAB_LAYOUT | {"px-6"}
_CHART_TAB_LAYOUT = _TAB_LAYOUT | {"px-1"}
_SIDEWAYS_SCROLLING_LIST = frozenset({"overflow-x-auto", "scrollbar-hide"})
_DIVIDER = frozenset({"border-b", "border-slate-200", "dark:border-slate-700"})


def _classes(attributes: Mapping[str, str | None]) -> frozenset[str]:
    """The classes of an element that carries *attributes*."""
    return frozenset((attributes.get("class") or "").split())


def _page(client: FlaskClient, path: str) -> str:
    """The page the app answers at *path*, which it must answer 200."""
    response = client.get(path)

    assert response.status_code == 200, f"{path} answered {response.status_code}"
    return response.get_data(as_text=True)


def _home_form_page(client: FlaskClient, storage: RunStorage) -> str:
    """The form that starts a home simulation, which shows no stored run."""
    return _page(client, "/simulate/home")


def _home_results_page(client: FlaskClient, storage: RunStorage) -> str:
    """The results page of a stored one-day home run."""
    store_home_run(storage, "home-1", make_home_config(), make_sim_results(days=1))
    return _page(client, "/results/home-1")


def _fleet_results_page(client: FlaskClient, storage: RunStorage) -> str:
    """The results page of a stored one-day run of a two-home fleet."""
    store_fleet_run(storage, "fleet-1", make_fleet_results(n_homes=2, days=1))
    return _page(client, "/results/fleet-1")


def _compare_page(client: FlaskClient, storage: RunStorage) -> str:
    """The page comparing two stored one-day home runs."""
    for run_id in ("home-1", "home-2"):
        store_home_run(storage, run_id, make_home_config(), make_sim_results(days=1))
    return _page(client, "/history/compare?ids=home-1,home-2")


class _TabBar(NamedTuple):
    """The tab bar of the page *open* opens: its name, the layout classes each of its tabs carries beside its colours, and how many tabs it has."""

    open: Callable[[FlaskClient, RunStorage], str]
    label: str
    tab_layout: frozenset[str]
    tab_count: int


_PAGES_WITH_TAB_BARS = [
    pytest.param(_TabBar(_home_form_page, "Configuration tabs", _CONFIGURATION_TAB_LAYOUT, 7), id="home-form"),
    pytest.param(_TabBar(_home_results_page, "Chart tabs", _CHART_TAB_LAYOUT, 4), id="results-home"),
    pytest.param(_TabBar(_fleet_results_page, "Chart tabs", _CHART_TAB_LAYOUT, 3), id="results-fleet"),
    pytest.param(_TabBar(_compare_page, "Chart tabs", _CHART_TAB_LAYOUT, 2), id="compare"),
]


@pytest.mark.parametrize("bar", _PAGES_WITH_TAB_BARS)
def test_a_pages_tab_bar_is_a_tablist_named_for_what_it_switches_whose_tabs_carry_its_layout_and_their_selection_as_aria_selected_and_colours(
    client: FlaskClient, storage: RunStorage, bar: _TabBar
) -> None:
    page = bar.open(client, storage)

    tablist_labels = [nav.get("aria-label") for nav in element_attributes(page, "nav") if nav.get("role") == "tablist"]
    tabs = [
        (button.get("aria-selected"), _classes(button))
        for button in element_attributes(page, "button")
        if button.get("role") == "tab"
    ]

    assert (tablist_labels, tabs) == (
        [bar.label],
        [("true", bar.tab_layout | _SELECTED_TAB_CLASSES)]
        + [("false", bar.tab_layout | _UNSELECTED_TAB_CLASSES)] * (bar.tab_count - 1),
    )


@pytest.mark.parametrize("bar", _PAGES_WITH_TAB_BARS)
def test_a_pages_tab_list_scrolls_sideways_inside_its_bar_with_its_scrollbar_hidden(
    client: FlaskClient, storage: RunStorage, bar: _TabBar
) -> None:
    page = bar.open(client, storage)

    tab_lists = [_classes(nav) for nav in element_attributes(page, "nav") if nav.get("role") == "tablist"]

    assert [_SIDEWAYS_SCROLLING_LIST - classes for classes in tab_lists] == [frozenset()]


def test_a_tab_bar_is_one_div_in_its_classes_ruled_off_below_its_tabs_by_a_divider(macros: Any) -> None:
    drawn = str(macros.tab_bar([{"key": "pv", "label": "PV"}], label="Configuration tabs", classes="mb-6"))

    assert [_classes(div) for div in element_attributes(drawn, "div")] == [_DIVIDER | {"mb-6"}]


def test_no_dashboard_source_but_components_macros_html_writes_tab_markup() -> None:
    sources = {**dashboard_template_sources(), **dashboard_script_sources()}
    unwritten = [marker for marker in _TAB_MARKUP if marker not in sources.get(_TAB_BAR_MACROS_KEY, "")]
    assert unwritten == [], (
        f"read none of {unwritten} from {_TAB_BAR_MACROS_KEY}, so this guard would pass vacuously"
    )

    written = {
        path: found
        for path, source in sources.items()
        if path != _TAB_BAR_MACROS_KEY and (found := [marker for marker in _TAB_MARKUP if marker in source])
    }

    listing = "".join(f"\n  {path}: {', '.join(found)}" for path, found in written.items())
    assert written == {}, (
        f"These dashboard sources write tab markup themselves:{listing}\n"
        f"The tab markup is written once, in {_TAB_BAR_MACROS_KEY}'s tab_bar, so a page draws its tabs "
        "with tab_bar(tabs, label=..., ...), or its chart tabs with chart_tabs."
    )
