"""End-to-end tests for the Scenario Builder page (/scenarios/builder)."""

import re
from pathlib import Path
from typing import Any, NamedTuple

import pytest
import yaml
from playwright.sync_api import FloatRect, Locator, Page, Response, ViewportSize, expect

from solar_challenge.config import load_fleet_config
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_writer import fleet_scenario, scenario_yaml

pytestmark = pytest.mark.e2e


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
    """
    page.goto(live_server + "/scenarios/builder")
    page.wait_for_load_state("networkidle")

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
    page.wait_for_load_state("networkidle")

    for section_name in _ACCORDION_SECTIONS:
        expect(
            page.get_by_role("button", name=section_name, exact=True),
            f"Accordion section '{section_name}' should be visible",
        ).to_be_visible()


def _expect_expanded_headers(page: Page, open_section: str | None) -> None:
    """Expect the header of *open_section* to be exposed as expanded and every other section's header as collapsed; with None, every header as collapsed."""
    for section in _ACCORDION_SECTIONS:
        expect(page.get_by_role("button", name=section, exact=True, expanded=section == open_section)).to_be_visible()


def test_only_the_open_sections_header_is_exposed_as_expanded(page: Page, live_server: str) -> None:
    """General's header alone is exposed as expanded when the page loads; opening Period moves that to Period's header, and closing Period leaves every header collapsed."""
    page.goto(live_server + "/scenarios/builder")
    _expect_expanded_headers(page, "General")

    _open_section(page, "Period")
    _expect_expanded_headers(page, "Period")

    page.get_by_role("button", name="Period", exact=True).click()
    _expect_expanded_headers(page, None)


def _sections_whose_control_the_panel_holds(page: Page, header: str) -> set[str]:
    """The sections of _ACCORDION_SECTIONS whose control lies, shown or hidden, in the element the header named *header* names in aria-controls."""
    panel_id = page.get_by_role("button", name=header, exact=True).get_attribute("aria-controls")
    assert panel_id, f"the {header} header names no element in aria-controls"
    panel = page.locator(f"id={panel_id}")
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
    page.wait_for_load_state("networkidle")

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
    page.wait_for_load_state("networkidle")

    download_btn = page.locator("button", has_text="Download YAML")
    expect(download_btn).to_be_visible()
    expect(download_btn).to_be_enabled()


# ── Form controls: each caption names its control ────────────────────


def _open_section(page: Page, section: str) -> None:
    """Open the accordion section whose header button is named *section*, closing the open one; General is open when the page loads."""
    page.get_by_role("button", name=section, exact=True).click()


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
    """A distribution card: its heading, the prefix of its form fields, the field holding its fixed value, a fixed value for that field that differs from the card's default and lies within the card's min and max, and the value its add buttons start a new row at."""

    heading: str
    prefix: str
    fixed_field: str
    non_default_fixed_value: str
    new_row_value: float


_CARDS = (
    _Card("PV Capacity (kW)", "pv", "pv_capacity_kw", "6.5", 4.0),
    _Card("Battery Capacity (kWh)", "battery", "battery_capacity_kwh", "9.5", 5.0),
    _Card("Annual Consumption (kWh)", "load", "annual_consumption_kwh", "4200", 3500),
)

_CARD_PARAMS = tuple(pytest.param(card, id=card.prefix) for card in _CARDS)

_DISTRIBUTION_CARDS = tuple(pytest.param(card.heading, card.prefix, id=card.prefix) for card in _CARDS)
"""(card heading, the prefix of its form fields)."""


@pytest.mark.parametrize(("card", "prefix"), _DISTRIBUTION_CARDS)
def test_distribution_card_is_a_group_whose_controls_named_by_their_captions_set_its_distribution(
    page: Page, live_server: str, card: str, prefix: str
) -> None:
    """The group named by a distribution card's heading holds that heading, and one combobox, Distribution Type.

    Choosing Normal Distribution there shows four spinbuttons, Mean, Std Dev, Min and Max,
    which set that card's fields of the form the builder sends.
    """
    page.goto(live_server + "/scenarios/builder")
    _open_section(page, "Fleet Distribution")

    card_group = page.get_by_role("group", name=card, exact=True)
    expect(card_group.get_by_role("combobox")).to_have_count(1)
    expect(card_group.get_by_role("heading", name=card, exact=True)).to_be_visible()
    card_group.get_by_role("combobox", name="Distribution Type", exact=True).select_option(
        label="Normal Distribution"
    )
    for caption, value in {"Mean": "7", "Std Dev": "3", "Min": "1", "Max": "9"}.items():
        card_group.get_by_role("spinbutton", name=caption, exact=True).fill(value)
    expect(card_group.get_by_role("spinbutton")).to_have_count(4)

    sent = _form_sent_on_validate(page)

    assert {field: value for field, value in sent.items() if field.startswith(prefix + "_")} == {
        f"{prefix}_distribution_type": "normal",
        f"{prefix}_mean": "7",
        f"{prefix}_std": "3",
        f"{prefix}_min": "1",
        f"{prefix}_max": "9",
    }


@pytest.mark.parametrize("card", _CARD_PARAMS)
def test_a_card_at_fixed_value_shows_one_spinbutton_named_fixed_value_that_sets_its_fixed_field(
    page: Page, live_server: str, card: _Card
) -> None:
    """At Fixed Value, as every card opens, the card's group shows one spinbutton, named Fixed Value, which sets the card's fixed field of the form the builder sends."""
    page.goto(live_server + "/scenarios/builder")
    _open_section(page, "Fleet Distribution")
    card_group = page.get_by_role("group", name=card.heading, exact=True)
    fixed_value = card_group.get_by_role("spinbutton", name="Fixed Value", exact=True)

    expect(fixed_value).to_have_count(1)
    expect(card_group.get_by_role("spinbutton")).to_have_count(1)
    fixed_value.fill(card.non_default_fixed_value)

    assert _form_sent_on_validate(page)[card.fixed_field] == card.non_default_fixed_value


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
    expect(card_group.get_by_role("button", name="+ Add value", exact=True)).to_be_visible()

    assert _layout_box(distribution_type)["width"] == pytest.approx(width_before, abs=0.5)


# ── Distribution cards: the fields and rows each card sends ──────────


def _choose_in_every_card(page: Page, distribution_type: str) -> None:
    """Open Fleet Distribution and choose *distribution_type* in every card's Distribution Type combobox."""
    _open_section(page, "Fleet Distribution")
    for card in _CARDS:
        page.get_by_role("group", name=card.heading, exact=True).get_by_role(
            "combobox", name="Distribution Type", exact=True
        ).select_option(label=distribution_type)


def _card_fields(sent: dict[str, Any], card: _Card) -> set[str]:
    """The fields of the form *sent* that give *card*: those named with its prefix, and its fixed field."""
    return {field for field in sent if field.startswith(card.prefix + "_") or field == card.fixed_field}


def test_a_card_at_fixed_value_sends_only_its_fixed_value(page: Page, live_server: str) -> None:
    """Every card opens at Fixed Value, and the form the builder previews on opening gives each card's fixed value alone."""
    with page.expect_response("**/api/scenarios/preview-yaml") as opened:
        page.goto(live_server + "/scenarios/builder")

    sent = opened.value.request.post_data_json

    assert {card.prefix: _card_fields(sent, card) for card in _CARDS} == {
        card.prefix: {card.fixed_field} for card in _CARDS
    }


@pytest.mark.parametrize(
    ("distribution_type", "type_value", "parameters"),
    [
        pytest.param("Normal Distribution", "normal", ("mean", "std", "min", "max"), id="normal"),
        pytest.param("Uniform Distribution", "uniform", ("mean", "std", "min", "max"), id="uniform"),
        pytest.param("Weighted Discrete", "weighted_discrete", ("wd_values",), id="weighted_discrete"),
        pytest.param("Shuffled Pool", "shuffled_pool", ("sp_entries",), id="shuffled_pool"),
    ],
)
def test_a_card_set_to_a_distribution_sends_its_type_and_the_fields_that_type_reads(
    page: Page, live_server: str, distribution_type: str, type_value: str, parameters: tuple[str, ...]
) -> None:
    """With *distribution_type* chosen in every card, the form the builder sends gives each card that type and its *parameters*, and not its fixed value.

    Uniform sends all four parameters as normal does; builder_form.py reads only min and max of it.
    """
    page.goto(live_server + "/scenarios/builder")
    _choose_in_every_card(page, distribution_type)

    sent = _form_sent_on_validate(page)

    assert {card.prefix: _card_fields(sent, card) for card in _CARDS} == {
        card.prefix: {f"{card.prefix}_distribution_type", *(f"{card.prefix}_{name}" for name in parameters)}
        for card in _CARDS
    }
    assert {sent[f"{card.prefix}_distribution_type"] for card in _CARDS} == {type_value}


class _RowList(NamedTuple):
    """A distribution the cards hold as rows: its Distribution Type option, the form field after a card's prefix that holds its rows, the number paired with each row's value and that number's caption, and the card's button that adds a row."""

    distribution_type: str
    rows_field: str
    column: str
    column_caption: str
    add_button: str


_ROW_LISTS = (
    pytest.param(
        _RowList("Weighted Discrete", "wd_values", "weight", "Weight", "+ Add value"), id="weighted_discrete"
    ),
    pytest.param(_RowList("Shuffled Pool", "sp_entries", "count", "Count", "+ Add entry"), id="shuffled_pool"),
)

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
    rows_field = f"{card.prefix}_{row_list.rows_field}"
    sent_before = _form_sent_on_validate(page)
    rows = sent_before[rows_field]
    new_row = {"value": card.new_row_value, row_list.column: 10}

    card_group.get_by_role("button", name=row_list.add_button, exact=True).click()
    expect(card_group.get_by_role("spinbutton")).to_have_count(2 * (len(rows) + 1))
    assert _form_sent_on_validate(page) == {**sent_before, rows_field: [*rows, new_row]}

    card_group.get_by_role("button", name="Remove Row 1", exact=True).click()
    expect(card_group.get_by_role("spinbutton")).to_have_count(2 * len(rows))
    assert _form_sent_on_validate(page) == {**sent_before, rows_field: [*rows[1:], new_row]}


@pytest.mark.parametrize("row_list", _ROW_LISTS)
def test_a_cards_last_row_has_no_remove_button(page: Page, live_server: str, row_list: _RowList) -> None:
    """Removing each card's first row until one is left leaves that row without a remove button, and the form the builder sends keeps it."""
    page.goto(live_server + "/scenarios/builder")
    _choose_in_every_card(page, row_list.distribution_type)
    sent_before = _form_sent_on_validate(page)
    rows_before = {card.prefix: sent_before[f"{card.prefix}_{row_list.rows_field}"] for card in _CARDS}
    assert all(len(rows) > 1 for rows in rows_before.values()), (
        f"every card must open with more than one row, or the test removes none: {rows_before}"
    )

    for card in _CARDS:
        card_group = page.get_by_role("group", name=card.heading, exact=True)
        for remaining in range(len(rows_before[card.prefix]) - 1, 0, -1):
            card_group.get_by_role("button", name="Remove Row 1", exact=True).click()
            expect(card_group.get_by_role("spinbutton")).to_have_count(2 * remaining)
        expect(card_group.get_by_role("button", name=_REMOVE_ROW_BUTTONS)).to_have_count(0)

    sent_after = _form_sent_on_validate(page)
    assert {card.prefix: sent_after[f"{card.prefix}_{row_list.rows_field}"] for card in _CARDS} == {
        prefix: rows[-1:] for prefix, rows in rows_before.items()
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
    rows_field = f"{card.prefix}_{row_list.rows_field}"
    sent_before = _form_sent_on_validate(page)
    typed = [{"value": 100 + n, row_list.column: n} for n in range(1, len(sent_before[rows_field]) + 1)]
    expect(card_group.get_by_role("spinbutton")).to_have_count(2 * len(typed))

    for n, row in enumerate(typed, start=1):
        card_group.get_by_role("spinbutton", name=f"Value {n}", exact=True).fill(str(row["value"]))
        card_group.get_by_role("spinbutton", name=f"{row_list.column_caption} {n}", exact=True).fill(
            str(row[row_list.column])
        )

    assert _form_sent_on_validate(page) == {**sent_before, rows_field: typed}


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
    rows_field = f"{card.prefix}_{row_list.rows_field}"
    sent_before = _form_sent_on_validate(page)
    rows = sent_before[rows_field]
    assert len(rows) > 2, f"the card must open with more than two rows, or Remove Row 2 renumbers none: {rows}"
    _expect_remove_buttons_numbered(card_group, len(rows))

    card_group.get_by_role("button", name="Remove Row 2", exact=True).click()

    _expect_remove_buttons_numbered(card_group, len(rows) - 1)
    assert _form_sent_on_validate(page) == {**sent_before, rows_field: [rows[0], *rows[2:]]}


def _phone_card_groups_with_rows(page: Page, live_server: str, row_list: _RowList) -> dict[str, Locator]:
    """Open the builder at phone width with *row_list*'s distribution chosen in every card, and return each card's group by its heading, once each shows its add button."""
    page.set_viewport_size(_PHONE_VIEWPORT)
    page.goto(live_server + "/scenarios/builder")
    _choose_in_every_card(page, row_list.distribution_type)
    card_groups = {card.heading: page.get_by_role("group", name=card.heading, exact=True) for card in _CARDS}
    for card_group in card_groups.values():
        expect(card_group.get_by_role("button", name=row_list.add_button, exact=True)).to_be_visible()
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
    """The YAML previewed for the builder's default form loads through load_fleet_config.

    The page previews its default form as soon as it opens, so this pins the real
    payload of getFormData(), which tests/unit/test_web_scenarios.py's
    TestBuilderScenarioYaml._DEFAULT_FORM mirrors.
    """
    with page.expect_response("**/api/scenarios/preview-yaml") as preview:
        page.goto(live_server + "/scenarios/builder")

    response = preview.value
    assert response.status == 200
    path = tmp_path / "builder.yaml"
    path.write_text(response.json()["yaml"], encoding="utf-8")

    fleet = load_fleet_config(path)

    assert len(fleet.homes) == 100
    assert {home.pv_config.capacity_kw for home in fleet.homes} == {4.0}


def _preview_after_uploading(
    page: Page, live_server: str, tmp_path: Path, yaml_text: str
) -> Response:
    """The preview the builder, freshly opened, requests once *yaml_text* is uploaded to it."""
    with page.expect_response("**/api/scenarios/preview-yaml"):
        page.goto(live_server + "/scenarios/builder")
    path = tmp_path / "scenario.yaml"
    path.write_text(yaml_text, encoding="utf-8")

    with page.expect_response("**/api/scenarios/preview-yaml") as after_upload:
        page.set_input_files('input[type="file"]', path)
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
                "pv_distribution_type": "weighted_discrete",
                "pv_wd_values": [{"value": 3.0, "weight": 1}, {"value": 5.0, "weight": 3}],
                "battery_distribution_type": "normal",
                "battery_mean": 5.0,
                "battery_std": 2.0,
                "battery_min": 0,
                "battery_max": 10.0,
                "load_distribution_type": "shuffled_pool",
                "load_sp_entries": [{"value": 2900, "count": 6}, {"value": 4100, "count": 6}],
            },
            id="distribution rows and min 0",
        ),
        pytest.param(
            {
                **_UPLOADED_FORM_GENERAL_FIELDS,
                "pv_distribution_type": "uniform",
                "pv_mean": 4.0,
                "pv_std": 1.0,
                "pv_min": 2,
                "pv_max": 8,
                "battery_capacity_kwh": 0,
                "annual_consumption_kwh": 3100,
            },
            id="fixed values and uniform",
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
    with page.expect_response("**/api/scenarios/preview-yaml"):
        page.goto(live_server + "/scenarios/builder")
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
        pytest.param(_RUN_EXPORT_YAML, "fleet_distribution", id="run-history export"),
        pytest.param(
            yaml.safe_dump(
                {
                    "name": "Pool without values",
                    "fleet_distribution": {
                        "n_homes": 5,
                        "pv": {"capacity_kw": {"type": "weighted_discrete", "weights": [1, 3]}},
                    },
                }
            ),
            "fleet_distribution.pv.capacity_kw",
            id="weighted_discrete without values",
        ),
    ],
)
def test_uploading_a_yaml_the_form_cannot_hold_leaves_the_form_and_says_why(
    page: Page, live_server: str, tmp_path: Path, yaml_text: str, refusal: str
) -> None:
    """Uploading a scenario the builder's form cannot hold leaves every field as it was, and the preview says why.

    A run-history export has no fleet_distribution: block for the form to edit, and a
    weighted_discrete distribution without values has no rows to show.
    """
    with page.expect_response("**/api/scenarios/preview-yaml") as opened:
        page.goto(live_server + "/scenarios/builder")
    form_before_upload = opened.value.request.post_data_json
    path = tmp_path / "scenario.yaml"
    path.write_text(yaml_text, encoding="utf-8")

    page.set_input_files('input[type="file"]', path)

    expect(page.locator("pre")).to_have_text(
        re.compile(rf"^# scenario\.yaml was not loaded: .*{re.escape(refusal)}")
    )
    assert _form_sent_on_validate(page) == form_before_upload
