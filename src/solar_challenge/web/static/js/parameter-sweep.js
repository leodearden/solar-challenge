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
        sweepValues: [],
        sweepResults: [],
        // The label of the parameter the last submitted sweep ran; unlike currentParam, it ignores the select
        sweptParameterLabel: '',
        // The HTML of the sweep's chart panels, as POST /scenarios/sweep/chart answers it; '' hides the chart area
        sweepCharts: '',
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

        // Aborts the current sweep's requests, each point's progress stream and result fetch,
        // and stops the sweep following its remaining points
        _sweepRequests: new AbortController(),

        destroy() {
            this._sweepRequests.abort();
        },

        // Submit sweep
        async submitSweep() {
            this.submitting = true;
            this.errorMsg = '';
            this.sweepResults = [];
            this.sweepCharts = '';
            this.destroy();
            // Label the table and the charts with the parameter this sweep runs, not one selected while it runs
            this.sweptParameterLabel = this.currentParam.label;

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
                    this.sweepValues = data.values || [];
                    // A row shows 'pending' until _followSweep starts following its point, whose job may be running or done by then
                    this.sweepResults = this.sweepValues.map((v, i) => ({
                        value: v,
                        status: 'pending',
                        generation: '-',
                        self_consumption: '-',
                        grid_import: '-',
                        job_id: data.job_ids ? data.job_ids[i] : null,
                        run_id: null,
                    }));
                    // Follow the points' jobs unawaited, so submitting ends once the sweep is accepted.
                    // Read each row back from this.sweepResults: only Alpine's reactive proxy of a row
                    // passes the job's writes to the page.
                    // Draw the charts once every point has ended; _drawSweepCharts reports its own failures.
                    const sweepRequests = new AbortController();
                    this._sweepRequests = sweepRequests;
                    const rows = this.sweepResults.filter(row => row.job_id);
                    this._followSweep(rows, sweepRequests.signal).then(
                        () => this._drawSweepCharts(rows, sweepRequests.signal),
                        e => { this.errorMsg = 'Lost track of the sweep: ' + e.message; }
                    );
                }
            } catch (e) {
                this.errorMsg = 'Network error: ' + e.message;
            } finally {
                this.submitting = false;
            }
        },

        // Follow each point's job in turn until signal aborts, so the page holds one progress stream at a time;
        // tests/e2e/test_parameter_sweep.py::test_another_tab_loads_run_history_while_an_eight_point_sweep_runs says why, and what it costs
        async _followSweep(rows, signal) {
            for (const row of rows) {
                if (signal.aborted) return;
                await this._followPoint(row, signal);
            }
        },

        // Follow one sweep point's job via SSE, writing its status and results into that point's row;
        // resolves once the job ends, the page loses its stream, or signal aborts
        _followPoint(row, signal) {
            return new Promise(resolve => {
                const es = new EventSource('/api/jobs/' + row.job_id + '/progress');
                const end = () => {
                    es.close();
                    signal.removeEventListener('abort', end);
                    resolve();
                };
                signal.addEventListener('abort', end);

                es.addEventListener('progress', (e) => {
                    try {
                        const data = JSON.parse(e.data);
                        row.status = data.status || 'running';
                    } catch(err) {}
                });

                es.addEventListener('complete', (e) => {
                    try {
                        const data = JSON.parse(e.data);
                        row.status = 'completed';
                        if (data.run_id) {
                            // The sweep's charts are drawn from each finished point's run
                            row.run_id = data.run_id;
                            this._fetchResult(row, signal);
                        }
                    } catch(err) {}
                    end();
                });

                const endWith = (status) => {
                    row.status = status;
                    end();
                };
                onJobProgressStreamErrors(es, {
                    failed: () => endWith('failed'),
                    cancelled: () => endWith('cancelled'),
                    lost: () => endWith('failed'),
                });
            });
        },

        // Post the finished points of rows, those whose jobs completed, in sweep order, and show the chart panels
        // POST /scenarios/sweep/chart answers, or why it could not draw them; nothing, if signal aborts first
        async _drawSweepCharts(rows, signal) {
            if (signal.aborted) return;
            const points = rows.filter(row => row.run_id).map(row => ({ value: row.value, run_id: row.run_id }));
            let panels = '';
            let failure = '';
            try {
                const resp = await fetch('/scenarios/sweep/chart', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ parameter_label: this.sweptParameterLabel, points }),
                    signal,
                });
                if (resp.ok) {
                    panels = await resp.text();
                } else {
                    // An answer that is not JSON, such as the app's HTML 500 page, is named by its status
                    const refusal = await resp.json().catch(() => null);
                    failure = (refusal && refusal.error) || 'HTTP ' + resp.status;
                }
            } catch (e) {
                failure = e.message;
            }
            if (signal.aborted) return;
            this.sweepCharts = panels;
            if (failure) {
                this.errorMsg = 'Could not draw the sweep charts: ' + failure;
            }
        },

        // Fetch a completed point's result summary into that point's row, unless signal aborts first
        async _fetchResult(row, signal) {
            try {
                const resp = await fetch('/api/jobs/' + row.job_id + '/results', { signal });
                if (resp.ok) {
                    const data = await resp.json();
                    const s = data.summary || {};
                    row.generation = s.total_generation_kwh != null
                        ? s.total_generation_kwh.toFixed(1) : '-';
                    row.self_consumption = s.self_consumption_ratio != null
                        ? (s.self_consumption_ratio * 100).toFixed(1) + '%' : '-';
                    row.grid_import = s.total_grid_import_kwh != null
                        ? s.total_grid_import_kwh.toFixed(1) : '-';
                }
            } catch(err) {}
        }
    }));
});
