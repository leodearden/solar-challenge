document.addEventListener('alpine:init', () => {
    // What the page's forms accept and start at: the #page-limits element base.html writes from page_limits().
    const limits = JSON.parse(document.getElementById('page-limits').textContent);
    // Each fleet component, by its key
    const components = Object.fromEntries(limits.components.map((component) => [component.key, component]));

    // A component's block of the body: its spec, the grammar's own, under its grammar key
    function componentBlock(key, dist) {
        return { [components[key].grammar_key]: DistributionEditor.wire(dist) };
    }

    // The most distinct values a preview summary lists, each with its count of homes
    const MOST_VALUES_LISTED = 8;

    // One home's value as a preview summary shows it: rounded to 2 decimals, or null for a null
    function shownValue(value) {
        return value === null ? null : Math.round(value * 100) / 100;
    }

    // A shown value as a preview summary writes it: in `unit`, or 'unset' for a null
    function previewValue(value, unit) {
        return value === null ? 'unset' : `${String(value)} ${unit}`;
    }

    // A count of homes as a preview summary writes it
    function homesCount(count) {
        return count === 1 ? '1 home' : `${count} homes`;
    }

    // A card's summary of `values`, one per home: each distinct shown value, ascending, with its count of homes,
    // or, past MOST_VALUES_LISTED distinct shown values, the min, median (the lower middle home's) and max
    function previewSummary(values, unit) {
        const sorted = values.map(shownValue).sort((a, b) => (a === null) - (b === null) || a - b);
        const counts = new Map();
        for (const value of sorted) {
            counts.set(value, (counts.get(value) || 0) + 1);
        }
        if (counts.size <= MOST_VALUES_LISTED) {
            return [...counts].map(([value, count]) => `${previewValue(value, unit)} \u00d7 ${homesCount(count)}`).join(', ');
        }
        const median = sorted[Math.floor((sorted.length - 1) / 2)];
        return `min ${previewValue(sorted[0], unit)}, median ${previewValue(median, unit)}, `
            + `max ${previewValue(sorted[sorted.length - 1], unit)}`;
    }

    // A new dist showing the spec `block`, a form's block for component `key`, holds, over `dist`
    function loadedDist(key, dist, block) {
        const component = components[key];
        const path = key + '.' + component.grammar_key;
        return DistributionEditor.load(dist, (block || {})[component.grammar_key], component, path);
    }

    // How the form holds, posts and loads a setting of each input kind, form_choices.SettingInput's values
    const SETTING_INPUTS = {
        number: {
            held: (start) => start,
            posted: (held) => held,
            loaded: (held, value) => value,
        },
        // The tariff's clock, posted as null, or one custom window, whose hours are kept while the clock is chosen
        clock_or_window: {
            held: (start) => ({ clock: false, hours: [...start[0]] }),
            posted: (held) => (held.clock ? null : [[...held.hours]]),
            loaded: (held, value) => (value === null ? { ...held, clock: true } : { clock: false, hours: [...value[0]] }),
        },
    };

    // The one of `choices`, a table's choices as FormChoice.as_json writes them, whose type is `type`
    function choiceOf(choices, type) {
        return choices.find((choice) => choice.type === type);
    }

    // A typed block's state: the first choice's type, and each choice's settings held at their starts, by type and key
    function choiceState(choices) {
        const settings = Object.fromEntries(choices.map((choice) => [
            choice.type,
            Object.fromEntries(choice.settings.map((setting) => [setting.key, SETTING_INPUTS[setting.input].held(setting.start)])),
        ]));
        return { type: choices[0].type, settings };
    }

    // The block `state` posts: its type under `typeKey`, and each setting of its type's choice
    function postedBlock(choices, state, typeKey) {
        const held = state.settings[state.type];
        const posted = choiceOf(choices, state.type).settings.map((setting) => [
            setting.key, SETTING_INPUTS[setting.input].posted(held[setting.key]),
        ]);
        return Object.fromEntries([[typeKey, state.type], ...posted]);
    }

    // A new state holding `block`, a block postedBlock posts, over `state`: every other type keeps its settings
    function loadedState(choices, state, block, typeKey) {
        const type = block[typeKey];
        const held = { ...state.settings[type] };
        for (const setting of choiceOf(choices, type).settings) {
            held[setting.key] = SETTING_INPUTS[setting.input].loaded(held[setting.key], block[setting.key]);
        }
        return { type, settings: { ...state.settings, [type]: held } };
    }

    Alpine.data('fleetSimulator', (tariffChoices, dispatchChoices) => ({
        n_homes: limits.fleet_size_default,
        seed: limits.seed_default,
        submitting: false,
        submittedJob: null,
        errorMsg: '',
        importNotice: '',
        // Each component's summary of the homes the last preview built, by component key
        previewSummaries: {},
        // The number of the latest preview asked for; the page drops the answer to any other
        latestPreview: 0,
        simName: '',

        /* ---- Period state ---- */
        periodMode: 'preset',
        periodDays: limits.default_days,
        startDate: limits.custom_range_default[0],
        endDate: limits.custom_range_default[1],

        /* ---- Each component's distribution editor state: its start in #page-limits ---- */
        pvDist: structuredClone(components.pv.start),
        batteryEnabled: true,
        batteryDist: structuredClone(components.battery.start),
        loadDist: structuredClone(components.load.start),

        /* ---- Fleet-wide tariff / dispatch / SEG state ---- */
        tariffEnabled: false,
        // The tariff and dispatch strategy chosen, each choice keeping its own settings
        tariff: choiceState(tariffChoices),
        dispatch: choiceState(dispatchChoices),
        segEnabled: false,
        segPreset: 'custom',
        segRatePencePerKwh: 4.0,

        /* A summary describes the form its preview posted, so a change to the form clears it and drops an answer still to come. */
        init() {
            this.$watch(() => JSON.stringify(this.buildPayload()), (posted, before) => {
                if (posted !== before) this._forgetPreview();
            });
        },

        /* ---- Build payload from current state ---- */
        buildPayload() {
            const payload = {
                name: this.simName,
                n_homes: this.n_homes,
                seed: this.seed,
                pv: componentBlock('pv', this.pvDist),
                load: componentBlock('load', this.loadDist)
            };
            if (this.batteryEnabled) {
                payload.battery = componentBlock('battery', this.batteryDist);
            }
            if (this.periodMode === 'preset') {
                payload.days = this.periodDays;
            } else {
                payload.start = this.startDate;
                payload.end = this.endDate;
            }

            // Fleet-wide tariff overlay
            if (this.tariffEnabled) {
                payload.tariff = postedBlock(tariffChoices, this.tariff, 'type');
            }

            // Fleet-wide SEG overlay
            if (this.segEnabled) {
                if (this.segPreset && this.segPreset !== 'custom') {
                    payload.seg = { preset: this.segPreset };
                } else {
                    payload.seg = { rate_pence_per_kwh: parseFloat(this.segRatePencePerKwh) };
                }
            }

            // Fleet-wide dispatch strategy overlay, for the homes with a battery
            if (this.batteryEnabled) {
                payload.dispatch_strategy = postedBlock(dispatchChoices, this.dispatch, 'strategy_type');
            }

            return payload;
        },

        /* POST the form, the body buildPayload builds, to `url` */
        _postFleetForm(url) {
            return fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.buildPayload())
            });
        },

        /* ---- Simulation submission ---- */
        /* The server refuses a form it cannot run; a refused Run leaves the earlier run's progress and results. */
        async submitFleet() {
            this.submitting = true;
            this.errorMsg = '';
            try {
                const resp = await this._postFleetForm('/api/simulate/fleet-from-distribution');
                const data = await resp.json();
                if (resp.ok) {
                    this.submittedJob = data;
                } else {
                    this.errorMsg = data.error || 'Submission failed';
                }
            } catch (e) {
                this.errorMsg = 'Network error: ' + e.message;
            } finally {
                this.submitting = false;
            }
        },

        /* ---- Preview ---- */
        /* Each card's summary of the homes Run builds from the form, or the server's refusal. */
        async preview() {
            const preview = this._forgetPreview();
            this.errorMsg = '';
            try {
                const resp = await this._postFleetForm('/api/fleet/preview-distribution');
                const data = await resp.json();
                if (preview !== this.latestPreview) return;
                if (!resp.ok) {
                    this.errorMsg = data.error || 'Preview failed';
                    return;
                }
                this.previewSummaries = Object.fromEntries(
                    Object.entries(data.values).map(([key, values]) => [key, previewSummary(values, components[key].unit)])
                );
            } catch (e) {
                if (preview !== this.latestPreview) return;
                this.errorMsg = 'Preview error: ' + e.message;
            }
        },

        /* Clear every summary and drop the answer to each preview asked for so far; the number of the next preview */
        _forgetPreview() {
            this.previewSummaries = {};
            return ++this.latestPreview;
        },

        /* ---- YAML Export ---- */
        async exportYaml() {
            this.errorMsg = '';
            try {
                const resp = await this._postFleetForm('/api/fleet/export-yaml');
                if (!resp.ok) {
                    const data = await resp.json();
                    this.errorMsg = data.error || 'Export failed';
                    return;
                }
                const blob = await resp.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'fleet-config.yaml';
                a.click();
                URL.revokeObjectURL(url);
            } catch (e) {
                this.errorMsg = 'Export error: ' + e.message;
            }
        },

        /* ---- YAML Import ---- */
        async importYaml(event) {
            const file = event.target.files[0];
            if (!file) return;
            const text = await file.text();
            await this._loadFleetForm('/api/fleet/import-yaml', {
                method: 'POST',
                headers: { 'Content-Type': 'text/yaml' },
                body: text
            });
            /* Reset file input */
            event.target.value = '';
        },

        /* ---- Preset loading ---- */
        loadPreset(name) {
            return this._loadFleetForm('/api/fleet/presets/' + encodeURIComponent(name));
        },

        /* ---- Apply the {form, not_loaded} answer of an import or preset ---- */
        async _loadFleetForm(url, options) {
            this.errorMsg = '';
            this.importNotice = '';
            try {
                const resp = await fetch(url, options);
                const data = await resp.json();
                if (!resp.ok) {
                    this.errorMsg = data.error || 'Load failed';
                    return;
                }
                this.applyConfig(data.form);
                if (data.not_loaded.length > 0) {
                    this.importNotice = 'Not loaded: the fleet form has no control for '
                        + data.not_loaded.join(', ') + '.';
                }
            } catch (e) {
                this.errorMsg = 'Load error: ' + e.message;
            }
        },

        /* ---- Apply a fleet form, the body buildPayload posts, to form state ---- */
        applyConfig(form) {
            this.simName = form.name ?? '';
            this.n_homes = form.n_homes;
            this.seed = form.seed ?? limits.seed_default;
            this.pvDist = loadedDist('pv', this.pvDist, form.pv);
            this.batteryEnabled = Boolean(form.battery);
            if (form.battery) {
                this.batteryDist = loadedDist('battery', this.batteryDist, form.battery);
            }
            this.loadDist = loadedDist('load', this.loadDist, form.load);
            this._applyPeriod(form.start, form.end);
            this._applyTariff(form.tariff);
            this._applySeg(form.seg);
            this._applyDispatch(form.dispatch_strategy);
        },

        /* A scenario without a period fixes no dates, so the form runs its default period. */
        _applyPeriod(start, end) {
            if (start) {
                this.periodMode = 'custom';
                this.startDate = start;
                this.endDate = end;
            } else {
                this.periodMode = 'preset';
                this.periodDays = limits.default_days;
            }
        },

        _applyTariff(tariff) {
            this.tariffEnabled = Boolean(tariff);
            if (!tariff) return;
            this.tariff = loadedState(tariffChoices, this.tariff, tariff, 'type');
        },

        _applySeg(seg) {
            this.segEnabled = Boolean(seg);
            if (!seg) return;
            if (seg.preset) {
                this.segPreset = seg.preset;
            } else {
                this.segPreset = 'custom';
                this.segRatePencePerKwh = seg.rate_pence_per_kwh;
            }
        },

        /* A form without a dispatch strategy runs the first choice's, the strategy a battery that names none runs. */
        _applyDispatch(dispatch) {
            if (dispatch) {
                this.dispatch = loadedState(dispatchChoices, this.dispatch, dispatch, 'strategy_type');
            } else {
                this.dispatch.type = dispatchChoices[0].type;
            }
        }
    }));
});
