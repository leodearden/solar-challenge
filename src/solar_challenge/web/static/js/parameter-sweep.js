document.addEventListener('alpine:init', () => {
    Alpine.data('parameterSweep', () => ({
        // Sweep configuration
        parameter: 'pv_capacity_kw',
        minVal: 2.0,
        maxVal: 8.0,
        steps: 5,
        mode: 'linear',

        // Base config
        configMode: 'preset',
        basePreset: '',
        baseConfig: {
            battery_kwh: 5.0,
            location: 'bristol',
            days: 7
        },

        // Results
        sweepId: null,
        sweepValues: [],
        sweepResults: [],
        submitting: false,
        errorMsg: '',

        // Sweep point preview calculations
        get previewValues() {
            const min = parseFloat(this.minVal);
            const max = parseFloat(this.maxVal);
            const n = parseInt(this.steps);
            if (isNaN(min) || isNaN(max) || isNaN(n) || n < 2 || min >= max) return [];

            let values = [];
            if (this.mode === 'geometric') {
                const logMin = Math.log(min);
                const logMax = Math.log(max);
                for (let i = 0; i < n; i++) {
                    values.push(Math.exp(logMin + (logMax - logMin) * i / (n - 1)));
                }
            } else {
                for (let i = 0; i < n; i++) {
                    values.push(min + (max - min) * i / (n - 1));
                }
            }
            return values.map(v => Math.round(v * 1000) / 1000);
        },

        // Parameter options
        parameterOptions: [
            { value: 'pv_capacity_kw', label: 'PV Capacity (kW)', min: 1, max: 20, defaultMin: 2, defaultMax: 8 },
            { value: 'battery_capacity_kwh', label: 'Battery Capacity (kWh)', min: 0, max: 50, defaultMin: 0, defaultMax: 13.5 },
            { value: 'annual_consumption_kwh', label: 'Annual Consumption (kWh)', min: 1000, max: 10000, defaultMin: 2000, defaultMax: 5000 },
        ],

        get currentParam() {
            return this.parameterOptions.find(p => p.value === this.parameter) || this.parameterOptions[0];
        },

        onParameterChange() {
            const param = this.currentParam;
            this.minVal = param.defaultMin;
            this.maxVal = param.defaultMax;
        },

        // Active EventSource connections
        _eventSources: [],

        destroy() {
            this._eventSources.forEach(es => es.close());
            this._eventSources = [];
        },

        // Submit sweep
        async submitSweep() {
            this.submitting = true;
            this.errorMsg = '';
            this.sweepResults = [];
            this.destroy();

            const payload = {
                parameter: this.parameter,
                min: parseFloat(this.minVal),
                max: parseFloat(this.maxVal),
                steps: parseInt(this.steps),
                mode: this.mode,
                base_config: this.baseConfig,
            };

            try {
                const resp = await fetch('/api/simulate/sweep', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (!resp.ok) {
                    this.errorMsg = data.error || 'Sweep submission failed';
                } else {
                    this.sweepId = data.sweep_id;
                    this.sweepValues = data.values || [];
                    // Populate initial results as pending
                    this.sweepResults = this.sweepValues.map((v, i) => ({
                        value: v,
                        status: 'pending',
                        generation: '-',
                        self_consumption: '-',
                        grid_import: '-',
                        job_id: data.job_ids ? data.job_ids[i] : null,
                    }));
                    // Start polling each job
                    this.sweepResults.forEach((result, idx) => {
                        if (result.job_id) {
                            this._pollJob(result.job_id, idx);
                        }
                    });
                }
            } catch (e) {
                this.errorMsg = 'Network error: ' + e.message;
            } finally {
                this.submitting = false;
            }
        },

        // Poll a single sweep job via SSE
        _pollJob(jobId, idx) {
            const es = new EventSource('/api/jobs/' + jobId + '/progress');
            this._eventSources.push(es);

            es.addEventListener('progress', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    if (this.sweepResults[idx]) {
                        this.sweepResults[idx].status = data.status || 'running';
                    }
                } catch(err) {}
            });

            es.addEventListener('complete', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    if (this.sweepResults[idx]) {
                        this.sweepResults[idx].status = 'completed';
                        if (data.run_id) {
                            this._fetchResult(data.run_id, idx);
                        }
                    }
                } catch(err) {}
                es.close();
                this._checkAllDone();
            });

            es.addEventListener('error', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    if (this.sweepResults[idx]) {
                        this.sweepResults[idx].status = 'failed';
                    }
                } catch(err) {
                    if (this.sweepResults[idx] && this.sweepResults[idx].status !== 'completed') {
                        this.sweepResults[idx].status = 'failed';
                    }
                }
                es.close();
                this._checkAllDone();
            });
        },

        // Fetch completed result summary
        async _fetchResult(runId, idx) {
            try {
                const resp = await fetch('/api/jobs/' + this.sweepResults[idx].job_id + '/results');
                if (resp.ok) {
                    const data = await resp.json();
                    const s = data.summary || {};
                    if (this.sweepResults[idx]) {
                        this.sweepResults[idx].generation = s.total_generation_kwh != null
                            ? s.total_generation_kwh.toFixed(1) : '-';
                        this.sweepResults[idx].self_consumption = s.self_consumption_ratio != null
                            ? (s.self_consumption_ratio * 100).toFixed(1) + '%' : '-';
                        this.sweepResults[idx].grid_import = s.total_grid_import_kwh != null
                            ? s.total_grid_import_kwh.toFixed(1) : '-';
                    }
                }
            } catch(err) {}
        },

        // Check if all sweep jobs are done and render chart
        _checkAllDone() {
            const allDone = this.sweepResults.every(r => r.status === 'completed' || r.status === 'failed');
            if (allDone) {
                this._renderChart();
            }
        },

        // Render sweep results chart
        _renderChart() {
            const canvas = document.getElementById('sweep-chart');
            if (!canvas || typeof Chart === 'undefined') return;
            const ctx = canvas.getContext('2d');
            const labels = this.sweepResults.map(r => r.value);
            const genData = this.sweepResults.map(r => parseFloat(r.generation) || 0);
            const importData = this.sweepResults.map(r => parseFloat(r.grid_import) || 0);

            if (canvas._chartInstance) canvas._chartInstance.destroy();
            canvas._chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        { label: 'Generation (kWh)', data: genData, borderColor: '#f59e0b', fill: false },
                        { label: 'Grid Import (kWh)', data: importData, borderColor: '#6b7280', fill: false },
                    ]
                },
                options: { responsive: true, scales: { x: { title: { display: true, text: this.currentParam.label } } } }
            });
        }
    }));
});
