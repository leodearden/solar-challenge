/**
 * Draws each Plotly chart of a page from the figure its container carries
 * (data-chart-figure, written by components/macros.html's chart_panel), once
 * the container is shown, so a hidden tab's chart waits for its tab (AC3).
 * A container added to the page after load, or given another figure, is
 * drawn the same way once shown, so a page that inserts chart panels, as the
 * sweep page does, needs no renderer API.
 * Each drawn chart is fitted to its container whenever the container's size
 * changes while it is shown, as when base.html's main column slides in on
 * load, the sidebar is toggled, the window is resized or the chart's tab is
 * shown again, so the chart ends as wide as its container.
 *
 * Each chart takes its chrome colours from the computed style of its
 * container (AC9): color for its texts, and --chart-grid for its grid, zero
 * and polar axis lines. They are applied to xaxis, yaxis and every other x
 * axis, y axis and polar subplot the figure's layout names, and a polar disc
 * is drawn in the figure's plot background. Paper and plot backgrounds are
 * left transparent, as charts._SHARED_LAYOUT sets them, so the card shows
 * through. Each drawn chart is recoloured on theme-changed once it is shown
 * (AC10): at once if it is, else when its tab is next shown. A chart that
 * cannot be drawn, fitted or recoloured, whether Plotly fails at once or
 * after it returns, logs a console error naming its container's id, and the
 * page's other charts still draw.
 *
 * Plotly must load first.
 */
(function () {
    "use strict";

    var SOLAR_CHART_CONFIG = { displayModeBar: true, scrollZoom: false };

    /** A layout key naming a subplot: an x axis, a y axis or a polar subplot, such as 'yaxis2'. */
    var _SUBPLOT_KEY = /^(?:[xy]axis|polar)\d*$/;

    /** The containers whose charts are drawn, each mapped to the keys of its chart's subplots. */
    var _drawn = new Map();

    /**
     * The chrome colours the computed style of container names: text, its
     * color, for the chart's texts, and grid, its --chart-grid, for the
     * chart's grid, zero and polar axis lines.
     */
    function _chromeColours(container) {
        var style = getComputedStyle(container);
        return { text: style.color, grid: style.getPropertyValue('--chart-grid').trim() };
    }

    /** Whether the chrome colours a and b are the same. */
    function _sameColours(a, b) {
        return a.text === b.text && a.grid === b.grid;
    }

    /**
     * The keys of the subplots of layout: xaxis and yaxis, which a cartesian
     * figure draws whether or not its layout names them, then every other x
     * axis, y axis and polar subplot the layout names.
     */
    function _subplotKeys(layout) {
        return ['xaxis', 'yaxis'].concat(Object.keys(layout).filter(function (key) {
            return _SUBPLOT_KEY.test(key) && key !== 'xaxis' && key !== 'yaxis';
        }));
    }

    /** Whether the subplot key names a polar subplot, such as 'polar2'. */
    function _isPolar(key) {
        return key.startsWith('polar');
    }

    /**
     * The Plotly attribute paths, such as 'yaxis2.gridcolor', that draw a
     * chart's chrome in colours, each mapped to its colour: the chart's texts,
     * and the grid, zero and polar axis lines of the subplots whose keys
     * subplots lists. A path sets only its leaf, so Plotly.relayout keeps the
     * rest of the attribute's container, such as an axis title or a radial
     * axis range.
     */
    function _chrome(subplots, colours) {
        var paths = { 'font.color': colours.text };
        subplots.forEach(function (key) {
            if (_isPolar(key)) {
                ['radialaxis', 'angularaxis'].forEach(function (axis) {
                    paths[key + '.' + axis + '.gridcolor'] = colours.grid;
                    paths[key + '.' + axis + '.linecolor'] = colours.grid;
                });
            } else {
                paths[key + '.gridcolor'] = colours.grid;
                paths[key + '.zerolinecolor'] = colours.grid;
            }
        });
        return paths;
    }

    /**
     * The Plotly attribute paths, such as 'polar.bgcolor', that draw in
     * background the disc of each polar subplot whose key subplots lists.
     */
    function _polarDiscs(subplots, background) {
        var paths = {};
        subplots.filter(_isPolar).forEach(function (key) {
            paths[key + '.bgcolor'] = background;
        });
        return paths;
    }

    /** Sets in layout the value of each attribute path of paths, creating each container on the way that layout lacks, and returns layout. */
    function _setPaths(layout, paths) {
        Object.keys(paths).forEach(function (path) {
            var names = path.split('.');
            var leaf = names.pop();
            var parent = names.reduce(function (node, name) {
                if (node[name] === null || typeof node[name] !== 'object') {
                    node[name] = {};
                }
                return node[name];
            }, layout);
            parent[leaf] = paths[path];
        });
        return layout;
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
     * Draws the chart of container's figure in the chrome colours container
     * names. A polar disc is a plot area, so it is drawn in the figure's plot
     * background, in every theme. The theme-changed listener recolours only
     * drawn charts, so a chart whose container names other colours once its
     * drawing finishes, after a theme change, is recoloured here.
     */
    function _draw(container) {
        var subplots;
        var drawnIn;
        _attempt(container, 'draw the figure of', function () {
            var fig = JSON.parse(container.dataset.chartFigure);
            var layout = fig.layout || {};
            subplots = _subplotKeys(layout);
            drawnIn = _chromeColours(container);
            var paths = Object.assign(_polarDiscs(subplots, layout.plot_bgcolor), _chrome(subplots, drawnIn));
            return Plotly.newPlot(container, fig.data, _setPaths(layout, paths), SOLAR_CHART_CONFIG);
        }, function () {
            _drawn.set(container, subplots);
            _fitWhileShown.observe(container);
            if (!_sameColours(_chromeColours(container), drawnIn)) {
                _recolourOnceShown.observe(container);
            }
        });
    }

    /** Recolours the chart of container, which is drawn, in the chrome colours container names now, and changes nothing else of it. */
    function _recolour(container) {
        _attempt(container, 'recolour the chart of', function () {
            return Plotly.relayout(container, _chrome(_drawn.get(container), _chromeColours(container)));
        });
    }

    /** Fits the chart of container, which is drawn, to the container's size. */
    function _fit(container) {
        _attempt(container, 'fit the chart of', function () {
            return Plotly.Plots.resize(container);
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

    /** Fits each observed container's chart, which is drawn, whenever the container's size changes while it has a width. */
    var _fitWhileShown = new ResizeObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.contentRect.width > 0) {
                _fit(entry.target);
            }
        });
    });

    /** Draws, once shown, node if it is a container, an element carrying a figure, and each container inside it; a text node holds none. */
    function _drawEachContainerIn(node) {
        if (!(node instanceof Element)) {
            return;
        }
        if (node.matches('[data-chart-figure]')) {
            _drawOnceShown.observe(node);
        }
        node.querySelectorAll('[data-chart-figure]').forEach(function (container) {
            _drawOnceShown.observe(container);
        });
    }

    /**
     * Draws, once shown, each container added to the page after load, and each
     * container given another figure, which _draw redraws with Plotly.newPlot.
     * A container whose figure was removed is left as it is.
     */
    var _drawContainersChangedAfterLoad = new MutationObserver(function (records) {
        records.forEach(function (record) {
            if (record.type === 'childList') {
                record.addedNodes.forEach(_drawEachContainerIn);
            } else if (record.target.hasAttribute('data-chart-figure')) {
                _drawOnceShown.observe(record.target);
            }
        });
    });

    document.addEventListener('DOMContentLoaded', function () {
        _drawEachContainerIn(document.body);
        _drawContainersChangedAfterLoad.observe(document.body, {
            childList: true, subtree: true, attributes: true, attributeFilter: ['data-chart-figure'],
        });
    });

    /** Recolours each drawn chart once it is shown, in the chrome colours its container names then (AC10). */
    document.addEventListener('theme-changed', function () {
        _drawn.forEach(function (subplots, container) {
            _recolourOnceShown.observe(container);
        });
    });
}());
