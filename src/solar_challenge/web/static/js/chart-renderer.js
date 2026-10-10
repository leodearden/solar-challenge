/**
 * Shared Plotly chart renderer used by home and fleet results pages.
 *
 * Expects Plotly.js to be loaded before this script.
 *
 * Features:
 *   - Deferred rendering for charts in hidden tabs (AC3)
 *   - Dark mode detection and layout overrides (AC9)
 *   - Re-renders on theme-changed event (AC10)
 */
"use strict";

var SOLAR_CHART_CONFIG = { responsive: true, displayModeBar: true, scrollZoom: false };

/** Registry of all rendered charts for theme toggle re-render (AC10). */
var _CHART_REGISTRY = [];

/** Queue of deferred charts waiting for their container to become visible. */
var _DEFERRED_QUEUE = [];

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
 * Internal: actually render a chart and register it.
 */
function _doRender(elementId, fig) {
    var layout = fig.layout || {};
    var overrides = _isDark() ? _darkOverrides() : _lightOverrides();
    _applyOverrides(layout, overrides);
    Plotly.newPlot(elementId, fig.data, layout, SOLAR_CHART_CONFIG);
    _CHART_REGISTRY.push({ elementId: elementId, fig: fig });
}

/**
 * Render a Plotly chart from a JSON string into a DOM element.
 *
 * An empty figure ('{}' or a falsy jsonStr) draws nothing and logs nothing.
 *
 * A figure whose element is missing draws nothing and logs a console error
 * naming elementId.
 *
 * If the target element is hidden (e.g. in a non-active tab), rendering is
 * deferred until the element becomes visible via a ResizeObserver (AC3).
 *
 * @param {string} elementId - ID of the target DOM element.
 * @param {string} jsonStr   - JSON-encoded Plotly figure (data + layout).
 */
function renderChart(elementId, jsonStr) {
    if (!jsonStr || jsonStr === '{}') return;
    var el = document.getElementById(elementId);
    if (!el) {
        console.error('renderChart: no element has the id "' + elementId + '", so its figure was not drawn');
        return;
    }
    try {
        var fig = JSON.parse(jsonStr);

        // If the element is hidden (zero-size), defer the render (AC3).
        if (el.offsetParent === null) {
            _DEFERRED_QUEUE.push({ elementId: elementId, fig: fig });

            var observer = new ResizeObserver(function(entries) {
                for (var j = 0; j < entries.length; j++) {
                    if (entries[j].contentRect.width > 0) {
                        // Find and remove from deferred queue
                        for (var q = 0; q < _DEFERRED_QUEUE.length; q++) {
                            if (_DEFERRED_QUEUE[q].elementId === elementId) {
                                var entry = _DEFERRED_QUEUE.splice(q, 1)[0];
                                _doRender(entry.elementId, entry.fig);
                                break;
                            }
                        }
                        observer.disconnect();
                        return;
                    }
                }
            });
            observer.observe(el);
            return;
        }

        _doRender(elementId, fig);
    } catch (e) {
        console.error('Failed to render chart ' + elementId, e);
    }
}

/**
 * Re-apply theme overrides to all registered charts when dark mode toggles (AC10).
 */
document.addEventListener('theme-changed', function() {
    var overrides = _isDark() ? _darkOverrides() : _lightOverrides();
    _CHART_REGISTRY.forEach(function(entry) {
        var el = document.getElementById(entry.elementId);
        if (el && el.offsetParent !== null) {
            Plotly.relayout(entry.elementId, overrides);
        }
    });
});
