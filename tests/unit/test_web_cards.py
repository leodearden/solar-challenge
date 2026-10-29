# SPDX-License-Identifier: AGPL-3.0-or-later
"""components/macros.html draws every card look of the dashboard: the card, and beside it
the panel, the flat card and the split card. Each element drawn in a look carries the
look's classes plus the classes its page gives it. Each look's classes are written once,
in its macro, so no other template or script draws that look itself. A card call that
gives a header band argument, a subtitle, colours or an aside, also gives the title that
opens the band.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

import pytest

pytest.importorskip("flask")

from flask import Flask
from flask.testing import FlaskClient
from jinja2 import Environment, nodes

from solar_challenge.web.storage import RunStorage
from tests._dashboard_sources import dashboard_script_sources, dashboard_template_sources
from tests._finance_builders import make_fleet_results, make_home_config, make_sim_results
from tests._html_page import element_attributes, headings, texts
from tests._web_runs import store_fleet_run, store_home_run

_CARD_TRIPLE = "bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-sm"
_CARD_CLASSES = frozenset(_CARD_TRIPLE.split())
_CARD_MACROS_KEY = "templates/components/macros.html"
_HEADER_BAND_PARAMETERS = frozenset({"subtitle", "header_classes", "dot_classes", "header_aside"})

_JINJA = Environment()
_SCRIPT_STRING_LITERAL = re.compile(r"""'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`""")


@dataclass(frozen=True)
class _Look:
    """A card look: the components/macros.html macro that draws it, the classes every element
    drawn in it carries, and the classes none of them carries."""

    macro: str
    classes: frozenset[str]
    lacks: frozenset[str] = frozenset()

    def draws(self, classes: frozenset[str]) -> bool:
        """Whether an element that carries *classes* is drawn in this look."""
        return self.classes <= classes and not self.lacks & classes


_CARD_LOOK = _Look("card", _CARD_CLASSES)
_PANEL_LOOK = _Look(
    "panel",
    frozenset("bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-sm".split()),
)
_SHADOWS = frozenset({"shadow-sm", "shadow", "shadow-md", "shadow-lg", "shadow-xl", "shadow-2xl", "shadow-inner"})
"""The Tailwind box-shadow utilities that draw a shadow."""
_FLAT_CARD_LOOK = _Look(
    "flat_card",
    frozenset("bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg".split()),
    lacks=_SHADOWS,
)
"""Its classes are a subset of the card's, which carries shadow-sm, and of scenarios/builder.html's
preset dropdown's, which carries shadow-lg: having no shadow is what tells a flat card from both."""
_SPLIT_CARD_TOP_LOOK = _Look(
    "split_card",
    frozenset("bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-t-lg".split()),
)
_SPLIT_CARD_BOTTOM_LOOK = _Look(
    "split_card",
    frozenset("bg-white dark:bg-slate-800 border border-t-0 border-slate-200 dark:border-slate-700 rounded-b-lg".split()),
)

_Drawn = tuple[str, frozenset[str]]


def _classes(attributes: Mapping[str, str | None]) -> frozenset[str]:
    """The classes of an element that carries *attributes*."""
    return frozenset((attributes.get("class") or "").split())


def _drawn(page: str, look: _Look) -> list[_Drawn]:
    """The tag, and the classes beyond *look*'s, of each link and then each div of *page* drawn in *look*, each in page order."""
    return [
        (tag, classes - look.classes)
        for tag in ("a", "div")
        for classes in map(_classes, element_attributes(page, tag))
        if look.draws(classes)
    ]


def _div(*classes: str) -> _Drawn:
    """A div drawn in a look that carries *classes* beyond the look's classes."""
    return ("div", frozenset(classes))


def _quick_start_link(palette: str) -> _Drawn:
    """A dashboard quick-start link drawn in a look, whose shadow grows and whose border takes *palette*'s colour on hover."""
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
    ("path", "look", "expected"),
    [
        pytest.param(
            "/",
            _CARD_LOOK,
            [
                _quick_start_link("primary"),
                _quick_start_link("sky"),
                _quick_start_link("emerald"),
                _div("p-5"),
                _div("p-5"),
                _div("p-5"),
                _div(),
            ],
            id="dashboard-cards",
        ),
        pytest.param(
            "/simulate/fleet",
            _CARD_LOOK,
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
            id="fleet-form-cards",
        ),
        pytest.param("/simulate/home", _CARD_LOOK, [_div("p-6")], id="home-form-cards"),
        pytest.param("/simulate/home", _SPLIT_CARD_TOP_LOOK, [_div()], id="home-form-split-card-top"),
        pytest.param("/simulate/home", _SPLIT_CARD_BOTTOM_LOOK, [_div("p-6")], id="home-form-split-card-bottom"),
        pytest.param("/history/compare", _CARD_LOOK, [_div("p-12", "text-center")], id="compare-without-runs-cards"),
        pytest.param(
            "/scenarios/builder",
            _PANEL_LOOK,
            [
                _div("overflow-hidden"),
                _div("overflow-hidden"),
                _div("overflow-hidden"),
                _div("overflow-hidden"),
                _div("overflow-hidden"),
                _div("sticky", "top-24"),
            ],
            id="builder-panels",
        ),
        pytest.param("/scenarios/sweep", _PANEL_LOOK, [_div(), _div(), _div()], id="sweep-panels"),
        pytest.param("/assistant/", _PANEL_LOOK, [_div("flex", "flex-col", "h-[600px]")], id="assistant-panel"),
        pytest.param(
            "/history/runs",
            _FLAT_CARD_LOOK,
            [
                _div("overflow-x-auto"),
                _div("mt-4", "px-4", "py-12", "text-center", "text-sm", "text-slate-500", "dark:text-slate-400"),
                _div("mt-4", "px-4", "py-12", "text-center"),
                _div("p-4"),
            ],
            id="runs-flat-cards",
        ),
    ],
)
def test_each_element_a_page_that_needs_no_stored_run_draws_in_a_card_look_carries_the_looks_classes_and_its_own(
    client: FlaskClient, path: str, look: _Look, expected: list[_Drawn]
) -> None:
    assert _drawn(_page(client, path), look) == expected


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
_RUN_HEADER_BOX = _div("p-4", "text-center")


@pytest.mark.parametrize(
    ("open_page", "look", "expected"),
    [
        pytest.param(
            _home_results_page, _CARD_LOOK, {_STAT_CARD, _CHART_PANEL, _ACTIONS_CARD}, id="home-results-cards"
        ),
        pytest.param(
            _fleet_results_page, _CARD_LOOK, {_STAT_CARD, _CHART_PANEL, _ACTIONS_CARD}, id="fleet-results-cards"
        ),
        pytest.param(_compare_page, _CARD_LOOK, {_CHART_PANEL}, id="compare-two-home-runs-cards"),
        pytest.param(_compare_page, _FLAT_CARD_LOOK, {_RUN_HEADER_BOX}, id="compare-two-home-runs-flat-cards"),
    ],
)
def test_each_element_a_page_of_stored_runs_draws_in_a_card_look_carries_the_looks_classes_and_its_own(
    client: FlaskClient,
    storage: RunStorage,
    open_page: Callable[[FlaskClient, RunStorage], str],
    look: _Look,
    expected: set[_Drawn],
) -> None:
    """How many elements a page of runs draws in a look follows its runs, so only their kinds are pinned."""
    assert set(_drawn(open_page(client, storage), look)) == expected


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
    app: Flask,
) -> None:
    """The aside is markup its page captures in a {% set %} block, as simulate/fleet.html captures its battery card's switch."""
    page = app.jinja_env.from_string(
        '{% from "components/macros.html" import card %}'
        '{% set aside %}<label class="ml-auto">Enable</label>{% endset %}'
        '{% call card(title="PV Systems", subtitle="Sizes (kW)", classes="overflow-hidden",'
        ' header_classes="bg-component-pv-50", dot_classes="bg-component-pv-500",'
        ' header_aside=aside, body_classes="p-6") %}Editor{% endcall %}'
    )

    drawn = page.render()

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


def test_a_panel_is_one_div_in_the_panel_classes_and_its_own_that_holds_its_content(macros: Any) -> None:
    drawn = str(macros.panel(classes="sticky top-24", caller=lambda: "Body"))

    assert _div_classes(drawn) == [_PANEL_LOOK.classes | {"sticky", "top-24"}]
    assert texts(drawn) == ["Body"]


def test_a_flat_card_is_one_div_in_the_flat_card_classes_and_its_own_that_holds_its_content(macros: Any) -> None:
    drawn = str(macros.flat_card(classes="p-4 text-center", caller=lambda: "Body"))

    assert _div_classes(drawn) == [_FLAT_CARD_LOOK.classes | {"p-4", "text-center"}]
    assert texts(drawn) == ["Body"]


def test_a_split_card_draws_its_top_part_then_its_bottom_part_each_in_its_parts_classes(app: Flask) -> None:
    """Each part is markup its page captures in a {% set %} block, as simulate/home.html captures its
    configuration and its submission."""
    page = app.jinja_env.from_string(
        '{% from "components/macros.html" import split_card %}'
        "{% set top %}<p>Tabs</p>{% endset %}"
        "{% set bottom %}<p>Run</p>{% endset %}"
        '{{ split_card(top, bottom, bottom_classes="p-6") }}'
    )

    drawn = page.render()

    assert _div_classes(drawn) == [_SPLIT_CARD_TOP_LOOK.classes, _SPLIT_CARD_BOTTOM_LOOK.classes | {"p-6"}]
    assert texts(drawn) == ["Tabs", "Run"]


def _card_calls(source: str) -> list[nodes.Call]:
    """Each call of card in the Jinja template *source*, by {{ card(...) }} and {% call card(...) %} alike."""
    return [
        call
        for call in _JINJA.parse(source).find_all(nodes.Call)
        if isinstance(call.node, nodes.Name) and call.node.name == "card"
    ]


def _given_parameters(call: nodes.Call, parameters: Sequence[str]) -> set[str]:
    """The parameters *call* gives, by position or by keyword, of a macro that takes *parameters* in that order."""
    return {*parameters[: len(call.args)], *(keyword.key for keyword in call.kwargs)}


def test_every_card_call_that_gives_a_header_band_argument_gives_a_title(macros: Any) -> None:
    """card draws subtitle, header_classes, dot_classes and header_aside only in the header band its
    title opens, so a call that gives them without a title loses them, and its page still answers 200."""
    band_calls = [
        (f"{path}:{call.lineno}", given)
        for path, source in dashboard_template_sources().items()
        for call in _card_calls(source)
        if (given := _given_parameters(call, macros.card.arguments)) & _HEADER_BAND_PARAMETERS
    ]
    assert band_calls, "read no card call that gives a header band argument, so this guard would pass vacuously"

    untitled = {site: sorted(given & _HEADER_BAND_PARAMETERS) for site, given in band_calls if "title" not in given}

    listing = "".join(f"\n  {site}: {', '.join(arguments)}" for site, arguments in untitled.items())
    assert untitled == {}, (
        f"These card calls give header band arguments but no title:{listing}\n"
        "card draws subtitle, header_classes, dot_classes and header_aside in the header band its title "
        "opens, and drops them without one. Give the call a title, or drop those arguments."
    )


class _StartTagClasses(HTMLParser):
    """Collects the classes of each start tag of an HTML text, in text order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.class_sets: list[frozenset[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.class_sets.append(_classes(dict(attrs)))


def _template_class_lists(source: str) -> list[frozenset[str]]:
    """The classes of each element of the Jinja template *source*'s literal markup, read with every
    Jinja tag blanked, then the words of each string its Jinja holds, such as a {% set %} value."""
    elements = _StartTagClasses()
    elements.feed("".join(value if kind == "data" else " " for _, kind, value in _JINJA.lex(source)))
    elements.close()
    constants = _JINJA.parse(source).find_all(nodes.Const)
    strings = [constant.value for constant in constants if isinstance(constant.value, str)]
    return [*elements.class_sets, *(frozenset(string.split()) for string in strings)]


def _script_class_lists(source: str) -> list[frozenset[str]]:
    """The words of each string literal of the script *source*."""
    return [frozenset(literal[1:-1].split()) for literal in _SCRIPT_STRING_LITERAL.findall(source)]


@pytest.mark.parametrize(
    "look",
    [
        pytest.param(_CARD_LOOK, id="card"),
        pytest.param(_PANEL_LOOK, id="panel"),
        pytest.param(_FLAT_CARD_LOOK, id="flat-card"),
        pytest.param(_SPLIT_CARD_TOP_LOOK, id="split-card-top"),
        pytest.param(_SPLIT_CARD_BOTTOM_LOOK, id="split-card-bottom"),
    ],
)
def test_each_card_looks_classes_are_written_once_in_the_dashboards_sources_in_components_macros_html(
    look: _Look,
) -> None:
    """One class list holds them all, in whatever order, so neither another template or script nor a
    macro built on the look's macro writes them again."""
    class_lists = {
        **{path: _template_class_lists(source) for path, source in dashboard_template_sources().items()},
        **{path: _script_class_lists(source) for path, source in dashboard_script_sources().items()},
    }

    written = {
        path: count for path, lists in class_lists.items() if (count := sum(map(look.draws, lists)))
    }

    listing = "".join(f"\n  {path}: {count}" for path, count in written.items())
    lacking = f", and none of '{' '.join(sorted(look.lacks))}'," if look.lacks else ""
    assert written == {_CARD_MACROS_KEY: 1}, (
        f"These dashboard sources write every class of the {look.macro} look, "
        f"'{' '.join(sorted(look.classes))}' in any order{lacking} in this many class lists:{listing}\n"
        f"Those classes are written once, in {_CARD_MACROS_KEY}'s {look.macro}, so a page draws "
        f"that look by calling {look.macro}."
    )
