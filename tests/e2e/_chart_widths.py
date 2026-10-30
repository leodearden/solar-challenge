# SPDX-License-Identifier: AGPL-3.0-or-later
"""Find the Plotly charts on a page that are not drawn as wide as their containers once the page's layout has settled."""

from collections.abc import Sequence

from playwright.sync_api import Page

_SETTLE_DEADLINE_MS = 5000
_POLL_INTERVAL_MS = 25

_CHARTS_NOT_AS_WIDE_AS_THEIR_CONTAINERS = """async ({chartIds, deadlineMs, pollIntervalMs}) => {
    const deadline = performance.now() + deadlineMs;
    const charts = chartIds.map(id => {
        const chart = document.getElementById(id);
        if (chart === null) throw new Error(`No element carries the chart id ${id}`);
        return chart;
    });
    const pause = () => new Promise(resolve => setTimeout(resolve, pollIntervalMs));
    const aTransitionRuns = () => document.getAnimations().some(animation => animation instanceof CSSTransition);
    const widths = chart => {
        const svg = chart.querySelector('.main-svg');
        return {chart: chart.id, drawn: svg ? Number(svg.getAttribute('width')) : null, container: chart.clientWidth};
    };
    const fits = ({drawn, container}) => drawn !== null && Math.abs(drawn - container) <= 1;
    const misfits = () => charts.map(widths).filter(entry => !fits(entry));
    while (aTransitionRuns() && performance.now() < deadline) {
        await pause();
    }
    let found = misfits();
    while (found.length > 0 && performance.now() < deadline) {
        await pause();
        found = misfits();
    }
    return found;
}"""


def charts_not_as_wide_as_their_containers(page: Page, chart_ids: Sequence[str]) -> list[dict[str, object]]:
    """The charts among chart_ids, the ids of page's chart containers, that Plotly has not drawn as wide as their containers, within 1 px.

    It waits until no CSS transition runs, so the page's layout has settled, and then until each chart is
    that wide, for at most 5 s in all. Each entry names a chart that still is not:
    {'chart': its container's id, 'drawn': the width of its first .main-svg, or None while Plotly has drawn none,
    'container': its container's clientWidth}. It raises playwright's Error if no element carries one of chart_ids.
    """
    misfits: list[dict[str, object]] = page.evaluate(
        _CHARTS_NOT_AS_WIDE_AS_THEIR_CONTAINERS,
        {"chartIds": list(chart_ids), "deadlineMs": _SETTLE_DEADLINE_MS, "pollIntervalMs": _POLL_INTERVAL_MS},
    )
    return misfits
