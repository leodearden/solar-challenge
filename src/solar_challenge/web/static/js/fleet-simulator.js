document.addEventListener('alpine:init', () => {
    Alpine.data('fleetSimulator', () => ({
        n_homes: 100,
        submitting: false,
        jobId: null,
        runId: null,
        errorMsg: '',

        /* ---- Progress tracking state ---- */
        progress: 0,
        step: 'Queued',
        message: 'Waiting to start...',
        status: 'idle',
        elapsed: 0,
        startTime: null,
        timer: null,
        evtSource: null,
        error: '',
        completedRunId: '',

        /* ---- PV distribution state ---- */
        pvDist: {
            type: 'shuffled_pool',
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

        /* ---- Battery distribution state ---- */
        batteryEnabled: true,
        batteryDist: {
            type: 'shuffled_pool',
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

        /* ---- Helper functions for distribution rows ---- */
        addPvRow() {
            if (this.pvDist.type === 'weighted_discrete') {
                this.pvDist.values.push({ value: 4.0, weight: 10 });
            } else if (this.pvDist.type === 'shuffled_pool') {
                this.pvDist.entries.push({ value: 4.0, count: 10 });
            }
        },
        removePvRow(idx) {
            if (this.pvDist.type === 'weighted_discrete' && this.pvDist.values.length > 1) {
                this.pvDist.values.splice(idx, 1);
            } else if (this.pvDist.type === 'shuffled_pool' && this.pvDist.entries.length > 1) {
                this.pvDist.entries.splice(idx, 1);
            }
        },

        addBatteryRow() {
            if (this.batteryDist.type === 'weighted_discrete') {
                this.batteryDist.values.push({ value: 5.0, weight: 10 });
            } else if (this.batteryDist.type === 'shuffled_pool') {
                this.batteryDist.entries.push({ value: 5.0, count: 10 });
            }
        },
        removeBatteryRow(idx) {
            if (this.batteryDist.type === 'weighted_discrete' && this.batteryDist.values.length > 1) {
                this.batteryDist.values.splice(idx, 1);
            } else if (this.batteryDist.type === 'shuffled_pool' && this.batteryDist.entries.length > 1) {
                this.batteryDist.entries.splice(idx, 1);
            }
        },

        addLoadRow() {
            if (this.loadDist.type === 'weighted_discrete') {
                this.loadDist.values.push({ value: 3500, weight: 10 });
            } else if (this.loadDist.type === 'shuffled_pool') {
                this.loadDist.entries.push({ value: 3500, count: 10 });
            }
        },
        removeLoadRow(idx) {
            if (this.loadDist.type === 'weighted_discrete' && this.loadDist.values.length > 1) {
                this.loadDist.values.splice(idx, 1);
            } else if (this.loadDist.type === 'shuffled_pool' && this.loadDist.entries.length > 1) {
                this.loadDist.entries.splice(idx, 1);
            }
        },

        /* ---- Form validation ---- */
        validationErrors: {},
        validate() {
            const errors = {};
            const n = parseInt(this.n_homes);
            if (isNaN(n) || n < 1) errors.n_homes = 'Fleet size must be at least 1';
            if (n > 1000) errors.n_homes = 'Fleet size must be at most 1000';
            // Validate PV distribution
            if (this.pvDist.type === 'normal') {
                if (parseFloat(this.pvDist.std) <= 0) errors.pv_std = 'PV std deviation must be positive';
            }
            if (this.pvDist.type === 'uniform' || this.pvDist.type === 'normal') {
                if (parseFloat(this.pvDist.min) >= parseFloat(this.pvDist.max)) errors.pv_range = 'PV min must be less than max';
            }
            this.validationErrors = errors;
            return Object.keys(errors).length === 0;
        },

        /* ---- Build payload from current state ---- */
        buildPayload() {
            const payload = {
                n_homes: parseInt(this.n_homes),
                seed: 42,
                pv: { capacity_kw: this._buildDistPayload(this.pvDist) },
                load: { annual_consumption_kwh: this._buildDistPayload(this.loadDist) }
            };
            if (this.batteryEnabled) {
                payload.battery = { capacity_kwh: this._buildDistPayload(this.batteryDist) };
            }
            return payload;
        },

        _buildDistPayload(dist) {
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
            if (!this.validate()) return;
            this.submitting = true;
            this.errorMsg = '';
            this.jobId = null;
            this.runId = null;
            this.status = 'idle';
            this.progress = 0;
            this.error = '';
            this.completedRunId = '';
            try {
                const resp = await fetch('/api/simulate/fleet-from-distribution', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.buildPayload())
                });
                const data = await resp.json();
                if (resp.ok) {
                    this.jobId = data.job_id;
                    this.runId = data.run_id;
                    this.startProgressTracking();
                } else {
                    this.errorMsg = data.error || 'Submission failed';
                }
            } catch (e) {
                this.errorMsg = 'Network error: ' + e.message;
            } finally {
                this.submitting = false;
            }
        },

        /* ---- SSE Progress tracking ---- */
        startProgressTracking() {
            this.status = 'queued';
            this.step = 'Queued';
            this.message = 'Waiting to start...';
            this.startTime = Date.now();
            this.timer = setInterval(() => {
                this.elapsed = Math.floor((Date.now() - this.startTime) / 1000);
            }, 1000);

            this.evtSource = new EventSource('/api/jobs/' + this.jobId + '/progress');

            this.evtSource.addEventListener('progress', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    if (data.progress !== undefined) this.progress = data.progress * 100;
                    if (data.progress_pct !== undefined) this.progress = data.progress_pct;
                    if (data.current_step) this.step = data.current_step;
                    if (data.message) this.message = data.message;
                    if (data.homes_completed !== undefined && data.total_homes) {
                        this.message = 'Processing home ' + data.homes_completed + '/' + data.total_homes;
                    }
                    if (data.status) this.status = data.status;
                } catch(err) {}
            });

            this.evtSource.addEventListener('complete', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    this.status = 'completed';
                    this.progress = 100;
                    this.step = 'Done';
                    this.message = data.message || 'Fleet simulation completed successfully';
                    if (data.run_id) this.completedRunId = data.run_id;
                } catch(err) {}
                this.stopProgressTracking();
            });

            this.evtSource.addEventListener('error', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    this.status = 'failed';
                    this.error = data.message || data.error || 'An unexpected error occurred';
                } catch(err) {
                    if (this.status !== 'completed') {
                        this.status = 'failed';
                        this.error = 'Lost connection to server';
                    }
                }
                this.stopProgressTracking();
            });
        },

        stopProgressTracking() {
            if (this.evtSource) {
                this.evtSource.close();
                this.evtSource = null;
            }
            if (this.timer) {
                clearInterval(this.timer);
                this.timer = null;
            }
        },

        destroy() {
            this.stopProgressTracking();
        },

        formatTime(seconds) {
            const m = Math.floor(seconds / 60);
            const s = seconds % 60;
            return m > 0 ? m + 'm ' + s + 's' : s + 's';
        },

        /* ---- YAML Export ---- */
        async exportYaml() {
            try {
                const resp = await fetch('/api/fleet/export-yaml', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.buildPayload())
                });
                if (!resp.ok) {
                    this.errorMsg = 'Export failed';
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
            try {
                const resp = await fetch('/api/fleet/import-yaml', {
                    method: 'POST',
                    headers: { 'Content-Type': 'text/yaml' },
                    body: text
                });
                const data = await resp.json();
                if (resp.ok) {
                    this.applyConfig(data);
                } else {
                    this.errorMsg = data.error || 'Import failed';
                }
            } catch (e) {
                this.errorMsg = 'Import error: ' + e.message;
            }
            /* Reset file input */
            event.target.value = '';
        },

        /* ---- Apply imported config to form state ---- */
        applyConfig(cfg) {
            this.n_homes = cfg.n_homes || 100;
            if (cfg.pv && cfg.pv.capacity_kw) {
                this.pvDist = this._distFromConfig(cfg.pv.capacity_kw, this.pvDist);
            }
            if (cfg.battery && cfg.battery.capacity_kwh) {
                this.batteryEnabled = true;
                this.batteryDist = this._distFromConfig(cfg.battery.capacity_kwh, this.batteryDist);
            } else {
                this.batteryEnabled = false;
            }
            if (cfg.load && cfg.load.annual_consumption_kwh) {
                this.loadDist = this._distFromConfig(cfg.load.annual_consumption_kwh, this.loadDist);
            }
        },

        _distFromConfig(spec, defaults) {
            if (typeof spec !== 'object' || !spec.type) return defaults;
            const d = { ...defaults, type: spec.type };
            if (spec.type === 'normal') {
                d.mean = spec.mean || 0;
                d.std = spec.std || 1;
                d.min = spec.min || 0;
                d.max = spec.max || 10;
            } else if (spec.type === 'uniform') {
                d.min = spec.min || 0;
                d.max = spec.max || 10;
            } else if (spec.type === 'weighted_discrete') {
                if (spec.values && spec.weights) {
                    d.values = spec.values.map((v, i) => ({
                        value: v, weight: spec.weights[i] || 1
                    }));
                }
            } else if (spec.type === 'shuffled_pool') {
                if (spec.values && spec.counts) {
                    d.entries = spec.values.map((v, i) => ({
                        value: v, count: spec.counts[i] || 1
                    }));
                }
            }
            return d;
        },

        /* ---- Preset loading ---- */
        async loadPreset(name) {
            if (!name) return;
            try {
                const resp = await fetch('/api/fleet/import-yaml', {
                    method: 'POST',
                    headers: { 'Content-Type': 'text/yaml' },
                    body: name
                });
                if (resp.ok) {
                    const data = await resp.json();
                    this.applyConfig(data);
                }
            } catch (e) {
                this.errorMsg = 'Preset load error: ' + e.message;
            }
        }
    }));
});
