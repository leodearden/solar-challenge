/**
 * Draws each Plotly chart of a page from the figure its container carries
 * (data-chart-figure, written by components/macros.html's chart_panel), once
 * the container is shown, so a hidden tab's chart waits for its tab (AC3).
 *
 * Charts are drawn in the theme's colours (AC9), and each drawn chart is
 * recoloured on theme-changed once it is shown (AC10): at once if it is, else
 * when its tab is next shown. A chart that cannot be drawn or recoloured,
 * whether Plotly fails at once or after it returns, logs a console error
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

    /** Layout overrides for dark mode if dark is true, else for light mode. */
    function _themeOverrides(dark) {
        return dark ? _darkOverrides() : _lightOverrides();
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
     * The leaves of the nested overrides, each keyed by its Plotly attribute
     * path, such as 'font.color'. Given a nested object, Plotly.relayout
     * replaces that whole container, axis titles and all, while a path sets
     * only its leaf.
     */
    function _attributePaths(overrides, prefix) {
        var paths = {};
        Object.keys(overrides).forEach(function (key) {
            var path = prefix ? prefix + '.' + key : key;
            var value = overrides[key];
            if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
                Object.assign(paths, _attributePaths(value, path));
            } else {
                paths[path] = value;
            }
        });
        return paths;
    }

    /**
     * Calls plotlyCall, which throws or returns the promise of a Plotly call,
     * and then onSuccess, if given, once that promise resolves. Either failure,
     * a throw or a rejection, logs one console error naming the activity and
     * the id of container.
     */
    function _attempt(container, activity, plotlyCall, onSuccess) {
        new Promise(function (resolve) {
            resolve(plotlyCall());
        }).then(onSuccess, function (e) {
            console.error('chart-renderer.js: failed to ' + activity + ' #' + container.id, e);
        });
    }

    /**
     * Draws the chart of container's figure in the active theme's colours. The
     * theme-changed listener recolours only drawn charts, so a chart whose
     * drawing finishes after a theme change is recoloured here.
     */
    function _draw(container) {
        var drawnDark = _isDark();
        _attempt(container, 'draw the figure of', function () {
            var fig = JSON.parse(container.dataset.chartFigure);
            var layout = _applyOverrides(fig.layout || {}, _themeOverrides(drawnDark));
            return Plotly.newPlot(container, fig.data, layout, SOLAR_CHART_CONFIG);
        }, function () {
            _drawn.push(container);
            if (_isDark() !== drawnDark) {
                _recolourOnceShown.observe(container);
            }
        });
    }

    /** Applies the active theme's overrides to the chart of container, which is drawn, and changes nothing else of it. */
    function _recolour(container) {
        _attempt(container, 'recolour the chart of', function () {
            return Plotly.relayout(container, _attributePaths(_themeOverrides(_isDark())));
        });
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
