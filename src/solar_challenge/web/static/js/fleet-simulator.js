document.addEventListener('alpine:init', () => {
    // What the page's forms accept and start at: the #page-limits element base.html writes from page_limits().
    const limits = JSON.parse(document.getElementById('page-limits').textContent);
    // Each fleet component, by its key
    const components = Object.fromEntries(limits.components.map((component) => [component.key, component]));

    // A component's block of the body: its spec, the grammar's own, under its grammar key
    function componentBlock(key, dist) {
        return { [components[key].grammar_key]: DistributionEditor.wire(dist) };
    }

    // A new dist showing the spec `block`, a form's block for component `key`, holds, over `dist`
    function loadedDist(key, dist, block) {
        const component = components[key];
        const path = key + '.' + component.grammar_key;
        return DistributionEditor.load(dist, (block || {})[component.grammar_key], component, path);
    }

    Alpine.data('fleetSimulator', (tariffPresetRates) => ({
        n_homes: limits.fleet_size_default,
        seed: limits.seed_default,
        submitting: false,
        submittedJob: null,
        errorMsg: '',
        importNotice: '',
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
        tariffType: 'flat_rate',
        tariffRatePerKwh: 0.28,
        tariffRates: tariffPresetRates,
        // The economy rate inputs edit the selected type's pair.
        get tariffPeakRate() { return this.tariffRates[this.tariffType]?.peak_rate; },
        set tariffPeakRate(rate) { this.tariffRates[this.tariffType].peak_rate = rate; },
        get tariffOffPeakRate() { return this.tariffRates[this.tariffType]?.off_peak_rate; },
        set tariffOffPeakRate(rate) { this.tariffRates[this.tariffType].off_peak_rate = rate; },
        dispatchStrategyType: 'self_consumption',
        dispatchPeakStart: 16,
        dispatchPeakEnd: 19,
        dispatchImportLimitKw: 3.0,
        segEnabled: false,
        segPreset: 'custom',
        segRatePencePerKwh: 4.0,

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
                if (this.tariffType === 'flat_rate') {
                    payload.tariff = { type: this.tariffType, rate_per_kwh: parseFloat(this.tariffRatePerKwh) };
                } else {
                    payload.tariff = { type: this.tariffType, peak_rate: parseFloat(this.tariffPeakRate), off_peak_rate: parseFloat(this.tariffOffPeakRate) };
                }
            }

            // Fleet-wide SEG overlay
            if (this.segEnabled) {
                if (this.segPreset && this.segPreset !== 'custom') {
                    payload.seg = { preset: this.segPreset };
                } else {
                    payload.seg = { rate_pence_per_kwh: parseFloat(this.segRatePencePerKwh) };
                }
            }

            // Fleet-wide dispatch strategy overlay (only when battery enabled and non-default)
            if (this.batteryEnabled && this.dispatchStrategyType !== 'self_consumption') {
                const ds = { strategy_type: this.dispatchStrategyType };
                if (this.dispatchStrategyType === 'tou_optimized') {
                    ds.peak_hours = [[this.dispatchPeakStart, this.dispatchPeakEnd]];
                } else if (this.dispatchStrategyType === 'peak_shaving') {
                    ds.import_limit_kw = parseFloat(this.dispatchImportLimitKw);
                }
                payload.dispatch_strategy = ds;
            }

            return payload;
        },

        /* ---- Simulation submission ---- */
        /* The server refuses a form it cannot run; a refused Run leaves the earlier run's progress and results. */
        async submitFleet() {
            this.submitting = true;
            this.errorMsg = '';
            try {
                const resp = await fetch('/api/simulate/fleet-from-distribution', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.buildPayload())
                });
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

        /* ---- YAML Export ---- */
        async exportYaml() {
            this.errorMsg = '';
            try {
                const resp = await fetch('/api/fleet/export-yaml', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.buildPayload())
                });
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
            this.tariffType = tariff.type;
            if (tariff.type === 'flat_rate') {
                this.tariffRatePerKwh = tariff.rate_per_kwh;
            } else {
                this.tariffPeakRate = tariff.peak_rate;
                this.tariffOffPeakRate = tariff.off_peak_rate;
            }
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

        _applyDispatch(dispatch) {
            this.dispatchStrategyType = dispatch ? dispatch.strategy_type : 'self_consumption';
            if (this.dispatchStrategyType === 'tou_optimized') {
                [this.dispatchPeakStart, this.dispatchPeakEnd] = dispatch.peak_hours[0];
            } else if (this.dispatchStrategyType === 'peak_shaving') {
                this.dispatchImportLimitKw = dispatch.import_limit_kw;
            }
        }
    }));
});
