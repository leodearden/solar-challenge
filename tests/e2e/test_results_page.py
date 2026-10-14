"""End-to-end tests for the Results page (/results/home/<id>).

Uses seeded data fixtures (no live simulation needed) to verify
page rendering, chart containers, tab switching, stat cards,
download links and error handling, that the daily balance
chart agrees with the stat cards, how a chart whose figure
cannot be drawn is reported, and that a hidden tab's chart is
drawn only once its tab is shown.
"""

import pytest
from playwright.sync_api import Locator, Page, expect

pytestmark = pytest.mark.e2e


# -- Results page loads with seeded data ------------------------------------


def test_results_page_loads(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """GET /results/home/<id> returns 200, and the page's h1 is the run's name."""
    run_id, run_name = seeded_home_run
    response = page.goto(live_server + f"/results/home/{run_id}")
    assert response is not None
    assert response.status == 200

    expect(page.get_by_role("heading", level=1)).to_have_text(run_name)


# -- Chart containers exist ------------------------------------------------


def test_results_chart_containers_exist(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Overview tab shows both chart containers: #chart-sankey, #chart-daily-balance."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")

    for chart_id in ("#chart-sankey", "#chart-daily-balance"):
        expect(page.locator(chart_id)).to_be_visible()


# -- Tab switching ----------------------------------------------------------


def test_results_tab_switching(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Clicking each chart tab makes it the only selected tab.

    Overview is selected on load, so it is clicked last: only then does
    its click have to move the selection.
    """
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")

    for name in ("Power Flow", "Battery & Finance", "Analysis", "Overview"):
        page.get_by_role("tab", name=name, exact=True).click()
        expect(page.get_by_role("tab", selected=True)).to_have_accessible_name(name)


# -- Stat card labels not truncated ----------------------------------------


def test_results_stat_card_labels_not_truncated(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """The seeded run's stat card labels are all visible, and none is cut short.

    The stat_card macro titles each label with its text; no other <p> here has a title.
    The seed's battery_config adds the battery cards; the expected count includes them.
    A label is cut short when its text needs more room than its box, across or down.
    """
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")

    stat_card_labels = page.locator("p[title]").filter(visible=True)
    expect(stat_card_labels).to_have_count(12)

    cut_short = stat_card_labels.evaluate_all("""labels => labels
        .filter(label => label.scrollWidth > label.clientWidth
            || label.scrollHeight > label.clientHeight)
        .map(label => ({
            label: label.textContent.trim(),
            text_size: [label.scrollWidth, label.scrollHeight],
            box_size: [label.clientWidth, label.clientHeight],
        }))""")
    assert cut_short == [], f"Stat card labels are cut short: {cut_short}"


# -- Daily balance chart agrees with the stat cards ------------------------


def _stat_card_value(page: Page, label: str) -> Locator:
    """The value of the stat card titled *label*: the first span under its title's parent, ahead of the unit's span."""
    return page.get_by_title(label, exact=True).locator("..").locator("span").first


def test_results_daily_balance_bars_add_up_to_the_stat_cards(
    page: Page,
    live_server: str,
    seeded_multi_day_home_run: tuple[str, str],
) -> None:
    """Each energy flow's Daily Energy Balance bars, one a day, add up to that flow's stat card.

    The cards show the run's stored summary and the chart its stored time series;
    a run the app saved derives both from the same per-minute amounts, over all its days.
    """
    run_id, _ = seeded_multi_day_home_run
    page.goto(live_server + f"/results/home/{run_id}")

    daily_balance = page.locator("#chart-daily-balance")
    expect(daily_balance.locator(".main-svg").first).to_be_attached()
    daily_bars = daily_balance.evaluate(
        "chart => Object.fromEntries(chart.data.map(trace => [trace.name, trace.y]))"
    )

    for card_label, flow in (
        ("Total Generation", "Generation"),
        ("Total Demand", "Demand"),
        ("Self-Consumption", "Self-Consumption"),
        ("Grid Import", "Grid Import"),
        ("Grid Export", "Grid Export"),
    ):
        bars = daily_bars[flow]
        assert len(bars) > 1, f"a multi-day run has several daily {flow} bars to add up, but the chart shows {len(bars)}"
        expect(_stat_card_value(page, card_label)).to_have_text(f"{sum(bars):.1f}")


# -- A chart whose figure cannot be drawn is reported ----------------------

_UNDRAWABLE_CHART_ID = "chart-undrawable"
_POWER_FLOW_CHART_ID = "chart-power-flow"
_POWER_FLOW_CONTAINER = f'<div id="{_POWER_FLOW_CHART_ID}"'
_CHART_RENDERER_SCRIPT = '<script src="/static/js/chart-renderer.js"'
_FAILED_DRAWING = "the drawing failed after Plotly.newPlot returned"
_PLOTLY_REJECTS_THE_POWER_FLOW_DRAWING = (
    "<script>(function () {"
    " var newPlot = Plotly.newPlot;"
    " Plotly.newPlot = function (container) {"
    f" if (container.id === '{_POWER_FLOW_CHART_ID}') return Promise.reject(new Error('{_FAILED_DRAWING}'));"
    " return newPlot.apply(this, arguments);"
    " };"
    "}());</script>"
)


def _serve_with(page: Page, url: str, insertion: str, anchor: str) -> None:
    """Answer page's requests for url with the page served there, insertion just ahead of anchor, which it must hold once."""
    served = page.request.get(url)
    assert served.status == 200, f"GET {url} answered {served.status}"
    html = served.text()
    anchors = html.count(anchor)
    assert anchors == 1, f"expected {anchor!r} once on the page, as the anchor for {insertion!r}; found {anchors}"
    modified = html.replace(anchor, insertion + anchor)
    page.route(
        url,
        lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=modified
        ),
    )


def _errors_naming(page_errors: list[str], element_id: str) -> list[str]:
    """The entries of page_errors that contain element_id, so an unrelated entry, such as a Plotly CDN failure, cannot change a verdict about the chart."""
    return [error for error in page_errors if element_id in error]


def test_a_chart_whose_figure_cannot_be_drawn_logs_one_error_naming_its_id_and_its_tabs_other_chart_still_draws(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
    page_errors: list[str],
) -> None:
    """Showing the Power Flow tab draws its charts together, the undrawable one first, so its failure must not stop chart-power-flow."""
    run_id, _ = seeded_home_run
    url = live_server + f"/results/home/{run_id}"
    _serve_with(
        page,
        url,
        f'<div id="{_UNDRAWABLE_CHART_ID}" class="w-full" data-chart-figure="not a figure"></div>',
        _POWER_FLOW_CONTAINER,
    )
    page.goto(url)
    expect(page.locator("#chart-daily-balance.js-plotly-plot")).to_be_visible()

    with page.expect_console_message(lambda message: _UNDRAWABLE_CHART_ID in message.text):
        page.get_by_role("tab", name="Power Flow", exact=True).click()

    expect(page.locator("#chart-power-flow.js-plotly-plot")).to_be_visible()
    errors_naming_the_chart = _errors_naming(page_errors, _UNDRAWABLE_CHART_ID)
    assert len(errors_naming_the_chart) == 1, (
        f"expected one error naming {_UNDRAWABLE_CHART_ID!r}, but the page logged: {page_errors}"
    )


def test_a_chart_whose_drawing_fails_after_plotly_newplot_returns_logs_one_error_naming_its_id(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
    page_errors: list[str],
) -> None:
    """Plotly.newPlot returns a promise, which rejects when a draw fails after its synchronous part; that failure is one error naming the chart, not an uncaught rejection."""
    run_id, _ = seeded_home_run
    url = live_server + f"/results/home/{run_id}"
    _serve_with(page, url, _PLOTLY_REJECTS_THE_POWER_FLOW_DRAWING, _CHART_RENDERER_SCRIPT)
    page.goto(url)
    expect(page.locator("#chart-daily-balance.js-plotly-plot")).to_be_visible()

    with page.expect_console_message(lambda message: _POWER_FLOW_CHART_ID in message.text):
        page.get_by_role("tab", name="Power Flow", exact=True).click()

    errors_naming_the_chart = _errors_naming(page_errors, _POWER_FLOW_CHART_ID)
    uncaught_failures = [
        error for error in page_errors if _FAILED_DRAWING in error and _POWER_FLOW_CHART_ID not in error
    ]
    assert (len(errors_naming_the_chart), uncaught_failures) == (1, []), (
        f"expected one error naming {_POWER_FLOW_CHART_ID!r} and no other carrying {_FAILED_DRAWING!r}, but the page logged: {page_errors}"
    )


# -- A hidden tab's chart is drawn once its tab is shown -------------------


def test_a_chart_in_a_hidden_tab_is_drawn_only_once_its_tab_is_shown(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Power Flow's chart, in a tab hidden on load, is not drawn until its tab is shown (AC3)."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")
    expect(page.locator("#chart-daily-balance.js-plotly-plot")).to_be_visible()
    expect(page.locator("#chart-power-flow.js-plotly-plot")).to_have_count(0)

    page.get_by_role("tab", name="Power Flow", exact=True).click()

    expect(page.locator("#chart-power-flow.js-plotly-plot")).to_be_visible()


# -- Download CSV returns 200 ----------------------------------------------


def test_results_download_csv_returns_200(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Follow CSV link -> status 200, content-type text/csv."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")

    csv_link = page.get_by_role("link", name="Download CSV", exact=True)
    expect(csv_link).to_be_visible()

    href = csv_link.get_attribute("href") or ""
    assert href, "CSV download link has no href"

    # Fetch the URL directly
    csv_url = href if href.startswith("http") else live_server + href
    response = page.request.get(csv_url)
    assert response.status == 200, f"CSV download returned {response.status}"
    content_type = response.headers.get("content-type", "")
    assert "text/csv" in content_type, f"Expected text/csv, got '{content_type}'"


# -- Download YAML returns 200 ---------------------------------------------


def test_results_download_yaml_returns_200(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Follow YAML link -> status 200."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")

    yaml_link = page.get_by_role("link", name="Download Config (YAML)", exact=True)
    expect(yaml_link).to_be_visible()

    href = yaml_link.get_attribute("href") or ""
    assert href, "YAML download link has no href"

    yaml_url = href if href.startswith("http") else live_server + href
    response = page.request.get(yaml_url)
    assert response.status == 200, f"YAML download returned {response.status}"


# -- Nonexistent run returns error -----------------------------------------


def test_results_nonexistent_run_returns_error(
    page: Page,
    live_server: str,
) -> None:
    """/results/home/nonexistent -> redirect to dashboard."""
    response = page.goto(live_server + "/results/home/nonexistent-run-id-xyz")
    assert response is not None

    # Should redirect to dashboard (status 200 after redirect, or 302)
    # The route flashes an error and redirects to main.index
    final_url = page.url
    # After redirect we should be on the dashboard or root
    assert "/results/home/nonexistent" not in final_url, (
        f"Expected redirect away from nonexistent results page, still at {final_url}"
    )
