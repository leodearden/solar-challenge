document.addEventListener('alpine:init', () => {
    Alpine.data('scenarioBuilder', () => ({
        // Form state
        name: '',
        description: '',
        start_date: '2024-01-01',
        end_date: '2024-12-31',
        location_preset: 'bristol',
        latitude: 51.45,
        longitude: -2.58,
        altitude: 11.0,
        n_homes: 100,
        pv_capacity_kw: 4.0,
        pv_distribution_type: '',
        pv_mean: 4.0,
        pv_std: 1.0,
        pv_min: 2.0,
        pv_max: 8.0,
        battery_capacity_kwh: 5.0,
        battery_distribution_type: '',
        battery_mean: 5.0,
        battery_std: 2.0,
        battery_min: 0,
        battery_max: 13.5,
        annual_consumption_kwh: 3500,
        load_distribution_type: '',
        load_mean: 3400,
        load_std: 800,
        load_min: 2000,
        load_max: 5000,
        import_rate: 0.245,
        seg_rate_pence_per_kwh: 15.0,

        // Weighted discrete / shuffled pool arrays
        pv_wd_values: [{ value: 3.0, weight: 20 }, { value: 4.0, weight: 40 }, { value: 5.0, weight: 30 }],
        pv_sp_entries: [{ value: 3.0, count: 20 }, { value: 4.0, count: 40 }, { value: 5.0, count: 30 }, { value: 6.0, count: 10 }],
        battery_wd_values: [{ value: 0, weight: 40 }, { value: 5.0, weight: 40 }, { value: 10.0, weight: 20 }],
        battery_sp_entries: [{ value: 0, count: 40 }, { value: 5.0, count: 40 }, { value: 10.0, count: 20 }],
        load_wd_values: [{ value: 2900, weight: 30 }, { value: 3500, weight: 40 }, { value: 4500, weight: 30 }],
        load_sp_entries: [{ value: 2900, count: 30 }, { value: 3500, count: 40 }, { value: 4500, count: 30 }],

        // UI state
        yamlPreview: '# Configure your scenario...',
        validationResult: null,
        accordionOpen: 'general',
        presetDropdownOpen: false,
        showSaveModal: false,
        saveName: '',
        presets: [],
        debounceTimer: null,

        // Quick period presets
        setPeriod(preset) {
            if (preset === 'full-year') {
                this.start_date = '2024-01-01';
                this.end_date = '2024-12-31';
            } else if (preset === 'summer') {
                this.start_date = '2024-06-01';
                this.end_date = '2024-08-31';
            } else if (preset === 'winter') {
                this.start_date = '2024-12-01';
                this.end_date = '2025-02-28';
            } else if (preset === 'week') {
                this.start_date = '2024-06-01';
                this.end_date = '2024-06-07';
            } else if (preset === 'month') {
                this.start_date = '2024-06-01';
                this.end_date = '2024-06-30';
            }
            this.updatePreview();
        },

        // Debounced YAML preview update
        updatePreview() {
            clearTimeout(this.debounceTimer);
            this.debounceTimer = setTimeout(() => this.fetchPreview(), 500);
        },

        // Fetch YAML preview from the API
        async fetchPreview() {
            const formData = this.getFormData();
            try {
                const resp = await fetch('/api/scenarios/preview-yaml', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(formData)
                });
                const result = await resp.json();
                this.yamlPreview = result.yaml !== undefined ? result.yaml : '# ' + result.error;
            } catch (e) {
                this.yamlPreview = '# Error: could not generate preview';
            }
        },

        // Validate scenario
        async validateScenario() {
            const formData = this.getFormData();
            try {
                const resp = await fetch('/api/scenarios/validate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(formData)
                });
                this.validationResult = await resp.json();
            } catch (e) {
                this.validationResult = { valid: false, errors: ['Network error'] };
            }
        },

        // Save scenario
        async saveScenario() {
            this.saveName = this.name || 'My Scenario';
            this.showSaveModal = true;
        },

        async doSave() {
            const name = this.saveName.trim();
            if (!name) return;
            this.showSaveModal = false;
            const formData = this.getFormData();
            try {
                const resp = await fetch('/api/scenarios/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name, config: formData })
                });
                const result = await resp.json();
                if (resp.ok) {
                    this.validationResult = { valid: true, errors: [], message: 'Scenario saved as: ' + name };
                } else {
                    this.validationResult = { valid: false, errors: [result.error || 'Save failed'] };
                }
            } catch (e) {
                this.validationResult = { valid: false, errors: ['Network error during save'] };
            }
        },

        // Download YAML
        downloadYaml() {
            const blob = new Blob([this.yamlPreview], { type: 'text/yaml' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = (this.name || 'scenario') + '.yaml';
            a.click();
            URL.revokeObjectURL(url);
        },

        // Upload YAML file
        async uploadYaml(event) {
            const file = event.target.files[0];
            if (!file) return;
            const text = await file.text();
            this.yamlPreview = text;
            try {
                const parsed = (typeof jsyaml !== 'undefined') ? jsyaml.load(text) : null;
                if (!parsed) return;
                if (parsed.name) this.name = parsed.name;
                if (parsed.description) this.description = parsed.description;
                if (parsed.start_date) this.start_date = parsed.start_date;
                if (parsed.end_date) this.end_date = parsed.end_date;
                if (parsed.n_homes) this.n_homes = parsed.n_homes;
                if (parsed.import_rate !== undefined) this.import_rate = parsed.import_rate;
                if (parsed.export_rate !== undefined) this.export_rate = parsed.export_rate;
                // Location
                if (parsed.location) {
                    if (parsed.location.latitude !== undefined) {
                        this.location_preset = 'custom';
                        this.latitude = parsed.location.latitude;
                        this.longitude = parsed.location.longitude || -2.58;
                        if (parsed.location.altitude !== undefined) this.altitude = parsed.location.altitude;
                    }
                }
                // PV distribution
                if (parsed.fleet_distribution && parsed.fleet_distribution.pv_capacity_kw) {
                    var pv = parsed.fleet_distribution.pv_capacity_kw;
                    if (typeof pv === 'number') {
                        this.pv_distribution_type = '';
                        this.pv_capacity_kw = pv;
                    } else if (pv.type) {
                        this.pv_distribution_type = pv.type;
                        if (pv.mean !== undefined) this.pv_mean = pv.mean;
                        if (pv.std !== undefined) this.pv_std = pv.std;
                        if (pv.min !== undefined) this.pv_min = pv.min;
                        if (pv.max !== undefined) this.pv_max = pv.max;
                    }
                }
                // Battery distribution
                if (parsed.fleet_distribution && parsed.fleet_distribution.battery_capacity_kwh) {
                    var batt = parsed.fleet_distribution.battery_capacity_kwh;
                    if (typeof batt === 'number') {
                        this.battery_distribution_type = '';
                        this.battery_capacity_kwh = batt;
                    } else if (batt.type) {
                        this.battery_distribution_type = batt.type;
                        if (batt.mean !== undefined) this.battery_mean = batt.mean;
                        if (batt.std !== undefined) this.battery_std = batt.std;
                        if (batt.min !== undefined) this.battery_min = batt.min;
                        if (batt.max !== undefined) this.battery_max = batt.max;
                    }
                }
                // Load distribution
                if (parsed.fleet_distribution && parsed.fleet_distribution.annual_consumption_kwh) {
                    var load = parsed.fleet_distribution.annual_consumption_kwh;
                    if (typeof load === 'number') {
                        this.load_distribution_type = '';
                        this.annual_consumption_kwh = load;
                    } else if (load.type) {
                        this.load_distribution_type = load.type;
                        if (load.mean !== undefined) this.load_mean = load.mean;
                        if (load.std !== undefined) this.load_std = load.std;
                        if (load.min !== undefined) this.load_min = load.min;
                        if (load.max !== undefined) this.load_max = load.max;
                    }
                }
                this.updatePreview();
            } catch (e) { /* ignore parse errors */ }
            event.target.value = '';
        },

        // Load presets list
        async loadPresets() {
            try {
                const resp = await fetch('/api/scenarios/presets');
                const data = await resp.json();
                this.presets = data.presets || [];
            } catch (e) {
                this.presets = [];
            }
        },

        // Load a specific preset
        async loadPreset(presetName) {
            try {
                const resp = await fetch('/api/scenarios/presets/' + presetName);
                const data = await resp.json();
                if (data.config) {
                    const cfg = data.config;
                    if (cfg.name) this.name = cfg.name;
                    if (cfg.location) {
                        this.latitude = cfg.location.latitude || 51.45;
                        this.longitude = cfg.location.longitude || -2.58;
                        this.location_preset = 'custom';
                    }
                    if (cfg.fleet_distribution) {
                        const fd = cfg.fleet_distribution;
                        if (fd.n_homes) this.n_homes = fd.n_homes;
                    }
                }
                this.presetDropdownOpen = false;
                this.updatePreview();
            } catch (e) { /* ignore */ }
        },

        getFormData() {
            const data = {
                name: this.name,
                description: this.description,
                start_date: this.start_date,
                end_date: this.end_date,
                location_preset: this.location_preset,
                n_homes: this.n_homes,
                import_rate: this.import_rate,
                seg_rate_pence_per_kwh: this.seg_rate_pence_per_kwh,
            };
            if (this.location_preset === 'custom') {
                data.latitude = this.latitude;
                data.longitude = this.longitude;
                data.altitude = this.altitude;
            }
            if (this.pv_distribution_type === 'weighted_discrete') {
                data.pv_distribution_type = 'weighted_discrete';
                data.pv_wd_values = this.pv_wd_values;
            } else if (this.pv_distribution_type === 'shuffled_pool') {
                data.pv_distribution_type = 'shuffled_pool';
                data.pv_sp_entries = this.pv_sp_entries;
            } else if (this.pv_distribution_type) {
                data.pv_distribution_type = this.pv_distribution_type;
                data.pv_mean = this.pv_mean;
                data.pv_std = this.pv_std;
                data.pv_min = this.pv_min;
                data.pv_max = this.pv_max;
            } else {
                data.pv_capacity_kw = this.pv_capacity_kw;
            }
            if (this.battery_distribution_type === 'weighted_discrete') {
                data.battery_distribution_type = 'weighted_discrete';
                data.battery_wd_values = this.battery_wd_values;
            } else if (this.battery_distribution_type === 'shuffled_pool') {
                data.battery_distribution_type = 'shuffled_pool';
                data.battery_sp_entries = this.battery_sp_entries;
            } else if (this.battery_distribution_type) {
                data.battery_distribution_type = this.battery_distribution_type;
                data.battery_mean = this.battery_mean;
                data.battery_std = this.battery_std;
                data.battery_min = this.battery_min;
                data.battery_max = this.battery_max;
            } else {
                data.battery_capacity_kwh = this.battery_capacity_kwh;
            }
            if (this.load_distribution_type === 'weighted_discrete') {
                data.load_distribution_type = 'weighted_discrete';
                data.load_wd_values = this.load_wd_values;
            } else if (this.load_distribution_type === 'shuffled_pool') {
                data.load_distribution_type = 'shuffled_pool';
                data.load_sp_entries = this.load_sp_entries;
            } else if (this.load_distribution_type) {
                data.load_distribution_type = this.load_distribution_type;
                data.load_mean = this.load_mean;
                data.load_std = this.load_std;
                data.load_min = this.load_min;
                data.load_max = this.load_max;
            } else {
                data.annual_consumption_kwh = this.annual_consumption_kwh;
            }
            return data;
        },

        init() {
            this.loadPresets();
            this.fetchPreview();
        }
    }));
});
