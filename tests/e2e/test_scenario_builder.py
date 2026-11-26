"""End-to-end tests for the Scenario Builder page (/scenarios/builder)."""

import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest
import yaml
from playwright.sync_api import FloatRect, Locator, Page, Response, ViewportSize, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pytest_playwright import CreateContextCallback

from solar_challenge.config import load_fleet_config
from solar_challenge.fleet_distribution import write_distribution_spec
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_writer import fleet_scenario, scenario_yaml
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY
from solar_challenge.web.fleet_components import FLEET_COMPONENTS, days_window
from tests.e2e._alpine_start import open_once_alpine_has_started
from tests.e2e._css_transitions import finish_the_css_transitions
from tests.e2e._fetches_handled import (
    record_fetches_started_and_handled,
    wait_until_the_page_has_handled_every_fetch_it_started,
)
from tests.e2e._scenario_builder_page import open_builder, upload_scenario


# ── Page loading ─────────────────────────────────────────────────────


def test_builder_page_loads(page: Page, live_server: str) -> None:
    """GET /scenarios/builder returns a page with 'Scenario Builder' heading."""
    response = page.goto(live_server + "/scenarios/builder")
    assert response is not None
    assert response.status == 200

    page.wait_for_load_state("domcontentloaded")

    heading = page.locator("text=Scenario Builder").first
    expect(heading).to_be_visible()


# ── Bug B1: Alpine race condition with external JS ───────────────────


def test_builder_no_js_errors(
    page: Page, live_server: str, page_errors: list[str]
) -> None:
    """The scenario builder page should load without JS errors.

    The ``scenarioBuilder()`` component is defined in an external JS file
    loaded via ``defer`` in ``{% block head %}``.  Alpine.js may evaluate
    the ``x-data`` before the component function is registered, which
    throws an uncaught ReferenceError.

    It reads page_errors once the page has handled its presets and first-preview answers.
    """
    record_fetches_started_and_handled(page)
    open_once_alpine_has_started(page, live_server + "/scenarios/builder")
    wait_until_the_page_has_handled_every_fetch_it_started(page)

    assert page_errors == [], f"Errors on /scenarios/builder: {page_errors}"


# ── Accordion sections ───────────────────────────────────────────────


_ACCORDION_SECTIONS: dict[str, tuple[str, str]] = {
    "General": ("textbox", "Description"),
    "Period": ("textbox", "Start Date"),
    "Location": ("combobox", "Location Preset"),
    "Fleet Distribution": ("spinbutton", "Number of Homes"),
    "Tariff": ("spinbutton", "Import Rate (GBP/kWh)"),
}
"""The accordion's sections in page order, each by its header's name, with the role and name of one control its panel holds."""


def test_accordion_sections_exist(page: Page, live_server: str) -> None:
    """The accordion should have General, Period, Location, Fleet Distribution,
    and Tariff sections.
    """
    page.goto(live_server + "/scenarios/builder")

    for section_name in _ACCORDION_SECTIONS:
        expect(
            page.get_by_role("button", name=section_name, exact=True),
            f"Accordion section '{section_name}' should be visible",
        ).to_be_visible()


def _expect_expanded_headers(page: Page, open_section: str | None, *, message: str | None = None) -> None:
    """Expect the header of *open_section* to be exposed as expanded and every other section's header as collapsed; with None, every header as collapsed. A failure reports *message*, if given."""
    for section in _ACCORDION_SECTIONS:
        expect(page.get_by_role("button", name=section, exact=True, expanded=section == open_section), message).to_be_visible()


def test_only_the_open_sections_header_is_exposed_as_expanded(page: Page, live_server: str) -> None:
    """General's header alone is exposed as expanded when the page loads; opening Period moves that to Period's header, and closing Period leaves every header collapsed."""
    page.goto(live_server + "/scenarios/builder")
    _expect_expanded_headers(page, "General")

    _open_section(page, "Period")
    _expect_expanded_headers(page, "Period")

    page.get_by_role("button", name="Period", exact=True).click()
    _expect_expanded_headers(page, None)


def _sections_shown_with_javascript_off(new_context: CreateContextCallback, live_server: str) -> set[str]:
    """The sections of _ACCORDION_SECTIONS whose control the builder shows with JavaScript off, as it shows them until Alpine starts."""
    page = new_context(java_script_enabled=False).new_page()
    page.goto(live_server + "/scenarios/builder")
    return {
        section
        for section, (role, name) in _ACCORDION_SECTIONS.items()
        if page.get_by_role(role, name=name, exact=True).is_visible()
    }


def test_the_section_the_builder_shows_before_alpine_starts_is_the_one_it_opens(
    new_context: CreateContextCallback, page: Page, live_server: str
) -> None:
    """With JavaScript off, as until Alpine starts, the builder shows one section's control, and once Alpine has started that section's header alone is exposed as expanded, so no other section's panel shows while the page loads."""
    shown = _sections_shown_with_javascript_off(new_context, live_server)
    assert len(shown) == 1, f"with JavaScript off the builder shows the controls of {sorted(shown)}, not of exactly one section"
    (shown_section,) = shown

    page.goto(live_server + "/scenarios/builder")
    _expect_expanded_headers(
        page,
        shown_section,
        message=f"the builder shows {shown_section}'s control before Alpine starts, so {shown_section}'s header alone should be exposed as expanded once Alpine has",
    )


def _panel_id_of(page: Page, header: str) -> str:
    """The id the accordion header named *header* names in aria-controls, i.e. the id of that section's panel."""
    panel_id = page.get_by_role("button", name=header, exact=True).get_attribute("aria-controls")
    assert panel_id, f"the {header} header names no element in aria-controls"
    return panel_id


def _panel_of(page: Page, header: str) -> Locator:
    """The element the accordion header named *header* names in aria-controls, i.e. that section's panel."""
    return page.locator(f"id={_panel_id_of(page, header)}")


def _sections_whose_control_the_panel_holds(page: Page, header: str) -> set[str]:
    """The sections of _ACCORDION_SECTIONS whose control lies, shown or hidden, in the element the header named *header* names in aria-controls."""
    panel = _panel_of(page, header)
    return {
        section
        for section, (role, name) in _ACCORDION_SECTIONS.items()
        if panel.get_by_role(role, name=name, exact=True, include_hidden=True).count() > 0
    }


def test_each_section_header_controls_the_panel_that_holds_that_sections_controls(page: Page, live_server: str) -> None:
    """The element each accordion header names in aria-controls holds that section's control, shown or not, and no other section's."""
    page.goto(live_server + "/scenarios/builder")

    assert {header: _sections_whose_control_the_panel_holds(page, header) for header in _ACCORDION_SECTIONS} == {
        header: {header} for header in _ACCORDION_SECTIONS
    }


# ── YAML Preview pane ────────────────────────────────────────────────


def test_yaml_preview_visible(page: Page, live_server: str) -> None:
    """The YAML Preview pane in the right column should be visible.

    The preview heading is always rendered.  The ``<pre>`` element that
    displays the YAML text may be invisible when Alpine has not yet
    populated ``yamlPreview`` (the element collapses to zero height with
    empty text content).  We verify the heading is visible and that the
    ``<pre>`` element is attached to the DOM.
    """
    page.goto(live_server + "/scenarios/builder")

    yaml_heading = page.locator("h3", has_text="YAML Preview")
    expect(yaml_heading).to_be_visible()

    # The <pre> element that displays the YAML content should be in the DOM.
    # It may not be "visible" in the Playwright sense when Alpine hasn't
    # initialised scenarioBuilder() (external JS race condition) because
    # it would have empty text content and collapse to zero height.
    yaml_pre = page.locator("pre")
    expect(yaml_pre).to_be_attached()


# ── Download YAML button ─────────────────────────────────────────────


def test_download_yaml_button(page: Page, live_server: str) -> None:
    """The 'Download YAML' button exists and is clickable."""
    page.goto(live_server + "/scenarios/builder")

    download_btn = page.locator("button", has_text="Download YAML")
    expect(download_btn).to_be_visible()
    expect(download_btn).to_be_enabled()


# ── Form controls: each caption names its control ────────────────────


_ACCORDION_STATE = """({ opened, closed }) => {
    const panel = (id) => document.getElementById(id);
    const { scrollHeight, clientHeight } = panel(opened);
    return { displayed: [opened, ...closed].filter((id) => panel(id).checkVisibility()), scrollHeight, clientHeight };
}"""
"""The state of the accordion with the panel whose id is *opened* open and the panels whose ids are *closed* closed: the ids of those panels that are displayed (checkVisibility()), *opened* first and then *closed* in its order, and the opened panel's scrollHeight and clientHeight."""

_ACCORDION_IS_AT_REST = f"""(accordion) => {{
    const {{ displayed, scrollHeight, clientHeight }} = ({_ACCORDION_STATE})(accordion);
    return displayed.length === 1 && displayed[0] === accordion.opened && scrollHeight <= clientHeight;
}}"""
"""Whether the accordion is at rest, judged on the state _ACCORDION_STATE reads: the opened panel alone is displayed, no closed panel being displayed, as a panel is once it has finished closing, and the opened panel is tall enough to show all of its content, as a panel is once it has finished opening."""


def _accordion_with_open(page: Page, section: str) -> dict[str, str | list[str]]:
    """The argument of _ACCORDION_STATE and _ACCORDION_IS_AT_REST for the accordion with *section* open: the id of *section*'s panel and the ids of every other section's."""
    return {
        "opened": _panel_id_of(page, section),
        "closed": [_panel_id_of(page, other) for other in _ACCORDION_SECTIONS if other != section],
    }


def _open_section(page: Page, section: str, *, rest_timeout_ms: float | None = None) -> None:
    """Open the accordion section whose header button is named *section*, closing the open one, and return once the accordion is at rest: *section*'s panel shows all of its content and every other section's panel is hidden.

    *section* must be closed, as every section but General is when the page loads: a click on an open section's header closes it. Until the accordion is at rest, the headers and controls below a growing or shrinking panel are still moving, so a click on one can miss. It waits for rest in real time rather than finishing the CSS transitions; test_finishing_the_css_transitions_leaves_a_closing_accordion_panel_displayed says why.

    *rest_timeout_ms*, if given, bounds only the wait for rest, in milliseconds: the click and the panel-id reads keep the page's default timeout and the header check keeps expect's own, so a click slowed by a loaded host cannot fail a caller that expects the wait to time out.
    """
    header = page.get_by_role("button", name=section, exact=True, expanded=False)
    expect(
        header,
        f"the {section} header should be exposed as collapsed before _open_section clicks it "
        "(Alpine binds its aria-expanded, and a click on an open section's header closes it)",
    ).to_be_visible()
    accordion = _accordion_with_open(page, section)
    header.click()
    try:
        page.wait_for_function(_ACCORDION_IS_AT_REST, arg=accordion, timeout=rest_timeout_ms)
    except PlaywrightTimeoutError as timeout:
        state = page.evaluate(_ACCORDION_STATE, accordion)
        raise AssertionError(
            f"the accordion did not come to rest after opening {section}: "
            f"the state _ACCORDION_STATE reads, which _ACCORDION_IS_AT_REST judges, is {state}"
        ) from timeout


@pytest.mark.parametrize(
    "stretched_panel",
    [pytest.param("closing", id="closing_panel_stretched"), pytest.param("opening", id="opening_panel_stretched")],
)
def test_opening_a_section_returns_with_the_accordion_at_rest(page: Page, live_server: str, stretched_panel: str) -> None:
    """When _open_section returns, Playwright shows only the panel of the section it opened, laid out as tall as its content to within half a pixel, so the next click meets no header or control still moving.

    The *stretched_panel*, the closing one (that of the section open when the page loads) or the opening one (that of the section the test opens), is made to take 3 s to move, far longer than the accordion's own transition. With the closing panel stretched, a helper that returns while that panel is still displayed is caught by `shown`. With the opening panel stretched, a helper that returns while that panel is still growing is caught by the height read. Either is caught by any read within 3 s of the click, not only by one that beats the transition.
    """
    section_open_on_load = "General"
    section_to_open = "Period"
    stretched_section = {"closing": section_open_on_load, "opening": section_to_open}[stretched_panel]
    page.goto(live_server + "/scenarios/builder")
    _expect_expanded_headers(
        page,
        section_open_on_load,
        message=f"the test takes {section_open_on_load}'s panel to be the closing one, so {section_open_on_load}'s header alone should be exposed as expanded when the page loads",
    )
    panels = {section: _panel_of(page, section) for section in _ACCORDION_SECTIONS}
    page.add_style_tag(content=f"#{_panel_id_of(page, stretched_section)} {{ transition-duration: 3s !important; }}")
    _open_section(page, section_to_open)

    shown = {section for section, panel in panels.items() if panel.is_visible()}
    opened_height = _layout_box(panels[section_to_open])["height"]
    opened_scroll_height = panels[section_to_open].evaluate("panel => panel.scrollHeight")

    assert (shown, opened_height) == ({section_to_open}, pytest.approx(opened_scroll_height, abs=0.5))


def test_open_section_fails_reporting_the_accordion_state_its_wait_judged(page: Page, live_server: str) -> None:
    """When the accordion does not come to rest, here because General's panel is kept displayed after Period opens, _open_section fails reporting the state _ACCORDION_STATE reads, the state _ACCORDION_IS_AT_REST judged."""
    page.goto(live_server + "/scenarios/builder")
    page.add_style_tag(content=f"#{_panel_id_of(page, 'General')} {{ display: block !important; }}")

    with pytest.raises(AssertionError) as failure:
        _open_section(page, "Period", rest_timeout_ms=5000)

    state = page.evaluate(_ACCORDION_STATE, _accordion_with_open(page, "Period"))
    assert str(state) in str(failure.value)


_BUSY_ON_MOUSEDOWN = """(element, busyMs) => element.addEventListener('mousedown', () => {
    const until = performance.now() + busyMs;
    while (performance.now() < until) {}
    element.dataset.busyHandled = 'true';
}, { once: true })"""
"""Keeps the page's main thread busy for *busyMs* milliseconds the next time *element* takes a mousedown, as a loaded host's renderer is busy, so a click on *element* is not done until then; the handler then sets *element*'s data-busy-handled attribute to "true", so a test can see that the click met it."""


def test_a_click_that_outlasts_open_sections_rest_timeout_still_lands_and_its_wait_for_rest_fails(page: Page, live_server: str) -> None:
    """rest_timeout_ms bounds only _open_section's wait for rest: a click whose handling keeps the page busy for twice that bound still lands, opening Period, and _open_section then fails because the accordion does not come to rest, not because of the click."""
    page.goto(live_server + "/scenarios/builder")
    page.add_style_tag(content=f"#{_panel_id_of(page, 'General')} {{ display: block !important; }}")
    period_header = page.get_by_role("button", name="Period", exact=True)
    period_header.evaluate(_BUSY_ON_MOUSEDOWN, 2000)

    with pytest.raises(AssertionError) as failure:
        _open_section(page, "Period", rest_timeout_ms=1000)

    assert isinstance(failure.value.__cause__, PlaywrightTimeoutError), (
        f"_open_section should have failed in its wait for rest, an AssertionError raised from the wait's PlaywrightTimeoutError, but it failed with: {failure.value}"
    )
    expect(
        period_header,
        "the click should have run _BUSY_ON_MOUSEDOWN's handler on the Period header; if it did not, the click was not held up and this test cannot tell whether rest_timeout_ms wrongly bounds it",
    ).to_have_attribute("data-busy-handled", "true")
    expect(page.get_by_role("button", name="Period", exact=True, expanded=True)).to_be_visible()


_A_HEIGHT_TRANSITION_RUNS_ON = """(panelId) => document.getAnimations().some((animation) =>
    animation instanceof CSSTransition && animation.transitionProperty === 'height' && animation.effect.target.id === panelId
)"""
"""Whether a CSS transition of height runs on the element whose id is *panelId*, as one does on a panel x-collapse is opening or closing."""

_MARK_THE_END_OF_ITS_HEIGHT_TRANSITION = """(panel) => panel.addEventListener('transitionend', (event) => {
    if (event.target === panel && event.propertyName === 'height') panel.dataset.heightTransitionEnded = 'true';
})"""
"""Sets *panel*'s data-height-transition-ended attribute to "true" once the browser has dispatched the transitionend of *panel*'s height transition, the event an x-collapse that hid a closing panel when its transition ended would hide it on."""


def test_finishing_the_css_transitions_leaves_a_closing_accordion_panel_displayed(page: Page, live_server: str) -> None:
    """x-collapse hides a closing panel from the end callback of Alpine's own transition timer, not when its CSS transition ends, so finishing the transitions, as the suite's other settled reads do, cannot bring the accordion to rest, and _open_section waits for rest in real time.

    General's panel, the closing one, is made to take 600 s to close, which makes Alpine's timer as long, so the timer cannot hide the panel during the test. The accordion is read once the browser has dispatched the transitionend of that panel's finished height transition, so the test fails once x-collapse hides the panel when its transition ends; _open_section could then finish the transitions instead.
    """
    page.goto(live_server + "/scenarios/builder")
    _expect_expanded_headers(
        page,
        "General",
        message="the test takes General's panel to be the closing one, so General's header alone should be exposed as expanded when the page loads",
    )
    general_panel_id = _panel_id_of(page, "General")
    general_panel = page.locator(f"id={general_panel_id}")
    accordion = _accordion_with_open(page, "Period")
    page.add_style_tag(content=f"#{general_panel_id} {{ transition-duration: 600s !important; }}")
    page.get_by_role("button", name="Period", exact=True, expanded=False).click()
    page.wait_for_function(_A_HEIGHT_TRANSITION_RUNS_ON, arg=general_panel_id)
    general_panel.evaluate(_MARK_THE_END_OF_ITS_HEIGHT_TRANSITION)

    finish_the_css_transitions(page)
    expect(
        general_panel,
        "the browser should dispatch the transitionend of General's panel once its height transition is finished",
    ).to_have_attribute("data-height-transition-ended", "true")

    assert page.evaluate(_ACCORDION_STATE, accordion)["displayed"] == [accordion["opened"], general_panel_id]


def _form_sent_on_validate(page: Page) -> dict[str, Any]:
    """Click Validate and return the form the builder sends to /api/scenarios/validate."""
    with page.expect_response("**/api/scenarios/validate") as validated:
        page.get_by_role("button", name="Validate", exact=True).click()
    return validated.value.request.post_data_json


def test_general_section_textboxes_set_the_name_and_description_the_builder_sends(
    page: Page, live_server: str
) -> None:
    """The textboxes named Scenario Name and Description, which the General section shows when the page opens, set the name and description of the form the builder sends."""
    page.goto(live_server + "/scenarios/builder")

    page.get_by_role("textbox", name="Scenario Name", exact=True).fill("Bristol Phase 1")
    page.get_by_role("textbox", name="Description", exact=True).fill("First 100 homes")

    sent = _form_sent_on_validate(page)

    assert (sent["name"], sent["description"]) == ("Bristol Phase 1", "First 100 homes")


_SECTION_CONTROLS = (
    pytest.param("Period", "textbox", "Start Date", "start_date", "2024-06-01", id="start_date"),
    pytest.param("Period", "textbox", "End Date", "end_date", "2024-06-30", id="end_date"),
    pytest.param(
        "Fleet Distribution", "spinbutton", "Number of Homes", "n_homes", "12", id="n_homes"
    ),
    pytest.param(
        "Tariff", "spinbutton", "Import Rate (GBP/kWh)", "import_rate", "0.3", id="import_rate"
    ),
    pytest.param(
        "Tariff",
        "spinbutton",
        "SEG Export Rate (p/kWh)",
        "seg_rate_pence_per_kwh",
        "5.5",
        id="seg_rate_pence_per_kwh",
    ),
)
"""(accordion section, role, caption, form field, value typed) of a control the sections show; every value differs from the form's default."""


@pytest.mark.parametrize(("section", "role", "caption", "field", "value"), _SECTION_CONTROLS)
def test_section_control_named_by_its_caption_sets_its_field_of_the_form_the_builder_sends(
    page: Page, live_server: str, section: str, role: str, caption: str, field: str, value: str
) -> None:
    """The control with *role* named *caption* in *section* sets *field* of the form the builder sends to the value typed into it."""
    page.goto(live_server + "/scenarios/builder")
    _open_section(page, section)

    page.get_by_role(role, name=caption, exact=True).fill(value)

    assert _form_sent_on_validate(page)[field] == value


def test_a_freshly_opened_builder_sends_no_seg_rate(page: Page, live_server: str) -> None:
    """A freshly opened builder shows and sends an empty SEG export rate."""
    page.goto(live_server + "/scenarios/builder")
    _open_section(page, "Tariff")

    assert page.get_by_role("spinbutton", name="SEG Export Rate (p/kWh)", exact=True).input_value() == ""
    assert _form_sent_on_validate(page)["seg_rate_pence_per_kwh"] == ""


def _run_sent_by_a_freshly_opened_simulate_page(
    page: Page, url: str, run_button: str, submission: str
) -> dict[str, Any]:
    """Open the simulate page at *url*, click its button named *run_button* and return the body of the run it POSTs to the route glob *submission*, aborted so no job reaches the live server's JobManager."""
    page.route(submission, lambda route: route.abort())
    page.goto(url)
    with page.expect_request(submission) as sent:
        page.get_by_role("button", name=run_button, exact=True).click()
    return sent.value.post_data_json


def test_the_builder_starts_with_no_seg_as_the_home_and_fleet_pages_do(page: Page, live_server: str) -> None:
    """Freshly opened, the home and fleet pages run with no seg block, and the builder previews a scenario whose seg: block is null."""
    home_run = _run_sent_by_a_freshly_opened_simulate_page(
        page, live_server + "/simulate/home", "Run Simulation", "**/api/simulate/home"
    )
    fleet_run = _run_sent_by_a_freshly_opened_simulate_page(
        page, live_server + "/simulate/fleet", "Run Fleet Simulation", "**/api/simulate/fleet-from-distribution"
    )
    builder_scenario = yaml.safe_load(open_builder(page, live_server).json()["yaml"])

    assert {
        "home": home_run.get("seg"),
        "fleet": fleet_run.get("seg"),
        "builder": builder_scenario["seg"],
    } == {"home": None, "fleet": None, "builder": None}


def test_custom_location_controls_named_by_their_captions_set_the_location_the_builder_sends(
    page: Page, live_server: str
) -> None:
    """Choosing Custom Location in the combobox named Location Preset shows the spinbuttons Latitude, Longitude and Altitude (m), which set the location of the form the builder sends."""
    page.goto(live_server + "/scenarios/builder")
    _open_section(page, "Location")

    page.get_by_role("combobox", name="Location Preset", exact=True).select_option(
        label="Custom Location"
    )
    page.get_by_role("spinbutton", name="Latitude", exact=True).fill("53.4")
    page.get_by_role("spinbutton", name="Longitude", exact=True).fill("-2.2")
    page.get_by_role("spinbutton", name="Altitude (m)", exact=True).fill("38")

    sent = _form_sent_on_validate(page)

    assert {key: sent[key] for key in ("location_preset", "latitude", "longitude", "altitude")} == {
        "location_preset": "custom",
        "latitude": "53.4",
        "longitude": "-2.2",
        "altitude": "38",
    }


class _Card(NamedTuple):
    """A distribution card: its heading, its block and its spec's key in the body the builder sends, a fixed value that differs from the one the card starts at and lies within its range, and the value its add buttons start a new row at."""

    heading: str
    key: str
    grammar_key: str
    non_default_fixed_value: float
    new_row_value: float


_CARDS = (
    _Card("PV Capacity (kW)", "pv", "capacity_kw", 6.5, 4.0),
    _Card("Battery Capacity (kWh)", "battery", "capacity_kwh", 9.5, 5.0),
    _Card("Annual Consumption (kWh)", "load", "annual_consumption_kwh", 4200, 3500),
)

_CARD_PARAMS = tuple(pytest.param(card, id=card.key) for card in _CARDS)


def _spec_sent(sent: dict[str, Any], card: _Card) -> Any:
    """*card*'s spec in the body *sent*: its block's spec, the grammar's own."""
    return sent[card.key][card.grammar_key]


def _start_spec(card: _Card, name: str) -> Any:
    """*card*'s component's start spec of the editor type named *name*, written as the grammar reads it."""
    (written,) = [
        written
        for written in (write_distribution_spec(spec) for spec in FLEET_COMPONENTS[card.key].start.specs)
        if isinstance(written, dict) and written["type"] == name
    ]
    return written


@pytest.mark.parametrize("card", _CARD_PARAMS)
def test_distribution_card_is_a_group_whose_controls_named_by_their_captions_set_its_distribution(
    page: Page, live_server: str, card: _Card
) -> None:
    """The group named by a distribution card's heading holds that heading, and one combobox, Distribution Type.

    Choosing Normal (Gaussian) there shows four spinbuttons, Mean, Std Dev, Min (clamp) and Max (clamp),
    which set that card's fields of the form the builder sends, as numbers.
    """
    page.goto(live_server + "/scenarios/builder")
    _open_section(page, "Fleet Distribution")

    card_group = page.get_by_role("group", name=card.heading, exact=True)
    expect(card_group.get_by_role("combobox")).to_have_count(1)
    expect(card_group.get_by_role("heading", name=card.heading, exact=True)).to_be_visible()
    card_group.get_by_role("combobox", name="Distribution Type", exact=True).select_option(
        label="Normal (Gaussian)"
    )
    for caption, value in {"Mean": "7", "Std Dev": "3", "Min (clamp)": "1", "Max (clamp)": "9"}.items():
        card_group.get_by_role("spinbutton", name=caption, exact=True).fill(value)
    expect(card_group.get_by_role("spinbutton")).to_have_count(4)

    sent = _form_sent_on_validate(page)

    assert sent[card.key] == {card.grammar_key: {"type": "normal", "mean": 7, "std": 3, "min": 1, "max": 9}}


@pytest.mark.parametrize("card", _CARD_PARAMS)
def test_a_card_at_fixed_value_shows_one_spinbutton_named_fixed_value_that_sets_its_spec(
    page: Page, live_server: str, card: _Card
) -> None:
    """Choosing Fixed Value shows one spinbutton in the card's group, named Fixed Value, which sets the card's spec of the form the builder sends to the number alone."""
    page.goto(live_server + "/scenarios/builder")
    _open_section(page, "Fleet Distribution")
    card_group = page.get_by_role("group", name=card.heading, exact=True)
    card_group.get_by_role("combobox", name="Distribution Type", exact=True).select_option(label="Fixed Value")
    fixed_value = card_group.get_by_role("spinbutton", name="Fixed Value", exact=True)

    expect(fixed_value).to_have_count(1)
    expect(card_group.get_by_role("spinbutton")).to_have_count(1)
    fixed_value.fill(str(card.non_default_fixed_value))

    assert _spec_sent(_form_sent_on_validate(page), card) == card.non_default_fixed_value


def test_a_card_at_uniform_shows_two_spinbuttons_min_and_max_that_set_its_range(page: Page, live_server: str) -> None:
    """Choosing Uniform in a card's Distribution Type shows two spinbuttons in its group, Min and Max, which set the card's min and max of the form the builder sends."""
    page.goto(live_server + "/scenarios/builder")
    _open_section(page, "Fleet Distribution")
    card_group = page.get_by_role("group", name="PV Capacity (kW)", exact=True)

    card_group.get_by_role("combobox", name="Distribution Type", exact=True).select_option(label="Uniform")
    card_group.get_by_role("spinbutton", name="Min", exact=True).fill("2.5")
    card_group.get_by_role("spinbutton", name="Max", exact=True).fill("7.5")
    expect(card_group.get_by_role("spinbutton")).to_have_count(2)

    sent = _form_sent_on_validate(page)

    assert _spec_sent(sent, _CARDS[0]) == {"type": "uniform", "min": 2.5, "max": 7.5}


def _layout_box(control: Locator) -> FloatRect:
    """The box *control* is laid out in."""
    box = control.bounding_box()
    assert box is not None, "the control has no layout box"
    return box


_PHONE_VIEWPORT: ViewportSize = {"width": 375, "height": 800}
"""The viewport of a phone."""


def test_choosing_weighted_discrete_on_a_phone_does_not_widen_the_distribution_type_combobox(
    page: Page, live_server: str
) -> None:
    """At phone width, choosing Weighted Discrete leaves the Distribution Type combobox as wide as it was, to within half a pixel.

    The rows Weighted Discrete shows are wider than the card, and a fieldset is as wide as
    its content unless it resets that, which would widen the combobox beyond the card's edge.
    """
    page.set_viewport_size(_PHONE_VIEWPORT)
    page.goto(live_server + "/scenarios/builder")
    _open_section(page, "Fleet Distribution")
    card_group = page.get_by_role("group", name="PV Capacity (kW)", exact=True)
    distribution_type = card_group.get_by_role("combobox", name="Distribution Type", exact=True)
    expect(distribution_type).to_be_visible()
    width_before = _layout_box(distribution_type)["width"]

    distribution_type.select_option(label="Weighted Discrete")
    expect(card_group.get_by_role("button", name="Add Row", exact=True)).to_be_visible()

    assert _layout_box(distribution_type)["width"] == pytest.approx(width_before, abs=0.5)


# ── Distribution cards: the fields and rows each card sends ──────────


def _choose_in_every_card(page: Page, distribution_type: str) -> None:
    """Open Fleet Distribution and choose *distribution_type* in every card's Distribution Type combobox."""
    _open_section(page, "Fleet Distribution")
    for card in _CARDS:
        page.get_by_role("group", name=card.heading, exact=True).get_by_role(
            "combobox", name="Distribution Type", exact=True
        ).select_option(label=distribution_type)


def test_each_card_opens_at_its_components_start_which_the_builder_sends_as_the_grammars_spec(
    page: Page, live_server: str
) -> None:
    """Every card opens at the fleet page's distribution, its component's start, and the form the builder previews on opening gives each card's block as that spec, written as the grammar reads it."""
    sent = open_builder(page, live_server).request.post_data_json

    assert {card.key: sent[card.key] for card in _CARDS} == {
        card.key: {card.grammar_key: _start_spec(card, FLEET_COMPONENTS[card.key].start.shown)} for card in _CARDS
    }


@pytest.mark.parametrize(
    ("distribution_type", "type_value"),
    [
        pytest.param("Normal (Gaussian)", "normal", id="normal"),
        pytest.param("Uniform", "uniform", id="uniform"),
        pytest.param("Weighted Discrete", "weighted_discrete", id="weighted_discrete"),
        pytest.param("Shuffled Pool", "shuffled_pool", id="shuffled_pool"),
    ],
)
def test_a_card_set_to_a_distribution_sends_its_start_spec_of_that_type(
    page: Page, live_server: str, distribution_type: str, type_value: str
) -> None:
    """With *distribution_type* chosen in every card, the form the builder sends gives each card its start's spec of that type, and only the keys that type reads."""
    page.goto(live_server + "/scenarios/builder")
    _choose_in_every_card(page, distribution_type)

    sent = _form_sent_on_validate(page)

    assert {card.key: _spec_sent(sent, card) for card in _CARDS} == {
        card.key: _start_spec(card, type_value) for card in _CARDS
    }


class _RowList(NamedTuple):
    """A distribution the cards hold as rows: its Distribution Type option, the key of the list paired with its values, and that list's caption."""

    distribution_type: str
    paired_key: str
    column_caption: str


_WEIGHTED_ROWS = _RowList("Weighted Discrete", "weights", "Weight")
_POOL_ROWS = _RowList("Shuffled Pool", "counts", "Count")
_ROW_LISTS = (
    pytest.param(_WEIGHTED_ROWS, id="weighted_discrete"),
    pytest.param(_POOL_ROWS, id="shuffled_pool"),
)


def _rows_sent(sent: dict[str, Any], card: _Card, row_list: _RowList) -> list[tuple[Any, Any]]:
    """*card*'s rows in the body *sent*: each value with the entry of its paired list, in order."""
    spec = _spec_sent(sent, card)
    return list(zip(spec["values"], spec[row_list.paired_key], strict=True))


def _with_rows(sent: dict[str, Any], card: _Card, row_list: _RowList, rows: list[tuple[Any, Any]]) -> dict[str, Any]:
    """The body *sent* with *card*'s spec holding *rows*, as its values and paired lists."""
    values, paired = ([row[0] for row in rows], [row[1] for row in rows])
    spec = {**_spec_sent(sent, card), "values": values, row_list.paired_key: paired}
    return {**sent, card.key: {card.grammar_key: spec}}

_REMOVE_ROW_BUTTONS = re.compile(r"^Remove Row \d+$")
"""The names of a card's remove buttons: Remove Row and the number of the row it removes, counted from 1 within the card."""


@pytest.mark.parametrize("row_list", _ROW_LISTS)
@pytest.mark.parametrize("card", _CARD_PARAMS)
def test_a_cards_add_and_remove_buttons_change_only_its_rows(
    page: Page, live_server: str, card: _Card, row_list: _RowList
) -> None:
    """With every card showing its rows, a card's add button appends a row holding the card's new-row value and 10, and its Remove Row 1 button then removes its first row.

    The card shows each change, and no other field of the form the builder sends changes.
    """
    page.goto(live_server + "/scenarios/builder")
    _choose_in_every_card(page, row_list.distribution_type)
    card_group = page.get_by_role("group", name=card.heading, exact=True)
    sent_before = _form_sent_on_validate(page)
    rows = _rows_sent(sent_before, card, row_list)
    new_row = (card.new_row_value, 10)

    card_group.get_by_role("button", name="Add Row", exact=True).click()
    expect(card_group.get_by_role("spinbutton")).to_have_count(2 * (len(rows) + 1))
    assert _form_sent_on_validate(page) == _with_rows(sent_before, card, row_list, [*rows, new_row])

    card_group.get_by_role("button", name="Remove Row 1", exact=True).click()
    expect(card_group.get_by_role("spinbutton")).to_have_count(2 * len(rows))
    assert _form_sent_on_validate(page) == _with_rows(sent_before, card, row_list, [*rows[1:], new_row])


@pytest.mark.parametrize("row_list", _ROW_LISTS)
def test_a_cards_last_row_has_no_remove_button(page: Page, live_server: str, row_list: _RowList) -> None:
    """Removing each card's first row until one is left leaves that row without a remove button, and the form the builder sends keeps it."""
    page.goto(live_server + "/scenarios/builder")
    _choose_in_every_card(page, row_list.distribution_type)
    sent_before = _form_sent_on_validate(page)
    rows_before = {card.key: _rows_sent(sent_before, card, row_list) for card in _CARDS}
    assert all(len(rows) > 1 for rows in rows_before.values()), (
        f"every card must open with more than one row, or the test removes none: {rows_before}"
    )

    for card in _CARDS:
        card_group = page.get_by_role("group", name=card.heading, exact=True)
        for remaining in range(len(rows_before[card.key]) - 1, 0, -1):
            card_group.get_by_role("button", name="Remove Row 1", exact=True).click()
            expect(card_group.get_by_role("spinbutton")).to_have_count(2 * remaining)
        expect(card_group.get_by_role("button", name=_REMOVE_ROW_BUTTONS)).to_have_count(0)

    sent_after = _form_sent_on_validate(page)
    assert {card.key: _rows_sent(sent_after, card, row_list) for card in _CARDS} == {
        key: rows[-1:] for key, rows in rows_before.items()
    }


@pytest.mark.parametrize("row_list", _ROW_LISTS)
@pytest.mark.parametrize("card", _CARD_PARAMS)
def test_a_cards_rows_have_spinbuttons_named_for_their_row_that_set_that_row(
    page: Page, live_server: str, card: _Card, row_list: _RowList
) -> None:
    """With every card showing its rows, row n of a card has two spinbuttons in its group, Value n and Weight n (or Count n), which set row n of the rows the builder sends."""
    page.goto(live_server + "/scenarios/builder")
    _choose_in_every_card(page, row_list.distribution_type)
    card_group = page.get_by_role("group", name=card.heading, exact=True)
    sent_before = _form_sent_on_validate(page)
    typed = [(100 + n, n) for n in range(1, len(_rows_sent(sent_before, card, row_list)) + 1)]
    expect(card_group.get_by_role("spinbutton")).to_have_count(2 * len(typed))

    for n, (value, paired) in enumerate(typed, start=1):
        card_group.get_by_role("spinbutton", name=f"Value {n}", exact=True).fill(str(value))
        card_group.get_by_role("spinbutton", name=f"{row_list.column_caption} {n}", exact=True).fill(str(paired))

    assert _form_sent_on_validate(page) == _with_rows(sent_before, card, row_list, typed)


def _expect_remove_buttons_numbered(card_group: Locator, rows: int) -> None:
    """Expect *card_group* to show *rows* remove buttons, named Remove Row 1 to Remove Row <rows> in order."""
    remove_buttons = card_group.get_by_role("button", name=_REMOVE_ROW_BUTTONS)
    expect(remove_buttons).to_have_count(rows)
    for n in range(1, rows + 1):
        expect(remove_buttons.nth(n - 1)).to_have_accessible_name(f"Remove Row {n}")


@pytest.mark.parametrize("row_list", _ROW_LISTS)
@pytest.mark.parametrize("card", _CARD_PARAMS)
def test_a_cards_remove_row_n_button_removes_row_n_and_the_rows_after_it_are_renumbered(
    page: Page, live_server: str, card: _Card, row_list: _RowList
) -> None:
    """With every card showing its rows, each of a card's rows has a remove button named for it; Remove Row 2 removes the second row alone, and the rows after it take the numbers before theirs."""
    page.goto(live_server + "/scenarios/builder")
    _choose_in_every_card(page, row_list.distribution_type)
    card_group = page.get_by_role("group", name=card.heading, exact=True)
    sent_before = _form_sent_on_validate(page)
    rows = _rows_sent(sent_before, card, row_list)
    assert len(rows) > 2, f"the card must open with more than two rows, or Remove Row 2 renumbers none: {rows}"
    _expect_remove_buttons_numbered(card_group, len(rows))

    card_group.get_by_role("button", name="Remove Row 2", exact=True).click()

    _expect_remove_buttons_numbered(card_group, len(rows) - 1)
    assert _form_sent_on_validate(page) == _with_rows(sent_before, card, row_list, [rows[0], *rows[2:]])


def test_a_cards_shuffled_pool_shows_the_total_of_its_counts(page: Page, live_server: str) -> None:
    """With Shuffled Pool chosen in every card, each card shows the total of its counts, and changing one card's count changes that card's total alone."""
    page.goto(live_server + "/scenarios/builder")
    _choose_in_every_card(page, "Shuffled Pool")
    sent = _form_sent_on_validate(page)
    totals = {card.heading: sum(_spec_sent(sent, card)["counts"]) for card in _CARDS}
    card_groups = {card.heading: page.get_by_role("group", name=card.heading, exact=True) for card in _CARDS}
    for heading, card_group in card_groups.items():
        expect(card_group.get_by_text("Total:")).to_have_text(f"Total: {totals[heading]} homes")

    pv_heading = _CARDS[0].heading
    first_count = card_groups[pv_heading].get_by_role("spinbutton", name="Count 1", exact=True)
    first_count.fill(str(int(first_count.input_value()) + 7))

    for heading, card_group in card_groups.items():
        total = totals[heading] + (7 if heading == pv_heading else 0)
        expect(card_group.get_by_text("Total:")).to_have_text(f"Total: {total} homes")


def _phone_card_groups_with_rows(page: Page, live_server: str, row_list: _RowList) -> dict[str, Locator]:
    """Open the builder at phone width with *row_list*'s distribution chosen in every card, and return each card's group by its heading, once each shows its add button."""
    page.set_viewport_size(_PHONE_VIEWPORT)
    page.goto(live_server + "/scenarios/builder")
    _choose_in_every_card(page, row_list.distribution_type)
    card_groups = {card.heading: page.get_by_role("group", name=card.heading, exact=True) for card in _CARDS}
    for card_group in card_groups.values():
        expect(card_group.get_by_role("button", name="Add Row", exact=True)).to_be_visible()
    return card_groups


def _controls_outside(card_group: Locator) -> list[str]:
    """The comboboxes, spinbuttons and buttons *card_group* shows whose box leaves the group's by more than half a pixel, each as its role, its number among those of its role, and its left and right edges."""
    group = _layout_box(card_group)
    left, right = group["x"], group["x"] + group["width"]
    outside = []
    for role in ("combobox", "spinbutton", "button"):
        for number, control in enumerate(card_group.get_by_role(role).all(), start=1):
            box = _layout_box(control)
            if box["x"] < left - 0.5 or box["x"] + box["width"] > right + 0.5:
                outside.append(f"{role} {number} spans x={box['x']:.1f} to {box['x'] + box['width']:.1f}")
    return outside


@pytest.mark.parametrize("row_list", _ROW_LISTS)
def test_on_a_phone_every_control_a_card_shows_with_its_rows_lies_within_the_card(
    page: Page, live_server: str, row_list: _RowList
) -> None:
    """At 375 px wide, with every card showing its rows, each combobox, spinbutton and button a card's group shows lies within the group's box, to within half a pixel."""
    card_groups = _phone_card_groups_with_rows(page, live_server, row_list)

    assert {heading: _controls_outside(card_group) for heading, card_group in card_groups.items()} == {
        heading: [] for heading in card_groups
    }


def _columns_out_of_line(card_group: Locator, captions: tuple[str, ...]) -> list[str]:
    """The columns of *card_group*, each named by its caption, whose spinbutton in the second row starts more than half a pixel from the first row's, each as its caption and the two left edges."""
    out_of_line = []
    for caption in captions:
        first, second = (
            _layout_box(card_group.get_by_role("spinbutton", name=f"{caption} {row}", exact=True))["x"]
            for row in (1, 2)
        )
        if abs(second - first) > 0.5:
            out_of_line.append(f"{caption} 1 starts at x={first:.1f} and {caption} 2 at x={second:.1f}")
    return out_of_line


@pytest.mark.parametrize("row_list", _ROW_LISTS)
def test_on_a_phone_a_cards_second_row_starts_each_column_where_its_first_row_does(
    page: Page, live_server: str, row_list: _RowList
) -> None:
    """At 375 px wide, with every card showing its rows, a card's second row starts its Value column and its Weight (or Count) column where its first row does, to within half a pixel.

    Only the first row shows the captions, above its spinbuttons, so the columns must stay
    in line with the rows below it, which show none.
    """
    card_groups = _phone_card_groups_with_rows(page, live_server, row_list)

    assert {
        heading: _columns_out_of_line(card_group, ("Value", row_list.column_caption))
        for heading, card_group in card_groups.items()
    } == {heading: [] for heading in card_groups}


# ── Builder YAML: what the scenario loaders read ─────────────────────


def test_default_form_previews_yaml_the_fleet_loader_loads(
    page: Page, live_server: str, tmp_path: Path
) -> None:
    """The YAML previewed for the builder's default form loads through load_fleet_config, its PV the start's shuffled pool, and has no SEG.

    The page previews its default form as soon as it opens, so this pins the real
    payload of getFormData(), which
    tests/unit/test_web_scenarios.py::TestBuilderScenarioYaml's _DEFAULT_FORM mirrors.
    """
    response = open_builder(page, live_server)
    assert response.status == 200
    yaml_text = response.json()["yaml"]
    path = tmp_path / "builder.yaml"
    path.write_text(yaml_text, encoding="utf-8")

    fleet = load_fleet_config(path)

    pool = _start_spec(_CARDS[0], "shuffled_pool")
    assert Counter(home.pv_config.capacity_kw for home in fleet.homes) == dict(
        zip(pool["values"], pool["counts"], strict=True)
    )
    assert yaml.safe_load(yaml_text)["seg"] is None


def _form_previewed_after(page: Page, action: Callable[[], None]) -> dict[str, Any]:
    """Run *action* and return the form of the preview the builder requests after it."""
    with page.expect_response("**/api/scenarios/preview-yaml") as previewed:
        action()
    return previewed.value.request.post_data_json


def test_each_edit_to_a_cards_distribution_previews_the_form_with_that_edit(page: Page, live_server: str) -> None:
    """Choosing a card's distribution type, typing in one of its rows, adding a row and removing one each make the builder preview the form with that edit."""
    open_builder(page, live_server)
    _open_section(page, "Fleet Distribution")
    pv = _CARDS[0]
    card_group = page.get_by_role("group", name=pv.heading, exact=True)

    chosen = _form_previewed_after(
        page,
        lambda: card_group.get_by_role("combobox", name="Distribution Type", exact=True).select_option(
            label="Weighted Discrete"
        ),
    )
    rows = _rows_sent(chosen, pv, _WEIGHTED_ROWS)
    typed = _form_previewed_after(
        page, lambda: card_group.get_by_role("spinbutton", name="Value 1", exact=True).fill("3.5")
    )
    added = _form_previewed_after(page, lambda: card_group.get_by_role("button", name="Add Row", exact=True).click())
    removed = _form_previewed_after(
        page, lambda: card_group.get_by_role("button", name="Remove Row 1", exact=True).click()
    )

    new_row = (pv.new_row_value, 10)
    assert _spec_sent(chosen, pv)["type"] == "weighted_discrete"
    assert _rows_sent(typed, pv, _WEIGHTED_ROWS) == [(3.5, rows[0][1]), *rows[1:]]
    assert _rows_sent(added, pv, _WEIGHTED_ROWS) == [(3.5, rows[0][1]), *rows[1:], new_row]
    assert _rows_sent(removed, pv, _WEIGHTED_ROWS) == [*rows[1:], new_row]


@pytest.mark.parametrize(("section", "role", "caption", "field", "value"), _SECTION_CONTROLS)
def test_each_edit_to_a_section_control_previews_the_form_with_that_edit(
    page: Page, live_server: str, section: str, role: str, caption: str, field: str, value: str
) -> None:
    """Typing into the control with *role* named *caption* in *section* makes the builder preview the form with *field* set to the value typed."""
    open_builder(page, live_server)
    _open_section(page, section)

    previewed = _form_previewed_after(page, lambda: page.get_by_role(role, name=caption, exact=True).fill(value))

    assert previewed[field] == value


def test_each_edit_to_the_general_textboxes_a_period_preset_and_the_location_previews_the_form_with_that_edit(
    page: Page, live_server: str
) -> None:
    """Typing a name or a description, choosing the 1 Month period, choosing Custom Location and typing each of its coordinates make the builder preview the form with that edit."""
    open_builder(page, live_server)

    named = _form_previewed_after(
        page, lambda: page.get_by_role("textbox", name="Scenario Name", exact=True).fill("Bristol Phase 1")
    )
    described = _form_previewed_after(
        page, lambda: page.get_by_role("textbox", name="Description", exact=True).fill("First 100 homes")
    )
    _open_section(page, "Period")
    month = _form_previewed_after(page, lambda: page.get_by_role("button", name="1 Month", exact=True).click())
    _open_section(page, "Location")
    custom = _form_previewed_after(
        page,
        lambda: page.get_by_role("combobox", name="Location Preset", exact=True).select_option(
            label="Custom Location"
        ),
    )
    north = _form_previewed_after(
        page, lambda: page.get_by_role("spinbutton", name="Latitude", exact=True).fill("53.4")
    )
    west = _form_previewed_after(
        page, lambda: page.get_by_role("spinbutton", name="Longitude", exact=True).fill("-2.2")
    )
    high = _form_previewed_after(
        page, lambda: page.get_by_role("spinbutton", name="Altitude (m)", exact=True).fill("38")
    )

    assert (named["name"], described["description"]) == ("Bristol Phase 1", "First 100 homes")
    assert (month["start_date"], month["end_date"]) == ("2024-06-01", "2024-06-30")
    assert custom["location_preset"] == "custom"
    assert (north["latitude"], west["longitude"], high["altitude"]) == ("53.4", "-2.2", "38")


_DISTRIBUTIONS_YAML = yaml.safe_dump(
    {
        "name": "Uploaded distributions",
        "period": {"start_date": "2024-06-01", "end_date": "2024-06-30"},
        "fleet_distribution": {
            "n_homes": 12,
            "pv": {"capacity_kw": {"type": "weighted_discrete", "values": [2.5, 7.5], "weights": [1, 3]}},
            "battery": {"capacity_kwh": {"type": "normal", "mean": 6.0, "std": 1.5, "min": 0, "max": 12.0}},
            "load": {"annual_consumption_kwh": {"type": "shuffled_pool", "values": [2500, 4100], "counts": [5, 7]}},
        },
    }
)
"""A fleet scenario giving each component a distribution of a different type."""


def test_uploading_a_scenario_shows_each_distribution_in_its_card(page: Page, live_server: str, tmp_path: Path) -> None:
    """Upload YAML shows each component's distribution in its card: its type, and its rows or parameters."""
    open_builder(page, live_server)
    with page.expect_response("**/api/scenarios/preview-yaml"):
        upload_scenario(page, tmp_path / "scenario.yaml", _DISTRIBUTIONS_YAML)
    _open_section(page, "Fleet Distribution")
    pv, battery, load = (page.get_by_role("group", name=card.heading, exact=True) for card in _CARDS)

    for card_group, role, name, value in (
        (pv, "combobox", "Distribution Type", "weighted_discrete"),
        (pv, "spinbutton", "Value 1", "2.5"),
        (pv, "spinbutton", "Weight 1", "1"),
        (pv, "spinbutton", "Value 2", "7.5"),
        (pv, "spinbutton", "Weight 2", "3"),
        (battery, "combobox", "Distribution Type", "normal"),
        (battery, "spinbutton", "Mean", "6"),
        (battery, "spinbutton", "Std Dev", "1.5"),
        (load, "combobox", "Distribution Type", "shuffled_pool"),
        (load, "spinbutton", "Value 2", "4100"),
        (load, "spinbutton", "Count 2", "7"),
    ):
        expect(card_group.get_by_role(role, name=name, exact=True)).to_have_value(value)


_SCALAR_FORM_AND_UNCLAMPED_NORMAL_YAML = yaml.safe_dump(
    {
        "name": "Hand-written specs",
        "fleet_distribution": {
            "n_homes": 12,
            "pv": {"capacity_kw": {"type": "fixed", "value": 4}},
            "battery": {"capacity_kwh": {"type": "normal", "mean": 6.0, "std": 1.5}},
            "load": {"annual_consumption_kwh": 3100},
        },
    }
)
"""A fleet scenario whose PV is the scalar form's mapping and whose battery is a normal without clamps."""


def test_uploading_a_fixed_spec_and_a_normal_without_clamps_shows_fixed_value_and_blank_clamps(
    page: Page, live_server: str, tmp_path: Path
) -> None:
    """Upload YAML loads {type: fixed, value: 4} as Fixed Value 4, and a normal without clamps with its clamps blank, which the builder then sends as null."""
    open_builder(page, live_server)
    with page.expect_response("**/api/scenarios/preview-yaml") as after_upload:
        upload_scenario(page, tmp_path / "scenario.yaml", _SCALAR_FORM_AND_UNCLAMPED_NORMAL_YAML)
    _open_section(page, "Fleet Distribution")
    pv, battery = (page.get_by_role("group", name=card.heading, exact=True) for card in _CARDS[:2])

    expect(pv.get_by_role("combobox", name="Distribution Type", exact=True)).to_have_value("")
    expect(pv.get_by_role("spinbutton", name="Fixed Value", exact=True)).to_have_value("4")
    expect(battery.get_by_role("combobox", name="Distribution Type", exact=True)).to_have_value("normal")
    for clamp in ("Min (clamp)", "Max (clamp)"):
        expect(battery.get_by_role("spinbutton", name=clamp, exact=True)).to_have_value("")
    sent = after_upload.value.request.post_data_json
    assert (_spec_sent(sent, _CARDS[0]), _spec_sent(sent, _CARDS[1])) == (
        4,
        {"type": "normal", "mean": 6, "std": 1.5, "min": None, "max": None},
    )


def _preview_after_uploading(
    page: Page, live_server: str, tmp_path: Path, yaml_text: str
) -> Response:
    """The preview the builder, freshly opened, requests once *yaml_text* is uploaded to it."""
    open_builder(page, live_server)

    with page.expect_response("**/api/scenarios/preview-yaml") as after_upload:
        upload_scenario(page, tmp_path / "scenario.yaml", yaml_text)
    return after_upload.value


_UPLOADED_FORM_GENERAL_FIELDS: dict[str, Any] = {
    "name": "Upload round trip",
    "description": "every builder block",
    "start_date": "2024-06-01",
    "end_date": "2024-06-30",
    "location_preset": "custom",
    "latitude": 53.4,
    "longitude": -2.2,
    "altitude": 38.0,
    "n_homes": 12,
    "import_rate": 0.3,
    "seg_rate_pence_per_kwh": 5.5,
}


@pytest.mark.parametrize(
    "form",
    [
        pytest.param(
            {
                **_UPLOADED_FORM_GENERAL_FIELDS,
                "pv": {"capacity_kw": {"type": "weighted_discrete", "values": [3.0, 5.0], "weights": [1, 3]}},
                "battery": {"capacity_kwh": {"type": "normal", "mean": 5.0, "std": 2.0, "min": 0, "max": 10.0}},
                "load": {"annual_consumption_kwh": {"type": "shuffled_pool", "values": [2900, 4100], "counts": [6, 6]}},
            },
            id="distribution-rows-and-min-0",
        ),
        pytest.param(
            {
                **_UPLOADED_FORM_GENERAL_FIELDS,
                "pv": {"capacity_kw": {"type": "uniform", "min": 2, "max": 8}},
                "battery": {"capacity_kwh": 0},
                "load": {"annual_consumption_kwh": 3100},
            },
            id="fixed-values-and-uniform",
        ),
        pytest.param(
            {
                **_UPLOADED_FORM_GENERAL_FIELDS,
                "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0, "min": None, "max": None}},
                "battery": {"capacity_kwh": {"type": "shuffled_pool", "values": [None, 5.0], "counts": [6, 6]}},
                "load": {"annual_consumption_kwh": 3100},
            },
            id="null-clamps-and-a-null-pool-value",
        ),
    ],
)
def test_uploading_a_builder_yaml_restores_the_form_that_emits_it(
    page: Page, live_server: str, tmp_path: Path, form: dict[str, Any]
) -> None:
    """Uploading the YAML the builder previews for *form* sets the form to one that previews the same scenario.

    The location is custom: a preset location reloads as 'custom', the same place under no preset name.
    """
    yaml_text = page.request.post(
        live_server + "/api/scenarios/preview-yaml", data=form, fail_on_status_code=True
    ).json()["yaml"]

    preview = _preview_after_uploading(page, live_server, tmp_path, yaml_text)

    assert preview.status == 200, preview.text()
    assert yaml.safe_load(preview.json()["yaml"]) == yaml.safe_load(yaml_text)


_LOCATION_WITHOUT_ALTITUDE_YAML = yaml.safe_dump(
    {
        "name": "Hand-written location",
        "period": {"start_date": "2024-06-01", "end_date": "2024-06-30"},
        "location": {"latitude": 53.4, "longitude": -2.2},
        "fleet_distribution": {
            "n_homes": 12,
            "pv": {"capacity_kw": 4.0},
            "battery": {"capacity_kwh": 5.0},
            "load": {"annual_consumption_kwh": 3100},
        },
        "tariff": {"type": "flat_rate", "rate_per_kwh": 0.3},
        "seg": {"rate_pence_per_kwh": 5.5},
    }
)
"""A hand-written fleet scenario with every block the form holds; its location: has no altitude."""


def test_uploading_a_scenario_whose_location_omits_altitude_previews_that_scenario(
    page: Page, live_server: str, tmp_path: Path
) -> None:
    """The builder previews an uploaded scenario without altitude: parse_location_block defaults it.

    It does not refuse the form, which the upload has already set.
    """
    preview = _preview_after_uploading(page, live_server, tmp_path, _LOCATION_WITHOUT_ALTITUDE_YAML)

    assert preview.status == 200, preview.text()
    assert yaml.safe_load(preview.json()["yaml"]) == yaml.safe_load(_LOCATION_WITHOUT_ALTITUDE_YAML)


@pytest.mark.parametrize("key", ["Enter", "Space"])
def test_tabbing_to_upload_yaml_and_pressing_key_opens_a_file_chooser_whose_scenario_loads_into_the_form(
    page: Page, live_server: str, tmp_path: Path, key: str
) -> None:
    """Tab moves focus from the Load Preset button to the Upload YAML button, and pressing *key* there opens a file chooser; the scenario chosen in it sets the form the builder previews."""
    open_builder(page, live_server)
    path = tmp_path / "scenario.yaml"
    path.write_text(_LOCATION_WITHOUT_ALTITUDE_YAML, encoding="utf-8")
    page.get_by_role("button", name="Load Preset", exact=True).focus()

    # The Tab and the focus check stay inside the with: they let the chooser listener register before the key press
    with page.expect_file_chooser() as chooser:
        page.keyboard.press("Tab")
        expect(page.get_by_role("button", name="Upload YAML", exact=True)).to_be_focused()
        page.keyboard.press(key)
    with page.expect_response("**/api/scenarios/preview-yaml") as after_upload:
        chooser.value.set_files(path)

    assert after_upload.value.request.post_data_json["name"] == "Hand-written location"


_RUN_EXPORT_YAML = scenario_yaml(
    fleet_scenario(
        [HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())],
        name="Exported run",
    )
)
"""A run-history YAML export, which lists the fleet's homes one by one."""


@pytest.mark.parametrize(
    ("yaml_text", "refusal"),
    [
        pytest.param(_RUN_EXPORT_YAML, re.escape("fleet_distribution"), id="run-history-export"),
        pytest.param(
            yaml.safe_dump(
                {
                    "name": "Consumption proportional to PV",
                    "fleet_distribution": {
                        "n_homes": 5,
                        "pv": {"capacity_kw": 4.0},
                        "load": {
                            "annual_consumption_kwh": {
                                "type": "proportional_to",
                                "source": "pv.capacity_kw",
                                "multiplier": 1000,
                            }
                        },
                    },
                }
            ),
            ".*".join(
                re.escape(text)
                for text in (
                    "fleet_distribution.load.annual_consumption_kwh",
                    *(each.name for each in FLEET_COMPONENTS["load"].editor_types),
                    "proportional_to",
                )
            ),
            id="a-type-the-editor-does-not-hold",
        ),
    ],
)
def test_uploading_a_yaml_the_form_cannot_hold_leaves_the_form_and_says_why(
    page: Page, live_server: str, tmp_path: Path, yaml_text: str, refusal: str
) -> None:
    """Uploading a scenario the builder's form cannot hold leaves every field as it was, and the preview says why.

    A run-history export has no fleet_distribution: block for the form to edit, and the
    editor holds no proportional_to: the refusal names its path, the editor's types and the
    type written.
    """
    form_before_upload = open_builder(page, live_server).request.post_data_json

    upload_scenario(page, tmp_path / "scenario.yaml", yaml_text)

    expect(page.locator("pre")).to_have_text(
        re.compile(rf"^# scenario\.yaml was not loaded: .*{refusal}")
    )
    assert _form_sent_on_validate(page) == form_before_upload


def test_full_year_sets_the_period_to_the_default_window(page: Page, live_server: str) -> None:
    """Full Year, after 1 Week moved the period, fills Start Date and End Date with timebase's default window."""
    open_builder(page, live_server)
    _open_section(page, "Period")
    start, end = page.get_by_label("Start Date", exact=True), page.get_by_label("End Date", exact=True)

    page.get_by_role("button", name="1 Week", exact=True).click()
    week_start, week_end = days_window(7)
    expect(start).to_have_value(week_start.isoformat())
    expect(end).to_have_value(week_end.isoformat())

    page.get_by_role("button", name="Full Year", exact=True).click()
    expect(start).to_have_value(DEFAULT_FIRST_DAY.isoformat())
    expect(end).to_have_value(DEFAULT_LAST_DAY.isoformat())
