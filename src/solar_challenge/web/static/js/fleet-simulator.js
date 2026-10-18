document.addEventListener('alpine:init', () => {
    // The fleet form's period and seed until it is changed, and when a loaded scenario sets none.
    const DEFAULT_PERIOD_DAYS = 30;
    const DEFAULT_SEED = 42;

    Alpine.data('fleetSimulator', () => ({
        n_homes: 100,
        seed: DEFAULT_SEED,
        submitting: false,
        jobId: null,
        errorMsg: '',
        importNotice: '',
        simName: '',

        /* ---- Period state ---- */
        periodMode: 'preset',
        periodDays: DEFAULT_PERIOD_DAYS,
        startDate: '2024-06-01',
        endDate: '2024-06-30',

        /* ---- PV distribution state ---- */
        pvDist: {
            type: 'shuffled_pool',
            fixed: 4.0,
            mean: 4.0, std: 1.0, min: 2.0, max: 8.0,
            values: [
                { value: 3.0, weight: 20 },
                { value: 4.0, weight: 40 },
                { value: 5.0, weight: 30 },
                { value: 6.0, weight: 10 }
            ],
            entries: [
                { value: 3.0, count: 20 },
                { value: 4.0, count: 40 },
                { value: 5.0, count: 30 },
                { value: 6.0, count: 10 }
            ]
        },

        /* ---- Fleet-wide tariff / dispatch / SEG state ---- */
        tariffEnabled: false,
        tariffType: 'flat_rate',
        tariffRatePerKwh: 0.28,
        tariffPeakRate: 0.35,
        tariffOffPeakRate: 0.13,
        dispatchStrategyType: 'self_consumption',
        dispatchPeakStart: 16,
        dispatchPeakEnd: 21,
        dispatchImportLimitKw: 3.0,
        segEnabled: false,
        segPreset: 'custom',
        segRatePencePerKwh: 4.0,

        /* ---- Battery distribution state ---- */
        batteryEnabled: true,
        batteryDist: {
            type: 'shuffled_pool',
            fixed: 5.0,
            mean: 5.0, std: 2.0, min: 0.0, max: 15.0,
            values: [
                { value: 0, weight: 40 },
                { value: 5.0, weight: 40 },
                { value: 10.0, weight: 20 }
            ],
            entries: [
                { value: 0, count: 40 },
                { value: 5.0, count: 40 },
                { value: 10.0, count: 20 }
            ]
        },

        /* ---- Load distribution state ---- */
        loadDist: {
            type: 'normal',
            fixed: 3500,
            mean: 3400, std: 800, min: 2000, max: 6000,
            values: [
                { value: 2900, weight: 30 },
                { value: 3500, weight: 40 },
                { value: 4500, weight: 30 }
            ],
            entries: [
                { value: 2900, count: 30 },
                { value: 3500, count: 40 },
                { value: 4500, count: 30 }
            ]
        },

        /* ---- Form validation: why Run refuses the form, none when it runs it ---- */
        formErrors() {
            const errors = [];
            const n = parseInt(this.n_homes);
            if (isNaN(n) || n < 1) errors.push('Fleet size must be at least 1');
            if (n > 1000) errors.push('Fleet size must be at most 1000');
            if (this.pvDist.type === 'normal' && parseFloat(this.pvDist.std) <= 0) {
                errors.push('PV std deviation must be positive');
            }
            if ((this.pvDist.type === 'uniform' || this.pvDist.type === 'normal')
                && parseFloat(this.pvDist.min) >= parseFloat(this.pvDist.max)) {
                errors.push('PV min must be less than max');
            }
            return errors;
        },

        /* ---- Build payload from current state ---- */
        buildPayload() {
            const payload = {
                name: this.simName || 'Fleet Simulation',
                n_homes: parseInt(this.n_homes),
                seed: this.seed,
                pv: { capacity_kw: this._buildDistPayload(this.pvDist) },
                load: { annual_consumption_kwh: this._buildDistPayload(this.loadDist) }
            };
            if (this.batteryEnabled) {
                payload.battery = { capacity_kwh: this._buildDistPayload(this.batteryDist) };
            }
            if (this.periodMode === 'preset') {
                payload.days = parseInt(this.periodDays);
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
                    ds.peak_hours = [[parseInt(this.dispatchPeakStart), parseInt(this.dispatchPeakEnd)]];
                } else if (this.dispatchStrategyType === 'peak_shaving') {
                    ds.import_limit_kw = parseFloat(this.dispatchImportLimitKw);
                }
                payload.dispatch_strategy = ds;
            }

            return payload;
        },

        _buildDistPayload(dist) {
            if (!dist.type) return dist.fixed;
            const d = { type: dist.type };
            if (dist.type === 'normal') {
                d.mean = dist.mean;
                d.std = dist.std;
                d.min = dist.min;
                d.max = dist.max;
            } else if (dist.type === 'uniform') {
                d.min = dist.min;
                d.max = dist.max;
            } else if (dist.type === 'weighted_discrete') {
                d.values = dist.values.map(v => ({ value: v.value, weight: v.weight }));
            } else if (dist.type === 'shuffled_pool') {
                d.entries = dist.entries.map(e => ({ value: e.value, count: e.count }));
            }
            return d;
        },

        /* ---- Simulation submission ---- */
        async submitFleet() {
            const errors = this.formErrors();
            if (errors.length > 0) {
                this.errorMsg = errors.join('; ');
                return;
            }
            this.submitting = true;
            this.errorMsg = '';
            this.jobId = null;
            try {
                const resp = await fetch('/api/simulate/fleet-from-distribution', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.buildPayload())
                });
                const data = await resp.json();
                if (resp.ok) {
                    this.jobId = data.job_id;
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
            this.seed = form.seed ?? DEFAULT_SEED;
            this.pvDist = this._distFromConfig(form.pv.capacity_kw, this.pvDist);
            this.batteryEnabled = Boolean(form.battery);
            if (form.battery) {
                this.batteryDist = this._distFromConfig(form.battery.capacity_kwh, this.batteryDist);
            }
            this.loadDist = this._distFromConfig(form.load.annual_consumption_kwh, this.loadDist);
            this._applyPeriod(form.start, form.end);
            this._applyTariff(form.tariff);
            this._applySeg(form.seg);
            this._applyDispatch(form.dispatch_strategy);
        },

        /* The inverse of _buildDistPayload: a fixed value, a number, as the card's Fixed Value (type ''), and a distribution's fields over the card's current distribution. */
        _distFromConfig(spec, current) {
            if (typeof spec === 'number') return { ...current, type: '', fixed: spec };
            return { ...current, ...spec };
        },

        /* A scenario without a period fixes no dates, so the form runs its default period. */
        _applyPeriod(start, end) {
            if (start) {
                this.periodMode = 'custom';
                this.startDate = start;
                this.endDate = end;
            } else {
                this.periodMode = 'preset';
                this.periodDays = DEFAULT_PERIOD_DAYS;
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
