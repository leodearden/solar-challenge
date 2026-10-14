/**
 * Draws each Plotly chart of a page from the figure its container carries
 * (data-chart-figure, written by components/macros.html's chart_panel), once
 * the container is shown, so a hidden tab's chart waits for its tab (AC3).
 *
 * Charts are drawn in the theme's colours (AC9), and each drawn chart is
 * recoloured on theme-changed once it is shown (AC10): at once if it is, else
 * when its tab is next shown. A chart that cannot be drawn, whether its
 * drawing fails at once or after Plotly.newPlot returns, logs a console error
 * naming its container's id, and the page's other charts still draw.
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

    /** Layout overrides for the active theme. */
    function _themeOverrides() {
        return _isDark() ? _darkOverrides() : _lightOverrides();
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
            var overrides = _themeOverrides();
            resolve(Plotly.newPlot(container, fig.data, _applyOverrides(fig.layout || {}, overrides), SOLAR_CHART_CONFIG));
        }).then(function () {
            _drawn.push(container);
        }, function (e) {
            console.error('chart-renderer.js: failed to draw the figure of #' + container.id, e);
        });
    }

    /** Applies the active theme's overrides to the chart of container, which is drawn. */
    function _recolour(container) {
        Plotly.relayout(container, _themeOverrides());
    }

    /**
     * Returns a ResizeObserver that calls action with each observed container
     * the first time it has a width, at the next frame if it has one already,
     * so nothing is laid out in a hidden tab.
     */
    function _onceShown(action) {
        return new ResizeObserver(function (entries, observer) {
            entries.forEach(function (entry) {
                if (entry.contentRect.width > 0) {
                    observer.unobserve(entry.target);
                    action(entry.target);
                }
            });
        });
    }

    /** Draws each observed container the first time it is shown (AC3). */
    var _drawOnceShown = _onceShown(_draw);

    /** Recolours each observed container's chart the first time it is shown (AC10). */
    var _recolourOnceShown = _onceShown(_recolour);

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-chart-figure]').forEach(function (container) {
            _drawOnceShown.observe(container);
        });
    });

    /** Recolours each drawn chart once it is shown, in the theme that is active then (AC10). */
    document.addEventListener('theme-changed', function () {
        _drawn.forEach(function (container) {
            _recolourOnceShown.observe(container);
        });
    });
}());
