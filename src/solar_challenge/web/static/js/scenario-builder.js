document.addEventListener('alpine:init', () => {
    // A scenario value as a form input holds it: '' (a cleared input, which the server reads as absent) for none
    function inputValue(value) {
        return value === undefined || value === null ? '' : value;
    }

    // The fleet components the form distributes: the prefix of their form fields, which also keys their distribution in
    // dists, the field the form sends a fixed value in, and their spec's key in the scenario grammar, at
    // fleet_distribution.<prefix>.<grammarKey>. templates/scenarios/builder.html calls distribution_card once for each,
    // with its prefix.
    const COMPONENTS = [
        { prefix: 'pv', fixedField: 'pv_capacity_kw', grammarKey: 'capacity_kw' },
        { prefix: 'battery', fixedField: 'battery_capacity_kwh', grammarKey: 'capacity_kwh' },
        { prefix: 'load', fixedField: 'annual_consumption_kwh', grammarKey: 'annual_consumption_kwh' },
    ];

    // Whether `value` is a YAML mapping, as a scenario document and each of its blocks is
    function isMapping(value) {
        return value !== null && typeof value === 'object' && !Array.isArray(value);
    }

    // The form fields whose preview is `scenario`, a document in the preview's grammar. Each component's distribution is
    // the form's one in `dists` with what its spec sets laid over it.
    // Throws, saying why, for a document the form cannot hold.
    function scenarioFormFields(scenario, dists) {
        if (!isMapping(scenario)) {
            throw new Error('it does not hold a YAML mapping');
        }
        const fleet = scenario.fleet_distribution;
        if (!isMapping(fleet)) {
            throw new Error('it has no fleet_distribution: block for the builder to edit (a run export lists its homes instead)');
        }
        const period = scenario.period || {};
        const tariff = scenario.tariff || {};
        const fields = {
            name: inputValue(scenario.name),
            description: inputValue(scenario.description),
            start_date: inputValue(period.start_date),
            end_date: inputValue(period.end_date),
            n_homes: inputValue(fleet.n_homes),
            import_rate: tariff.type === 'flat_rate' ? inputValue(tariff.rate_per_kwh) : '',
            seg_rate_pence_per_kwh: inputValue((scenario.seg || {}).rate_pence_per_kwh),
            dists: Object.fromEntries(COMPONENTS.map((component) => [
                component.prefix, { ...dists[component.prefix], ...componentDistribution(fleet, component) },
            ])),
        };
        if (scenario.location) {
            fields.location_preset = 'custom';
            fields.latitude = inputValue(scenario.location.latitude);
            fields.longitude = inputValue(scenario.location.longitude);
            fields.altitude = inputValue(scenario.location.altitude);
        }
        return fields;
    }

    // The fields of one component's distribution that its spec in `fleet` sets: a fixed number, or a distribution.
    // Throws, naming the spec, for one the form cannot hold.
    function componentDistribution(fleet, { prefix, grammarKey }) {
        const spec = (fleet[prefix] || {})[grammarKey];
        const path = 'fleet_distribution.' + prefix + '.' + grammarKey;
        if (spec === undefined || spec === null || typeof spec === 'number') {
            return { type: '', fixed: inputValue(spec) };
        }
        if (!isMapping(spec)) {
            throw new Error(path + ' must be a number or a distribution, got ' + JSON.stringify(spec));
        }
        if (spec.type === 'weighted_discrete') {
            return { type: spec.type, values: distributionRows(spec, 'weights', 'weight', path) };
        }
        if (spec.type === 'shuffled_pool') {
            return { type: spec.type, entries: distributionRows(spec, 'counts', 'count', path) };
        }
        if (spec.type === 'normal' || spec.type === 'uniform') {
            const distribution = { type: spec.type };
            for (const parameter of ['mean', 'std', 'min', 'max']) {
                distribution[parameter] = inputValue(spec[parameter]);
            }
            return distribution;
        }
        throw new Error(path + ' has distribution type ' + JSON.stringify(spec.type) + ', which the builder does not offer');
    }

    // The form's rows of a distribution: each of its values, with the same entry of its `listKey` list as `rowKey`.
    // Throws, naming `path`, unless both are lists of the same length.
    function distributionRows(spec, listKey, rowKey, path) {
        const values = spec.values;
        const column = spec[listKey];
        if (!Array.isArray(values) || !Array.isArray(column) || values.length !== column.length) {
            throw new Error(path + ' needs values and ' + listKey + ' lists of the same length');
        }
        return values.map((value, i) => ({ value, [rowKey]: column[i] }));
    }

    // The fields of the form the builder sends that give one component's distribution `dist`: its fixed value, or its
    // type and the fields that type reads (all four parameters for normal and uniform alike)
    function componentFormData(dist, { prefix, fixedField }) {
        if (!dist.type) {
            return { [fixedField]: dist.fixed };
        }
        const data = { [prefix + '_distribution_type']: dist.type };
        if (dist.type === 'weighted_discrete') {
            data[prefix + '_wd_values'] = dist.values;
        } else if (dist.type === 'shuffled_pool') {
            data[prefix + '_sp_entries'] = dist.entries;
        } else {
            for (const parameter of ['mean', 'std', 'min', 'max']) {
                data[prefix + '_' + parameter] = dist[parameter];
            }
        }
        return data;
    }

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
        import_rate: 0.245,
        seg_rate_pence_per_kwh: 15.0,

        // Each component's distribution, by its prefix in COMPONENTS: a fixed value while type is ''
        dists: {
            pv: {
                type: '', fixed: 4.0, mean: 4.0, std: 1.0, min: 2.0, max: 8.0,
                values: [{ value: 3.0, weight: 20 }, { value: 4.0, weight: 40 }, { value: 5.0, weight: 30 }],
                entries: [{ value: 3.0, count: 20 }, { value: 4.0, count: 40 }, { value: 5.0, count: 30 }, { value: 6.0, count: 10 }],
            },
            battery: {
                type: '', fixed: 5.0, mean: 5.0, std: 2.0, min: 0, max: 13.5,
                values: [{ value: 0, weight: 40 }, { value: 5.0, weight: 40 }, { value: 10.0, weight: 20 }],
                entries: [{ value: 0, count: 40 }, { value: 5.0, count: 40 }, { value: 10.0, count: 20 }],
            },
            load: {
                type: '', fixed: 3500, mean: 3400, std: 800, min: 2000, max: 5000,
                values: [{ value: 2900, weight: 30 }, { value: 3500, weight: 40 }, { value: 4500, weight: 30 }],
                entries: [{ value: 2900, count: 30 }, { value: 3500, count: 40 }, { value: 4500, count: 30 }],
            },
        },

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

        // Upload YAML file: set the form to the scenario it holds, or, for one the form cannot hold,
        // leave every field as it is and say why in the preview
        async uploadYaml(event) {
            const file = event.target.files[0];
            if (!file) return;
            const text = await file.text();
            event.target.value = '';
            let fields;
            try {
                fields = scenarioFormFields(jsyaml.load(text), this.dists);
            } catch (e) {
                this.yamlPreview = '# ' + file.name + ' was not loaded: ' + e.message;
                return;
            }
            Object.assign(this, fields);
            this.yamlPreview = text;
            this.updatePreview();
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
            for (const component of COMPONENTS) {
                Object.assign(data, componentFormData(this.dists[component.prefix], component));
            }
            return data;
        },

        init() {
            this.loadPresets();
            this.fetchPreview();
            this.$watch('dists', () => this.updatePreview());
        }
    }));
});
