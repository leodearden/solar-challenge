/**
 * Draws each Plotly chart of a page from the figure its container carries
 * (data-chart-figure, written by components/macros.html's chart_panel), once
 * the container is shown, so a hidden tab's chart waits for its tab (AC3).
 *
 * Charts are drawn in the theme's colours (AC9), and each drawn chart that is
 * shown is recoloured on theme-changed (AC10). A chart that cannot be drawn,
 * whether its drawing fails at once or after Plotly.newPlot returns, logs a
 * console error naming its container's id, and the page's other charts still
 * draw.
 *
 * Plotly must load first.
 */
(function () {
    "use strict";

    var SOLAR_CHART_CONFIG = { responsive: true, displayModeBar: true, scrollZoom: false };

    /** The containers whose charts are drawn. */
    var _drawn = [];

    /** Check whether dark mode is active. */
    function _isDark() {
        return document.documentElement.classList.contains('dark');
    }

    /** Layout overrides for dark mode. */
    function _darkOverrides() {
        return {
            paper_bgcolor: '#1e293b',
            plot_bgcolor: '#1e293b',
            font: { color: '#e2e8f0' },
            xaxis: { gridcolor: '#334155' },
            yaxis: { gridcolor: '#334155' }
        };
    }

    /** Layout overrides for light mode. */
    function _lightOverrides() {
        return {
            paper_bgcolor: '#ffffff',
            plot_bgcolor: '#ffffff',
            font: { color: '#1e293b' },
            xaxis: { gridcolor: '#e2e8f0' },
            yaxis: { gridcolor: '#e2e8f0' }
        };
    }

    /**
     * Deep-merge theme overrides into a layout object (mutates target).
     */
    function _applyOverrides(layout, overrides) {
        var keys = Object.keys(overrides);
        for (var i = 0; i < keys.length; i++) {
            var k = keys[i];
            if (overrides[k] !== null && typeof overrides[k] === 'object' && !Array.isArray(overrides[k])) {
                if (!layout[k] || typeof layout[k] !== 'object') {
                    layout[k] = {};
                }
                _applyOverrides(layout[k], overrides[k]);
            } else {
                layout[k] = overrides[k];
            }
        }
        return layout;
    }

    /**
     * Draws the chart of container's figure. A throw, or a rejection of the
     * promise Plotly.newPlot returns, logs one console error naming container.
     */
    function _draw(container) {
        new Promise(function (resolve) {
            var fig = JSON.parse(container.dataset.chartFigure);
            var overrides = _isDark() ? _darkOverrides() : _lightOverrides();
            resolve(Plotly.newPlot(container, fig.data, _applyOverrides(fig.layout || {}, overrides), SOLAR_CHART_CONFIG));
        }).then(function () {
            _drawn.push(container);
        }, function (e) {
            console.error('chart-renderer.js: failed to draw the figure of #' + container.id, e);
        });
    }

    /** Draws each observed container the first time it has a width (AC3). */
    var _firstShown = new ResizeObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.contentRect.width > 0) {
                _firstShown.unobserve(entry.target);
                _draw(entry.target);
            }
        });
    });

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-chart-figure]').forEach(function (container) {
            _firstShown.observe(container);
        });
    });

    /** Re-apply theme overrides to each drawn chart that is shown when dark mode toggles (AC10). */
    document.addEventListener('theme-changed', function () {
        var overrides = _isDark() ? _darkOverrides() : _lightOverrides();
        _drawn.forEach(function (container) {
            if (container.offsetParent !== null) {
                Plotly.relayout(container, overrides);
            }
        });
    });
}());
