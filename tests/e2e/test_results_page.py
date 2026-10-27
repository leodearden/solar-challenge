"""End-to-end tests for the Results page (/results/home/<id>).

Uses seeded data fixtures (no live simulation needed) to verify
page rendering, that each tab shows only its own charts, stat
cards, download links and error handling, that the daily balance
chart agrees with the stat cards, how a chart whose figure
cannot be drawn is reported, that a hidden tab's chart is drawn
only once its tab is shown, and that showing every tab logs no
errors.
Each drawn chart ends as wide as its container whenever the
container's width changes: as base.html's main column slides in
on load, when the sidebar collapses or expands and when the
window narrows, and, for a chart whose tab is hidden at the
time, once its tab is shown again. A chart that cannot be
fitted to its container logs one error naming it.
A chart container added to the page after load is drawn, and
a drawn container given another figure is redrawn with it.
"""

from playwright.sync_api import Locator, Page, expect

from tests._chart_absences import monthly_reason, seasonal_reason
from tests.e2e._chart_tabs import open_chart_tab, show_chart_tab
from tests.e2e._chart_widths import charts_not_as_wide_as_their_containers


# -- The page's chart tabs --------------------------------------------------

# The charts each tab shows for seeded_home_run, the tab selected on load last.
_CHART_IDS_BY_TAB = {
    "Power Flow": ("chart-power-flow",),
    "Battery & Finance": ("chart-battery-soc", "chart-financial"),
    "Analysis": (),
    "Overview": ("chart-sankey", "chart-daily-balance"),
}


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


# -- Each tab shows only its own charts -------------------------------------


def test_results_tabs_each_show_only_their_own_charts(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Clicking each chart tab selects it alone and shows only its own charts, drawn by Plotly.

    Overview is selected on load, so it is clicked last: only then does
    its click have to move the selection.
    """
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")
    selected_tab = page.get_by_role("tab", selected=True)
    last_listed_tab = list(_CHART_IDS_BY_TAB)[-1]
    expect(
        selected_tab,
        f"expected the tab selected on load to be {last_listed_tab!r}, the last in _CHART_IDS_BY_TAB",
    ).to_have_accessible_name(last_listed_tab)

    for tab_name, chart_ids in _CHART_IDS_BY_TAB.items():
        show_chart_tab(page, tab_name, chart_ids)
        expect(selected_tab).to_have_accessible_name(tab_name)
        expect(page.locator(".js-plotly-plot").filter(visible=True)).to_have_count(len(chart_ids))


def test_results_tabs_of_a_one_day_run_give_the_reason_its_monthly_and_seasonal_charts_are_absent(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """The monthly summary needs 90 days and the seasonal comparison 180, and seeded_home_run covers 1."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")

    for tab_name, chart_id, reason in (
        ("Battery & Finance", "chart-monthly", monthly_reason(1)),
        ("Analysis", "chart-seasonal", seasonal_reason(1)),
    ):
        open_chart_tab(page, tab_name)
        absence = page.locator(f"#{chart_id}")
        expect(absence).to_be_visible()
        expect(absence).to_have_text(reason)


# -- Showing every tab logs no errors ---------------------------------------


def test_results_page_shows_every_tab_without_errors(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
    page_errors: list[str],
) -> None:
    """Loading the page and showing each of its tabs logs no console error and throws no uncaught exception.

    chart-renderer.js draws a hidden tab's charts only once the tab is shown, so every tab is shown.
    """
    run_id, _ = seeded_home_run
    response = page.goto(live_server + f"/results/home/{run_id}")
    assert response is not None
    assert response.status == 200
    for tab_name, chart_ids in _CHART_IDS_BY_TAB.items():
        show_chart_tab(page, tab_name, chart_ids)

    assert page_errors == [], f"Errors on /results/home/{run_id}: {page_errors}"


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
    """The entries of page_errors that contain element_id, so an unrelated entry, such as a resource the browser failed to load, cannot change a verdict about the chart."""
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
        open_chart_tab(page, "Power Flow")

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
        open_chart_tab(page, "Power Flow")

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

    open_chart_tab(page, "Power Flow")

    expect(page.locator("#chart-power-flow.js-plotly-plot")).to_be_visible()


# -- Each chart is drawn as wide as its container --------------------------

_OVERVIEW_CHART_IDS = ("chart-sankey", "chart-daily-balance")


def _open_with_the_overview_charts_drawn(page: Page, live_server: str, run_id: str) -> None:
    """Open run_id's results page and wait until Plotly has drawn each chart of Overview, the tab shown on load, visible."""
    page.goto(live_server + f"/results/home/{run_id}")
    for chart_id in _OVERVIEW_CHART_IDS:
        expect(page.locator(f"#{chart_id}.js-plotly-plot")).to_be_visible()


def test_each_overview_chart_is_as_wide_as_its_container_once_the_page_settles(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """The Overview charts are drawn while base.html's main column slides in on load, and each ends as wide as its container."""
    run_id, _ = seeded_home_run
    _open_with_the_overview_charts_drawn(page, live_server, run_id)

    assert charts_not_as_wide_as_their_containers(page, _OVERVIEW_CHART_IDS) == []


def test_after_the_sidebar_collapses_each_chart_is_as_wide_as_its_container_whether_its_tab_was_shown_or_hidden(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
    page_errors: list[str],
) -> None:
    """Collapsing the sidebar widens the main column: the Overview charts, shown then, and Power Flow's chart, drawn but hidden then, each end as wide as its container, and the page logs no error."""
    run_id, _ = seeded_home_run
    _open_with_the_overview_charts_drawn(page, live_server, run_id)
    show_chart_tab(page, "Power Flow", (_POWER_FLOW_CHART_ID,))
    open_chart_tab(page, "Overview")

    page.get_by_title("Collapse sidebar", exact=True).click()
    overview = charts_not_as_wide_as_their_containers(page, _OVERVIEW_CHART_IDS)
    open_chart_tab(page, "Power Flow")
    power_flow = charts_not_as_wide_as_their_containers(page, [_POWER_FLOW_CHART_ID])

    assert (overview, power_flow, page_errors) == ([], [], [])


def test_after_the_sidebar_expands_each_shown_chart_is_as_wide_as_its_container(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Expanding a sidebar collapsed on load narrows the main column, which clips a chart that keeps its width: each Overview chart ends as wide as its container."""
    run_id, _ = seeded_home_run
    page.add_init_script("localStorage.setItem('sidebarOpen', 'false')")
    _open_with_the_overview_charts_drawn(page, live_server, run_id)

    page.get_by_title("Expand sidebar", exact=True).click()

    assert charts_not_as_wide_as_their_containers(page, _OVERVIEW_CHART_IDS) == []


def test_each_overview_chart_hidden_as_the_page_settles_is_as_wide_as_its_container_once_its_tab_is_shown_again(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Showing Power Flow before the main column has settled hides the Overview charts before they are fitted to their containers' settled width; once Overview is shown again, each ends as wide as its container."""
    run_id, _ = seeded_home_run
    _open_with_the_overview_charts_drawn(page, live_server, run_id)
    show_chart_tab(page, "Power Flow", (_POWER_FLOW_CHART_ID,))

    open_chart_tab(page, "Overview")

    assert charts_not_as_wide_as_their_containers(page, _OVERVIEW_CHART_IDS) == []


def test_after_the_window_narrows_each_shown_chart_is_as_wide_as_its_container(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """At 1100 px the window is still Tailwind's lg, so the sidebar stays and the main column narrows: each Overview chart ends as wide as its container."""
    run_id, _ = seeded_home_run
    _open_with_the_overview_charts_drawn(page, live_server, run_id)

    page.set_viewport_size({"width": 1100, "height": 720})

    assert charts_not_as_wide_as_their_containers(page, _OVERVIEW_CHART_IDS) == []


# -- A chart that cannot be fitted is reported -----------------------------

_FAILED_FITTING = "the fitting failed after Plotly.Plots.resize returned"
_FAILED_TO_FIT_THE_POWER_FLOW_CHART = f"failed to fit the chart of #{_POWER_FLOW_CHART_ID}"
_REJECT_THE_FIRST_FITTING_OF = """([chartId, failure]) => {
    const resize = Plotly.Plots.resize;
    let rejected = false;
    Plotly.Plots.resize = function (container) {
        if (container.id === chartId && !rejected) {
            rejected = true;
            return Promise.reject(new Error(failure));
        }
        return resize.apply(this, arguments);
    };
}"""


def test_a_chart_whose_fitting_fails_after_plotly_plots_resize_returns_logs_one_error_naming_its_id(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
    page_errors: list[str],
) -> None:
    """Plotly.Plots.resize returns a promise, which rejects when a fit fails; that failure is one error saying which chart failed to fit, not an uncaught rejection.

    Only the chart's first fit fails, so the test need not know how often it is fitted:
    its container can change size, and the chart be fitted again, while the page settles.
    """
    run_id, _ = seeded_home_run
    _open_with_the_overview_charts_drawn(page, live_server, run_id)
    page.evaluate(_REJECT_THE_FIRST_FITTING_OF, [_POWER_FLOW_CHART_ID, _FAILED_FITTING])

    with page.expect_console_message(lambda message: _POWER_FLOW_CHART_ID in message.text):
        open_chart_tab(page, "Power Flow")

    errors_naming_the_chart = _errors_naming(page_errors, _POWER_FLOW_CHART_ID)
    failures_to_fit = [error for error in errors_naming_the_chart if _FAILED_TO_FIT_THE_POWER_FLOW_CHART in error]
    uncaught_failures = [
        error for error in page_errors if _FAILED_FITTING in error and _POWER_FLOW_CHART_ID not in error
    ]
    assert (len(errors_naming_the_chart), len(failures_to_fit), uncaught_failures) == (1, 1, []), (
        f"expected one error naming {_POWER_FLOW_CHART_ID!r}, saying {_FAILED_TO_FIT_THE_POWER_FLOW_CHART!r}, "
        f"and no other carrying {_FAILED_FITTING!r}, but the page logged: {page_errors}"
    )


# -- A chart container added or given another figure after load is drawn --

# Adds, right after the drawn container it is called on, a container carrying that
# container's figure but not its class, the js-plotly-plot Plotly gave it.
_ADD_A_CONTAINER_OF_THE_SAME_FIGURE_AFTER = """(drawn) => {
    const added = document.createElement('div');
    added.id = 'chart-added-late';
    added.dataset.chartFigure = drawn.dataset.chartFigure;
    drawn.after(added);
}"""

_GIVE_IT_THE_SANKEYS_FIGURE = """(container) => {
    container.dataset.chartFigure = document.getElementById('chart-sankey').dataset.chartFigure;
}"""


def test_a_chart_container_added_to_a_shown_tab_after_load_is_drawn(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
    page_errors: list[str],
) -> None:
    run_id, _ = seeded_home_run
    _open_with_the_overview_charts_drawn(page, live_server, run_id)

    page.locator("#chart-daily-balance").evaluate(_ADD_A_CONTAINER_OF_THE_SAME_FIGURE_AFTER)

    expect(page.locator("#chart-added-late.js-plotly-plot")).to_be_visible()
    assert page_errors == []


def test_a_drawn_chart_container_given_another_figure_is_redrawn_with_it(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
    page_errors: list[str],
) -> None:
    """The daily balance's container, given the Sankey's figure, is drawn titled as the Sankey's layout is."""
    run_id, _ = seeded_home_run
    _open_with_the_overview_charts_drawn(page, live_server, run_id)
    title = page.locator("#chart-daily-balance .gtitle")
    expect(title).to_have_text("Daily Energy Balance")

    page.locator("#chart-daily-balance").evaluate(_GIVE_IT_THE_SANKEYS_FIGURE)

    expect(title).to_have_text("Energy Flow")
    assert page_errors == []


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
    """/results/<id no run has> -> the dashboard, which flashes "Run not found."."""
    page.goto(live_server + "/results/nonexistent-run-id-xyz")

    expect(page).to_have_url(live_server + "/")
    expect(page.get_by_text("Run not found.", exact=True)).to_be_visible()
