"""End-to-end tests for Fleet Simulation page interactions (/simulate/fleet).

Verifies slider-input sync, that each distribution editor's controls are named
for their card, export YAML button, that the simulation name reaches the
submitted run, and that the period selector offers presets and a custom date
range.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# -- Slider-input sync -----------------------------------------------------


def test_fleet_slider_input_sync(page: Page, live_server: str) -> None:
    """Moving the Number of Homes slider to 50 shows 50 in the number input beside it."""
    page.goto(live_server + "/simulate/fleet")

    page.locator("#n_homes_range").fill("50")

    expect(page.get_by_label("Number of Homes", exact=True)).to_have_value("50")


# -- Distribution editor control names -------------------------------------


DISTRIBUTION_CARDS = [
    pytest.param("PV Capacity", id="pv_capacity"),
    pytest.param("Battery Capacity", id="battery_capacity"),
    pytest.param("Annual Consumption", id="annual_consumption"),
]


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
