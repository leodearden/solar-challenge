"""End-to-end tests for the Parameter Sweep page (/scenarios/sweep).

Verifies page loading, that each form control is found by role and by the name
its label gives it, that the Linear and Geometric radios are the radio group
named "Sweep Mode" and the Battery (kWh), Location and Days controls are in
the group named "Base Configuration", preview calculations (the preview lists
its values in the list named "Sweep values"), that submitting a sweep filled
into the form returns one background job per sweep point, and detects Bug B1
(Alpine race condition with external JS).
"""

import pytest
from playwright.sync_api import ConsoleMessage, Page, expect

pytestmark = pytest.mark.e2e


# -- Page loading ----------------------------------------------------------


def test_sweep_page_loads(page: Page, live_server: str) -> None:
    """GET /scenarios/sweep returns a page with 'Parameter Sweep' heading."""
    response = page.goto(live_server + "/scenarios/sweep")
    assert response is not None
    assert response.status == 200

    page.wait_for_load_state("domcontentloaded")

    heading = page.locator("text=Parameter Sweep").first
    expect(heading).to_be_visible()


# -- Bug B1: Alpine race condition with external JS -----------------------


def test_sweep_no_js_errors(page: Page, live_server: str) -> None:
    """The sweep page should load without JavaScript console errors.

    The ``parameterSweep()`` component is defined in an external JS file
    loaded via ``defer`` in ``{% block head %}``.  Depending on script
    execution order, Alpine.js may try to evaluate the ``x-data``
    attribute before the component function is registered, causing a
    console error.
    """
    errors: list[str] = []

    def _on_console(msg: ConsoleMessage) -> None:
        if msg.type == "error":
            errors.append(msg.text)

    page.on("console", _on_console)
    page.goto(live_server + "/scenarios/sweep")
    # Give deferred scripts time to load and Alpine to initialise
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    page.remove_listener("console", _on_console)

    assert errors == [], f"Console errors on /scenarios/sweep: {errors}"


# -- Sweep configuration form controls -------------------------------------


_SWEEP_FORM_CONTROLS = (
    pytest.param("combobox", "Parameter to Sweep", id="parameter"),
    pytest.param("spinbutton", "Min Value", id="min"),
    pytest.param("spinbutton", "Max Value", id="max"),
    pytest.param("spinbutton", "Steps", id="steps"),
    pytest.param("radio", "Linear", id="linear"),
    pytest.param("radio", "Geometric", id="geometric"),
    pytest.param("spinbutton", "Battery (kWh)", id="battery_kwh"),
    pytest.param("combobox", "Location", id="location"),
    pytest.param("spinbutton", "Days", id="days"),
)


@pytest.mark.parametrize(("role", "label"), _SWEEP_FORM_CONTROLS)
def test_sweep_form_control_is_named_by_its_label(
    page: Page, live_server: str, role: str, label: str
) -> None:
    """Each sweep form control is found by role and by the accessible name its label gives it."""
    page.goto(live_server + "/scenarios/sweep")

    expect(page.get_by_role(role, name=label, exact=True)).to_be_visible()


# -- Sweep form control groups ---------------------------------------------


def test_sweep_mode_radio_group_holds_the_linear_and_geometric_radios(
    page: Page, live_server: str
) -> None:
    """The radio group named "Sweep Mode" holds exactly two radios, Linear and Geometric."""
    page.goto(live_server + "/scenarios/sweep")

    sweep_mode = page.get_by_role("radiogroup", name="Sweep Mode", exact=True)
    expect(sweep_mode.get_by_role("radio")).to_have_count(2)
    expect(sweep_mode.get_by_role("radio", name="Linear", exact=True)).to_be_visible()
    expect(
        sweep_mode.get_by_role("radio", name="Geometric", exact=True)
    ).to_be_visible()


def test_base_configuration_group_holds_the_battery_location_and_days_controls(
    page: Page, live_server: str
) -> None:
    """The group named "Base Configuration" holds the Battery (kWh) and Days spinbuttons and the Location combobox."""
    page.goto(live_server + "/scenarios/sweep")

    base_configuration = page.get_by_role(
        "group", name="Base Configuration", exact=True
    )
    expect(
        base_configuration.get_by_role("spinbutton", name="Battery (kWh)", exact=True)
    ).to_be_visible()
    expect(
        base_configuration.get_by_role("combobox", name="Location", exact=True)
    ).to_be_visible()
    expect(
        base_configuration.get_by_role("spinbutton", name="Days", exact=True)
    ).to_be_visible()


# -- Preview updates when inputs change ------------------------------------


def test_sweep_preview_updates(page: Page, live_server: str) -> None:
    """Filling in min=1, max=10, steps=5 previews the five linear sweep values from 1 to 10, listed in the list named "Sweep values"."""
    page.goto(live_server + "/scenarios/sweep")

    page.get_by_label("Min Value", exact=True).fill("1")
    page.get_by_label("Max Value", exact=True).fill("10")
    page.get_by_label("Steps", exact=True).fill("5")

    expect(page.get_by_text("5 values will be tested", exact=True)).to_be_visible()
    sweep_values = page.get_by_role("list", name="Sweep values", exact=True)
    expect(sweep_values.get_by_role("listitem")).to_have_text(
        ["1", "3.25", "5.5", "7.75", "10"]
    )


# -- Sweep submission: one background home job per sweep point ------------


def test_sweep_submit_returns_201_with_job_ids(page: Page, live_server: str) -> None:
    """Filling the form with a 3-point geometric sweep from 1 to 9 and clicking its
    button returns 201 with a sweep id, the geometric sweep values and one
    distinct background home-job id per sweep point.

    Min, max, steps and mode are all moved off their defaults, so the response's
    values prove that each filled control reached the request.
    """
    page.goto(live_server + "/scenarios/sweep")

    page.get_by_label("Min Value", exact=True).fill("1")
    page.get_by_label("Max Value", exact=True).fill("9")
    page.get_by_label("Steps", exact=True).fill("3")
    page.get_by_role("radio", name="Geometric", exact=True).check()

    # Intercept the API call and click the submit button
    with page.expect_response("**/api/simulate/sweep") as response_info:
        page.get_by_role("button", name="Run Parameter Sweep").click()

    response = response_info.value
    assert response.status == 201

    data = response.json()
    assert data["sweep_id"]
    assert data["values"] == [1.0, 3.0, 9.0]

    job_ids = data["job_ids"]
    assert len(job_ids) == 3
    assert len(set(job_ids)) == 3
    assert all(job_ids)
