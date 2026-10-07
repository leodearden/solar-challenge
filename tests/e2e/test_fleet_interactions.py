"""End-to-end tests for Fleet Simulation page interactions (/simulate/fleet).

Verifies slider-input sync, that each distribution editor's controls are named
for their card, that each card's row buttons change only its rows, that a
card's last row has no remove button, that Import YAML shows each distribution
in its card, that a fleet exported as YAML imports back into the form, that
Load Preset fills the form and names the preset's
settings the form has no control for, that a preset without a period runs the
page's default period, that the page shows why a preset cannot
load or a fleet cannot export, that the simulation name reaches the submitted
run, that Run shows why the page refuses a form, submits nothing and leaves the
results link of an earlier run in place, and that the period selector offers
presets and a custom date range.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, Route, expect

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


@pytest.mark.parametrize(
    ("distribution_type", "row_field"),
    [
        pytest.param("Weighted Discrete", "Weight", id="weighted_discrete"),
        pytest.param("Shuffled Pool", "Count", id="shuffled_pool"),
    ],
)
@pytest.mark.parametrize("card", DISTRIBUTION_CARDS)
def test_fleet_distribution_last_row_has_no_remove_button(
    page: Page, live_server: str, card: str, distribution_type: str, row_field: str
) -> None:
    """Removing a card's first row until one is left leaves that row without a remove button."""
    page.goto(live_server + "/simulate/fleet")
    page.get_by_role("combobox", name=f"{card} Distribution Type", exact=True).select_option(
        label=distribution_type
    )
    _expect_only_row_list_shown(page, card, row_field)
    remove_buttons = page.get_by_role("button", name=re.compile(rf"^{card} Remove Row \d+$"))

    for remaining in range(_value_inputs(page, card).count() - 1, 0, -1):
        page.get_by_role("button", name=f"{card} Remove Row 1", exact=True).click()
        expect(_value_inputs(page, card)).to_have_count(remaining)

    expect(remove_buttons).to_have_count(0)


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


# -- Export YAML, then import it -------------------------------------------


def _set_a_fleet_unlike_the_default(page: Page) -> None:
    """Set a name, PV distribution, period, tariff, SEG and dispatch strategy that each differ from the page's defaults."""
    page.get_by_label("Simulation Name", exact=True).fill("Round Trip Fleet")
    page.get_by_role("combobox", name="PV Capacity Distribution Type", exact=True).select_option(
        label="Weighted Discrete"
    )
    _expect_only_row_list_shown(page, "PV Capacity", "Weight")
    page.get_by_role("spinbutton", name="PV Capacity Value 1", exact=True).fill("3.5")
    page.get_by_role("radio", name="Custom range", exact=True).check()
    page.get_by_label("Start Date", exact=True).fill("2024-07-01")
    page.get_by_label("End Date", exact=True).fill("2024-07-10")
    page.get_by_role("switch", name="Enable Tariff", exact=True).click()
    page.get_by_role("combobox", name="Tariff Type", exact=True).select_option(label="Economy 7")
    page.get_by_role("spinbutton", name="Peak Rate (£/kWh)", exact=True).fill("0.31")
    page.get_by_role("switch", name="Enable SEG Export Pricing", exact=True).click()
    page.get_by_role("combobox", name="Supplier Preset", exact=True).select_option(value="Octopus")
    page.get_by_role("combobox", name="Dispatch Strategy", exact=True).select_option(
        label="Peak Shaving"
    )
    page.get_by_role("spinbutton", name="Import limit (kW)", exact=True).fill("4.5")


def _expect_the_fleet_unlike_the_default(page: Page) -> None:
    """Expect every control _set_a_fleet_unlike_the_default sets to show its value, with the battery still enabled."""
    expect(page.get_by_label("Simulation Name", exact=True)).to_have_value("Round Trip Fleet")
    expect(
        page.get_by_role("combobox", name="PV Capacity Distribution Type", exact=True)
    ).to_have_value("weighted_discrete")
    _expect_only_row_list_shown(page, "PV Capacity", "Weight")
    expect(page.get_by_role("spinbutton", name="PV Capacity Value 1", exact=True)).to_have_value(
        "3.5"
    )
    expect(page.get_by_role("radio", name="Custom range", exact=True)).to_be_checked()
    expect(page.get_by_label("Start Date", exact=True)).to_have_value("2024-07-01")
    expect(page.get_by_label("End Date", exact=True)).to_have_value("2024-07-10")
    expect(page.get_by_role("switch", name="Enable Tariff", exact=True)).to_be_checked()
    expect(page.get_by_role("combobox", name="Tariff Type", exact=True)).to_have_value("economy_7")
    expect(page.get_by_role("spinbutton", name="Peak Rate (£/kWh)", exact=True)).to_have_value(
        "0.31"
    )
    expect(page.get_by_role("switch", name="Enable SEG Export Pricing", exact=True)).to_be_checked()
    expect(page.get_by_role("combobox", name="Supplier Preset", exact=True)).to_have_value(
        "Octopus"
    )
    expect(page.get_by_role("checkbox", name="Enable Battery", exact=True)).to_be_checked()
    expect(page.get_by_role("combobox", name="Dispatch Strategy", exact=True)).to_have_value(
        "peak_shaving"
    )
    expect(page.get_by_role("spinbutton", name="Import limit (kW)", exact=True)).to_have_value(
        "4.5"
    )


def test_fleet_yaml_export_imports_back_into_the_form(
    page: Page, live_server: str, tmp_path: Path, page_errors: list[str]
) -> None:
    """A fleet exported with Export YAML, imported into a reloaded page with Import YAML, shows every value it was exported with, and the page names nothing as not loaded."""
    page.goto(live_server + "/simulate/fleet")
    _set_a_fleet_unlike_the_default(page)

    with page.expect_download() as download:
        page.get_by_role("button", name="Export YAML", exact=True).click()
    fleet_file = tmp_path / "fleet-config.yaml"
    download.value.save_as(fleet_file)
    page.reload()
    with page.expect_file_chooser() as chooser:
        page.get_by_text("Import YAML", exact=True).click()
    chooser.value.set_files(fleet_file)

    _expect_the_fleet_unlike_the_default(page)
    expect(page.get_by_role("alert")).to_have_count(0)
    expect(page.get_by_role("status")).to_have_count(0)
    assert page_errors == [], f"Errors on /simulate/fleet: {page_errors}"


def test_fleet_export_shows_the_servers_refusal(page: Page, live_server: str) -> None:
    """Export YAML of a fleet the loaders refuse, a normal PV distribution whose min clamp exceeds its max, shows the server's error."""
    page.goto(live_server + "/simulate/fleet")
    page.get_by_role("combobox", name="PV Capacity Distribution Type", exact=True).select_option(
        label="Normal (Gaussian)"
    )
    page.get_by_role("spinbutton", name="PV Capacity Min (clamp)", exact=True).fill("8")
    page.get_by_role("spinbutton", name="PV Capacity Max (clamp)", exact=True).fill("2")

    with page.expect_response("**/api/fleet/export-yaml") as answer:
        page.get_by_role("button", name="Export YAML", exact=True).click()

    assert answer.value.status == 400
    expect(page.get_by_role("alert")).to_have_text(answer.value.json()["error"])


# -- Load Preset ------------------------------------------------------------


BRISTOL_PHASE1_ROWS = {
    "PV Capacity": [("3", "20"), ("4", "40"), ("5", "30"), ("6", "10")],
    "Battery Capacity": [("0", "40"), ("5", "40"), ("10", "20")],
}


def _expect_pool_rows(page: Page, subject: str, rows: list[tuple[str, str]]) -> None:
    """Expect the card to show a shuffled pool of exactly *rows*, each a (Value, Count) pair."""
    expect(
        page.get_by_role("combobox", name=f"{subject} Distribution Type", exact=True)
    ).to_have_value("shuffled_pool")
    _expect_only_row_list_shown(page, subject, "Count")
    expect(_value_inputs(page, subject)).to_have_count(len(rows))
    for row, (value, count) in enumerate(rows, start=1):
        expect(
            page.get_by_role("spinbutton", name=f"{subject} Value {row}", exact=True)
        ).to_have_value(value)
        expect(
            page.get_by_role("spinbutton", name=f"{subject} Count {row}", exact=True)
        ).to_have_value(count)


def test_fleet_load_preset_fills_the_form_and_names_what_it_did_not_load(
    page: Page, live_server: str, page_errors: list[str]
) -> None:
    """Load Preset 'bristol-phase1' shows its fleet size, distributions and SEG rate, and a notice names its settings the form has no control for."""
    page.goto(live_server + "/simulate/fleet")
    pv_type = page.get_by_role("combobox", name="PV Capacity Distribution Type", exact=True)
    load_type = page.get_by_role(
        "combobox", name="Annual Consumption Distribution Type", exact=True
    )
    n_homes = page.get_by_label("Number of Homes", exact=True)
    battery = page.get_by_role("checkbox", name="Enable Battery", exact=True)
    # The default form is bristol-phase1's fleet, so move away from it first.
    pv_type.select_option(label="Uniform")
    load_type.select_option(label="Uniform")
    n_homes.fill("50")
    battery.uncheck()
    expect(pv_type).to_have_value("uniform")
    expect(load_type).to_have_value("uniform")
    expect(n_homes).to_have_value("50")
    expect(battery).not_to_be_checked()

    page.get_by_role("combobox", name="Load Preset", exact=True).select_option("bristol-phase1")

    _expect_pool_rows(page, "PV Capacity", BRISTOL_PHASE1_ROWS["PV Capacity"])
    expect(battery).to_be_checked()
    _expect_pool_rows(page, "Battery Capacity", BRISTOL_PHASE1_ROWS["Battery Capacity"])
    expect(load_type).to_have_value("normal")
    expect(
        page.get_by_role("spinbutton", name="Annual Consumption Mean", exact=True)
    ).to_have_value("3400")
    expect(n_homes).to_have_value("100")
    expect(page.get_by_role("switch", name="Enable SEG Export Pricing", exact=True)).to_be_checked()
    expect(page.get_by_role("combobox", name="Supplier Preset", exact=True)).to_have_value(
        "custom"
    )
    expect(page.get_by_role("spinbutton", name="Export Rate (p/kWh)", exact=True)).to_have_value(
        "4.1"
    )
    for not_loaded in (
        "fleet_distribution.random_order",
        "fleet_distribution.pv.azimuth",
        "finance",
    ):
        expect(page.get_by_role("status")).to_contain_text(not_loaded)
    assert page_errors == [], f"Errors on /simulate/fleet: {page_errors}"


def test_fleet_load_preset_without_a_period_runs_the_pages_default_period(
    page: Page, live_server: str, tmp_path: Path
) -> None:
    """Load Preset of a scenario with no period, after a file with one was imported, runs the page's default 30 days, not the file's dates."""
    # Abort the submission so no fleet job ever reaches the server's JobManager.
    page.route("**/api/simulate/fleet-from-distribution", lambda route: route.abort())
    fleet_file = tmp_path / "fleet.yaml"
    fleet_file.write_text(IMPORTED_FLEET + "period: {start_date: 2024-07-01, end_date: 2024-07-10}\n")
    page.goto(live_server + "/simulate/fleet")
    # A quick preset other than the default, so keeping the last one shown would not pass.
    page.get_by_role("button", name="90 days", exact=True).click()
    with page.expect_file_chooser() as chooser:
        page.get_by_text("Import YAML", exact=True).click()
    chooser.value.set_files(fleet_file)
    expect(page.get_by_role("radio", name="Custom range", exact=True)).to_be_checked()
    expect(page.get_by_label("Start Date", exact=True)).to_have_value("2024-07-01")

    page.get_by_role("combobox", name="Load Preset", exact=True).select_option("bristol-phase1")
    expect(page.get_by_role("status")).to_contain_text("fleet_distribution.random_order")

    expect(page.get_by_role("radio", name="Quick preset", exact=True)).to_be_checked()
    with page.expect_request("**/api/simulate/fleet-from-distribution") as submission:
        page.get_by_role("button", name="Run Fleet Simulation").click()
    payload = submission.value.post_data_json
    assert (payload.get("days"), payload.get("start"), payload.get("end")) == (30, None, None)


def test_fleet_load_preset_shows_why_a_scenario_cannot_load(page: Page, live_server: str) -> None:
    """Load Preset of a scenario of individual homes, which has no fleet_distribution block, shows the error naming that block."""
    page.goto(live_server + "/simulate/fleet")

    page.get_by_role("combobox", name="Load Preset", exact=True).select_option("bristol-arbitrage")

    expect(page.get_by_role("alert")).to_contain_text("fleet_distribution")


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


# -- Run refuses a form it cannot run --------------------------------------


@pytest.fixture
def fleet_submissions(page: Page) -> list[Any]:
    """The body of each fleet run the page submits during the test, each aborted so no job reaches the live server's JobManager."""
    submissions: list[Any] = []

    def _record_and_abort(route: Route) -> None:
        submissions.append(route.request.post_data_json)
        route.abort()

    page.route("**/api/simulate/fleet-from-distribution", _record_and_abort)
    return submissions


def test_fleet_run_of_an_imported_fleet_over_the_pages_size_limit_shows_the_refusal(
    page: Page,
    live_server: str,
    tmp_path: Path,
    fleet_submissions: list[Any],
    page_errors: list[str],
) -> None:
    """Run of a fleet imported with more homes than the page runs, 1500 against its 1000, shows the refusal and submits nothing."""
    fleet_file = tmp_path / "fleet.yaml"
    fleet_file.write_text(IMPORTED_FLEET.replace("n_homes: 100", "n_homes: 1500"))
    page.goto(live_server + "/simulate/fleet")

    with page.expect_file_chooser() as chooser:
        page.get_by_text("Import YAML", exact=True).click()
    chooser.value.set_files(fleet_file)
    expect(page.get_by_label("Number of Homes", exact=True)).to_have_value("1500")

    page.get_by_role("button", name="Run Fleet Simulation").click()

    expect(page.get_by_role("alert")).to_have_text("Fleet size must be at most 1000")
    assert fleet_submissions == []
    assert page_errors == [], f"Errors on /simulate/fleet: {page_errors}"


def test_fleet_run_shows_every_reason_it_refuses_the_form(
    page: Page, live_server: str, fleet_submissions: list[Any], page_errors: list[str]
) -> None:
    """Run of a form with two faults, a normal PV distribution with a zero Std Dev and a Min clamp above its Max, shows both reasons in one alert and submits nothing."""
    page.goto(live_server + "/simulate/fleet")
    page.get_by_role("combobox", name="PV Capacity Distribution Type", exact=True).select_option(
        label="Normal (Gaussian)"
    )
    page.get_by_role("spinbutton", name="PV Capacity Std Dev", exact=True).fill("0")
    page.get_by_role("spinbutton", name="PV Capacity Min (clamp)", exact=True).fill("8")
    page.get_by_role("spinbutton", name="PV Capacity Max (clamp)", exact=True).fill("2")

    page.get_by_role("button", name="Run Fleet Simulation").click()

    expect(page.get_by_role("alert")).to_have_text(
        "PV std deviation must be positive; PV min must be less than max"
    )
    assert fleet_submissions == []
    assert page_errors == [], f"Errors on /simulate/fleet: {page_errors}"


COMPLETED_RUN_ID = "run-1"


@pytest.fixture
def fleet_runs_complete_at_once(page: Page) -> None:
    """Answer each fleet run the page submits as a job that completes at once as COMPLETED_RUN_ID, so no job reaches the live server's JobManager."""
    page.route(
        "**/api/simulate/fleet-from-distribution",
        lambda route: route.fulfill(
            status=201, json={"job_id": "job-1", "run_id": COMPLETED_RUN_ID}
        ),
    )
    completion = {"status": "completed", "run_id": COMPLETED_RUN_ID}
    page.route(
        "**/api/jobs/job-1/progress",
        lambda route: route.fulfill(
            content_type="text/event-stream",
            body=f"event: complete\ndata: {json.dumps(completion)}\n\n",
        ),
    )


@pytest.mark.usefixtures("fleet_runs_complete_at_once")
def test_fleet_run_that_refuses_the_form_leaves_the_earlier_runs_results_link(
    page: Page, live_server: str, page_errors: list[str]
) -> None:
    """Run of a form the page refuses, after a run that completed, shows the refusal and leaves that run's View Results link: a refusal is no submission to replace it."""
    earlier_results = f"/results/fleet/{COMPLETED_RUN_ID}"
    page.goto(live_server + "/simulate/fleet")
    page.get_by_role("button", name="Run Fleet Simulation").click()
    results_link = page.get_by_role("link", name="View Results", exact=True)
    expect(results_link).to_have_attribute("href", earlier_results)

    page.get_by_role("combobox", name="PV Capacity Distribution Type", exact=True).select_option(
        label="Normal (Gaussian)"
    )
    page.get_by_role("spinbutton", name="PV Capacity Std Dev", exact=True).fill("0")
    page.get_by_role("button", name="Run Fleet Simulation").click()

    expect(page.get_by_role("alert")).to_have_text("PV std deviation must be positive")
    expect(results_link).to_have_attribute("href", earlier_results)
    assert page_errors == [], f"Errors on /simulate/fleet: {page_errors}"


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
