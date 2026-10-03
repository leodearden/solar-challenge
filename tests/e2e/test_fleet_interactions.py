"""End-to-end tests for Fleet Simulation page interactions (/simulate/fleet).

Verifies slider-input sync, that each distribution editor's controls are named
for their card, that each card's row buttons change only its rows, that Import
YAML shows each distribution in its card, export YAML button, that the
simulation name reaches the submitted run, and that the period selector offers
presets and a custom date range.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect

pytestmark = pytest.mark.e2e


# -- Slider-input sync -----------------------------------------------------


def test_fleet_slider_input_sync(page: Page, live_server: str) -> None:
    """Moving the Number of Homes slider to 50 shows 50 in the number input beside it."""
    page.goto(live_server + "/simulate/fleet")

    page.locator("#n_homes_range").fill("50")

    expect(page.get_by_label("Number of Homes", exact=True)).to_have_value("50")


# -- Distribution editor control names -------------------------------------


CARD_SUBJECTS = ("PV Capacity", "Battery Capacity", "Annual Consumption")
DISTRIBUTION_CARDS = [
    pytest.param(subject, id=subject.lower().replace(" ", "_")) for subject in CARD_SUBJECTS
]


def _value_inputs(page: Page, subject: str) -> Locator:
    """The Value input of each row in the card's shown row list."""
    return page.get_by_role("spinbutton", name=re.compile(rf"^{subject} Value \d+$"))


def _expect_only_row_list_shown(page: Page, subject: str, row_field: str) -> None:
    """Wait until the card shows its row_field row list, then until that is its only visible row list: both row lists name their button "<subject> Add Row", so one visible button means the other list has hidden."""
    expect(
        page.get_by_role("spinbutton", name=f"{subject} {row_field} 1", exact=True)
    ).to_have_count(1)
    expect(page.get_by_role("button", name=f"{subject} Add Row", exact=True)).to_have_count(1)


@pytest.mark.parametrize("card", DISTRIBUTION_CARDS)
def test_fleet_distribution_type_select_is_named_for_its_card(
    page: Page, live_server: str, card: str
) -> None:
    """Each card's distribution-type select is named for its card, e.g. 'PV Capacity Distribution Type', and offers 'Normal (Gaussian)'."""
    page.goto(live_server + "/simulate/fleet")

    type_select = page.get_by_role("combobox", name=f"{card} Distribution Type", exact=True)
    expect(type_select).to_be_visible()
    expect(
        type_select.get_by_role("option", name="Normal (Gaussian)", exact=True)
    ).to_have_count(1)


@pytest.mark.parametrize(
    ("distribution_type", "fields"),
    [
        pytest.param(
            "Normal (Gaussian)", ("Mean", "Std Dev", "Min (clamp)", "Max (clamp)"), id="normal"
        ),
        pytest.param("Uniform", ("Min", "Max"), id="uniform"),
        pytest.param(
            "Weighted Discrete",
            ("Value 1", "Weight 1", "Value 2", "Weight 2"),
            id="weighted_discrete",
        ),
        pytest.param(
            "Shuffled Pool", ("Value 1", "Count 1", "Value 2", "Count 2"), id="shuffled_pool"
        ),
    ],
)
@pytest.mark.parametrize("card", DISTRIBUTION_CARDS)
def test_fleet_distribution_parameters_are_named_for_their_card(
    page: Page, live_server: str, card: str, distribution_type: str, fields: tuple[str, ...]
) -> None:
    """Each number input a distribution type shows is named for its card and field, and a row's inputs for their row, e.g. 'PV Capacity Value 2'."""
    page.goto(live_server + "/simulate/fleet")

    page.get_by_role("combobox", name=f"{card} Distribution Type", exact=True).select_option(
        label=distribution_type
    )
    for field in fields:
        # to_have_count(1) retries while a type switch's outgoing row list, with the same names, is still shown.
        expect(
            page.get_by_role("spinbutton", name=f"{card} {field}", exact=True)
        ).to_have_count(1)


@pytest.mark.parametrize(
    "distribution_type",
    [
        pytest.param("Weighted Discrete", id="weighted_discrete"),
        pytest.param("Shuffled Pool", id="shuffled_pool"),
    ],
)
@pytest.mark.parametrize("card", DISTRIBUTION_CARDS)
def test_fleet_distribution_row_buttons_are_named_for_their_card(
    page: Page, live_server: str, card: str, distribution_type: str
) -> None:
    """A row list's Add Row button and each row's remove button are named for the card, e.g. 'PV Capacity Add Row' and 'PV Capacity Remove Row 2'."""
    page.goto(live_server + "/simulate/fleet")

    page.get_by_role("combobox", name=f"{card} Distribution Type", exact=True).select_option(
        label=distribution_type
    )
    for name in ("Remove Row 1", "Remove Row 2", "Add Row"):
        expect(
            page.get_by_role("button", name=f"{card} {name}", exact=True)
        ).to_have_count(1)


NEW_ROW_VALUES = {"PV Capacity": "4", "Battery Capacity": "5", "Annual Consumption": "3500"}


@pytest.mark.parametrize(
    ("distribution_type", "row_field"),
    [
        pytest.param("Weighted Discrete", "Weight", id="weighted_discrete"),
        pytest.param("Shuffled Pool", "Count", id="shuffled_pool"),
    ],
)
@pytest.mark.parametrize("card", DISTRIBUTION_CARDS)
def test_fleet_distribution_row_buttons_change_only_their_cards_rows(
    page: Page, live_server: str, card: str, distribution_type: str, row_field: str
) -> None:
    """A card's Add Row button appends a row to that card alone, starting at the card's value and a weight or count of 10, and its Remove Row 1 button removes that card's first row alone."""
    page.goto(live_server + "/simulate/fleet")
    for subject in CARD_SUBJECTS:
        page.get_by_role(
            "combobox", name=f"{subject} Distribution Type", exact=True
        ).select_option(label=distribution_type)
        _expect_only_row_list_shown(page, subject, row_field)
    row_counts = {subject: _value_inputs(page, subject).count() for subject in CARD_SUBJECTS}
    other_cards = [subject for subject in CARD_SUBJECTS if subject != card]

    page.get_by_role("button", name=f"{card} Add Row", exact=True).click()
    added_row = row_counts[card] + 1
    expect(_value_inputs(page, card)).to_have_count(added_row)
    for other in other_cards:
        expect(_value_inputs(page, other)).to_have_count(row_counts[other])
    expect(
        page.get_by_role("spinbutton", name=f"{card} Value {added_row}", exact=True)
    ).to_have_value(NEW_ROW_VALUES[card])
    expect(
        page.get_by_role("spinbutton", name=f"{card} {row_field} {added_row}", exact=True)
    ).to_have_value("10")

    second_value = page.get_by_role("spinbutton", name=f"{card} Value 2", exact=True).input_value()
    page.get_by_role("button", name=f"{card} Remove Row 1", exact=True).click()
    for subject in (card, *other_cards):
        expect(_value_inputs(page, subject)).to_have_count(row_counts[subject])
    expect(page.get_by_role("spinbutton", name=f"{card} Value 1", exact=True)).to_have_value(
        second_value
    )


# -- Import YAML ------------------------------------------------------------


IMPORTED_FLEET = """\
fleet_distribution:
  n_homes: 100
  pv:
    capacity_kw: {type: weighted_discrete, values: [2.5, 7.5], weights: [1, 3]}
  battery:
    capacity_kwh: {type: weighted_discrete, values: [0, 9.5], weights: [1, 1]}
  load:
    annual_consumption_kwh: {type: weighted_discrete, values: [2500, 4100, 5200], weights: [1, 1, 1]}
"""
IMPORTED_VALUES = {
    "PV Capacity": ["2.5", "7.5"],
    "Battery Capacity": ["0", "9.5"],
    "Annual Consumption": ["2500", "4100", "5200"],
}


def test_fleet_import_yaml_shows_each_distribution_in_its_card(
    page: Page, live_server: str, tmp_path: Path
) -> None:
    """Import YAML puts a fleet file's PV, battery and consumption distributions in their cards, each showing its distribution's rows."""
    fleet_file = tmp_path / "fleet.yaml"
    fleet_file.write_text(IMPORTED_FLEET)
    page.goto(live_server + "/simulate/fleet")

    with page.expect_file_chooser() as chooser:
        page.get_by_text("Import YAML", exact=True).click()
    chooser.value.set_files(fleet_file)

    for subject, values in IMPORTED_VALUES.items():
        _expect_only_row_list_shown(page, subject, "Weight")
        expect(_value_inputs(page, subject)).to_have_count(len(values))
        for row, value in enumerate(values, start=1):
            expect(
                page.get_by_role("spinbutton", name=f"{subject} Value {row}", exact=True)
            ).to_have_value(value)


# -- Export YAML button -----------------------------------------------------


def test_fleet_export_yaml_button(page: Page, live_server: str) -> None:
    """The fleet page shows an 'Export YAML' button."""
    page.goto(live_server + "/simulate/fleet")

    expect(page.get_by_role("button", name="Export YAML", exact=True)).to_be_visible()


# -- Simulation name reaches the submitted run -----------------------------


def test_fleet_simulation_name_is_submitted(page: Page, live_server: str) -> None:
    """The name typed into 'Simulation Name' is the name the fleet run is submitted under."""
    # Abort the submission so no fleet job ever reaches the server's JobManager.
    page.route("**/api/simulate/fleet-from-distribution", lambda route: route.abort())
    page.goto(live_server + "/simulate/fleet")

    run_button = page.get_by_role("button", name="Run Fleet Simulation")
    expect(run_button).to_be_visible()

    page.get_by_label("Simulation Name", exact=True).fill("Bristol Fleet Trial")
    with page.expect_request("**/api/simulate/fleet-from-distribution") as submission:
        run_button.click()

    assert submission.value.post_data_json["name"] == "Bristol Fleet Trial"


# -- Period selector -------------------------------------------------------


def test_fleet_period_selector_offers_presets_and_custom_range(
    page: Page, live_server: str
) -> None:
    """The Simulation Period offers presets from '7 days' to '1 year', and Custom range shows Start Date and End Date."""
    page.goto(live_server + "/simulate/fleet")

    for preset in ("7 days", "1 year"):
        expect(page.get_by_role("button", name=preset, exact=True)).to_be_visible()

    page.get_by_role("radio", name="Custom range", exact=True).check()
    for boundary in ("Start Date", "End Date"):
        expect(page.get_by_label(boundary, exact=True)).to_be_visible()
