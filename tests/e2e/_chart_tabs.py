# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drive the chart tabs components/macros.html's chart_tabs draws, through the UI."""

from playwright.sync_api import Page, expect


def open_chart_tab(page: Page, tab_name: str) -> None:
    """Click the chart tab named tab_name, such as "Power Flow"."""
    page.get_by_role("tab", name=tab_name, exact=True).click()


def show_chart_tab(page: Page, tab_name: str, chart_ids: tuple[str, ...]) -> None:
    """Click the chart tab named tab_name and wait until Plotly has drawn each of chart_ids, visible."""
    open_chart_tab(page, tab_name)
    for chart_id in chart_ids:
        expect(page.locator(f"#{chart_id}.js-plotly-plot")).to_be_visible()
