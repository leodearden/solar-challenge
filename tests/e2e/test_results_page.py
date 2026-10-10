"""End-to-end tests for the Results page (/results/home/<id>).

Uses seeded data fixtures (no live simulation needed) to verify
page rendering, chart containers, tab switching, stat cards,
download links and error handling, that the daily balance
chart agrees with the stat cards, and how renderChart reports
a figure it cannot draw.
"""

import json

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


# -- renderChart reports a figure it cannot draw ---------------------------

_ID_NO_ELEMENT_CARRIES = "chart-no-element-carries"
_FIGURE_TO_DRAW = json.dumps({"data": [{"type": "bar", "x": ["a"], "y": [1]}], "layout": {}})


def _render_chart(page: Page, element_id: str, figure: str | None) -> None:
    """Call the page's global renderChart; a page without it makes evaluate raise, so no test using this passes vacuously.

    A None figure reaches the page as null, which `{{ charts.X | tojson }}` writes for a chart that is None.
    """
    page.evaluate("([elementId, figure]) => renderChart(elementId, figure)", [element_id, figure])


def _errors_naming(page_errors: list[str], element_id: str) -> list[str]:
    """The entries of page_errors that contain element_id, so an unrelated entry, such as a Plotly CDN failure, cannot change a verdict about renderChart."""
    return [error for error in page_errors if element_id in error]


def test_render_chart_logs_an_error_naming_a_target_id_no_element_carries(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
    page_errors: list[str],
) -> None:
    """Given a figure to draw and an id no element carries, renderChart logs one console error naming the id.

    A page writes each chart's id twice, on its container and in its renderChart call, so the two can drift apart.
    """
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")
    expect(page.locator(f"#{_ID_NO_ELEMENT_CARRIES}")).to_have_count(0)

    _render_chart(page, _ID_NO_ELEMENT_CARRIES, _FIGURE_TO_DRAW)

    errors_naming_the_id = _errors_naming(page_errors, _ID_NO_ELEMENT_CARRIES)
    assert len(errors_naming_the_id) == 1, (
        f"expected one console error naming {_ID_NO_ELEMENT_CARRIES!r}, but the page logged: {page_errors}"
    )


@pytest.mark.parametrize("empty_figure", ["{}", None], ids=["empty-object", "null"])
def test_render_chart_logs_nothing_for_an_empty_figure_even_when_no_element_carries_its_id(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
    page_errors: list[str],
    empty_figure: str | None,
) -> None:
    """An empty figure is nothing to draw, so renderChart logs nothing, whether or not an element carries the id.

    sankey_diagram returns '{}' for a run with no energy flow, and results/home.html then still
    calls renderChart('chart-sankey', '{}') with that chart's container left out.
    """
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")
    expect(page.locator(f"#{_ID_NO_ELEMENT_CARRIES}")).to_have_count(0)

    _render_chart(page, _ID_NO_ELEMENT_CARRIES, empty_figure)

    assert _errors_naming(page_errors, _ID_NO_ELEMENT_CARRIES) == [], (
        f"renderChart({_ID_NO_ELEMENT_CARRIES!r}, {empty_figure!r}) has nothing to draw, but the page logged: {page_errors}"
    )


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
