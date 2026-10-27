# SPDX-License-Identifier: AGPL-3.0-or-later
"""components/macros.html's card draws every dashboard card, one element in the card
classes plus the classes its page gives it. The card classes are written once, in card,
so no other template or script draws a card itself.
"""

from collections.abc import Callable, Mapping
from typing import Any

import pytest

pytest.importorskip("flask")

from flask.testing import FlaskClient
from markupsafe import Markup

from solar_challenge.web.storage import RunStorage
from tests._dashboard_sources import dashboard_script_sources, dashboard_template_sources
from tests._finance_builders import make_fleet_results, make_home_config, make_sim_results
from tests._html_page import element_attributes, headings, texts
from tests._web_runs import store_fleet_run, store_home_run

_CARD_TRIPLE = "bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-sm"
_CARD_CLASSES = frozenset(_CARD_TRIPLE.split())
_CARD_MACROS_KEY = "templates/components/macros.html"

_Card = tuple[str, frozenset[str]]


def _classes(attributes: Mapping[str, str | None]) -> frozenset[str]:
    """The classes of an element that carries *attributes*."""
    return frozenset((attributes.get("class") or "").split())


def _cards(page: str) -> list[_Card]:
    """The tag, and the classes beyond the card classes, of each link and then each div of *page* that carries every card class, each in page order."""
    return [
        (tag, classes - _CARD_CLASSES)
        for tag in ("a", "div")
        for classes in map(_classes, element_attributes(page, tag))
        if _CARD_CLASSES <= classes
    ]


def _div(*classes: str) -> _Card:
    """A div card that carries *classes* beyond the card classes."""
    return ("div", frozenset(classes))


def _quick_start_link(palette: str) -> _Card:
    """A dashboard quick-start link card, whose shadow grows and whose border takes *palette*'s colour on hover."""
    return (
        "a",
        frozenset(
            {
                "group",
                "block",
                "p-6",
                "hover:shadow-md",
                f"hover:border-{palette}-300",
                f"dark:hover:border-{palette}-600",
                "transition-all",
            }
        ),
    )


def _page(client: FlaskClient, path: str) -> str:
    """The page the app answers at *path*, which it must answer 200."""
    response = client.get(path)

    assert response.status_code == 200, f"{path} answered {response.status_code}"
    return response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(
            "/",
            [
                _quick_start_link("primary"),
                _quick_start_link("sky"),
                _quick_start_link("emerald"),
                _div("p-5"),
                _div("p-5"),
                _div("p-5"),
                _div(),
            ],
            id="dashboard",
        ),
        pytest.param(
            "/simulate/fleet",
            [
                _div("p-6", "mb-6"),
                _div("p-6", "mb-6"),
                _div("overflow-hidden"),
                _div("overflow-hidden"),
                _div("overflow-hidden"),
                _div("mb-6", "overflow-hidden"),
                _div("p-6", "mb-6"),
                _div("p-6"),
            ],
            id="fleet-form",
        ),
        pytest.param("/simulate/home", [_div("p-6")], id="home-form"),
        pytest.param("/history/compare", [_div("p-12", "text-center")], id="compare-without-runs"),
    ],
)
def test_each_card_of_a_page_that_needs_no_stored_run_carries_the_card_classes_and_its_own(
    client: FlaskClient, path: str, expected: list[_Card]
) -> None:
    assert _cards(_page(client, path)) == expected


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


_STAT_CARD = _div("p-5")
_CHART_PANEL = _div("overflow-hidden")
_ACTIONS_CARD = _div("p-6")


@pytest.mark.parametrize(
    ("open_page", "expected"),
    [
        pytest.param(_home_results_page, {_STAT_CARD, _CHART_PANEL, _ACTIONS_CARD}, id="home-results"),
        pytest.param(_fleet_results_page, {_STAT_CARD, _CHART_PANEL, _ACTIONS_CARD}, id="fleet-results"),
        pytest.param(_compare_page, {_CHART_PANEL}, id="compare-two-home-runs"),
    ],
)
def test_each_card_of_a_page_of_stored_runs_carries_the_card_classes_and_its_own(
    client: FlaskClient,
    storage: RunStorage,
    open_page: Callable[[FlaskClient, RunStorage], str],
    expected: set[_Card],
) -> None:
    """How many stat cards and chart panels a page draws follows its runs, so only the kinds of card are pinned."""
    assert set(_cards(open_page(client, storage))) == expected


def _div_classes(drawn: str) -> list[frozenset[str]]:
    """The classes of each div *drawn* draws, in page order."""
    return [_classes(div) for div in element_attributes(drawn, "div")]


def test_a_card_given_no_title_is_one_div_in_the_card_classes_and_its_own_that_holds_its_content(
    macros: Any,
) -> None:
    drawn = str(macros.card(classes="p-6 mb-6", caller=lambda: "Body"))

    assert _div_classes(drawn) == [_CARD_CLASSES | {"p-6", "mb-6"}]
    assert texts(drawn) == ["Body"]


def test_a_titled_card_draws_a_header_band_with_its_dot_title_aside_and_subtitle_then_its_padded_body(
    macros: Any,
) -> None:
    drawn = str(
        macros.card(
            title="PV Systems",
            subtitle="Sizes (kW)",
            classes="overflow-hidden",
            header_classes="bg-component-pv-50",
            dot_classes="bg-component-pv-500",
            header_aside=Markup('<label class="ml-auto">Enable</label>'),
            body_classes="p-6",
            caller=lambda: "Editor",
        )
    )

    assert _div_classes(drawn) == [
        _CARD_CLASSES | {"overflow-hidden"},
        {"px-6", "py-4", "border-b", "border-slate-200", "dark:border-slate-700", "bg-component-pv-50"},
        {"flex", "items-center", "gap-2"},
        {"w-3", "h-3", "rounded-full", "bg-component-pv-500"},
        {"p-6"},
    ]
    assert headings(drawn) == ["PV Systems"]
    assert texts(drawn) == ["PV Systems", "Enable", "Sizes (kW)", "Editor"]


def test_a_card_given_an_href_is_one_link_to_it_in_the_card_classes_and_its_own(macros: Any) -> None:
    drawn = str(macros.card(href="/simulate/home", classes="group block p-6", caller=lambda: "Run Single Home"))

    links = element_attributes(drawn, "a")
    assert [(link.get("href"), _classes(link)) for link in links] == [
        ("/simulate/home", _CARD_CLASSES | {"group", "block", "p-6"})
    ]
    assert element_attributes(drawn, "div") == []


def test_the_card_classes_are_written_once_in_the_dashboards_sources_in_components_macros_html() -> None:
    """Exactly one copy, so neither another template or script nor a macro built on card writes them again."""
    sources = {**dashboard_template_sources(), **dashboard_script_sources()}

    written = {path: count for path, source in sources.items() if (count := source.count(_CARD_TRIPLE))}

    listing = "".join(f"\n  {path}: {count}" for path, count in written.items())
    assert written == {_CARD_MACROS_KEY: 1}, (
        f"These dashboard sources write the card classes '{_CARD_TRIPLE}' this many times:{listing}\n"
        f"The card classes are written once, in {_CARD_MACROS_KEY}'s card, so a page draws a card with "
        "{% call card(...) %}: classes for the card's own padding, margin and hover; title, subtitle, "
        "header_classes, dot_classes and header_aside for a header band; body_classes for a padded "
        "body; and href for a link."
    )
