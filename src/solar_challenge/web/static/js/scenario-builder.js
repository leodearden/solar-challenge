document.addEventListener('alpine:init', () => {
    // A scenario value as a form input holds it: '' (a cleared input, which the server reads as absent) for none
    function inputValue(value) {
        return value === undefined || value === null ? '' : value;
    }

    // The fleet components the form distributes: the prefix of their form fields, the field holding a fixed value,
    // and their spec's key in the scenario grammar, at fleet_distribution.<prefix>.<grammarKey>.
    // templates/scenarios/builder.html calls distribution_card once for each, with its prefix and fixedField.
    const COMPONENTS = [
        { prefix: 'pv', fixedField: 'pv_capacity_kw', grammarKey: 'capacity_kw' },
        { prefix: 'battery', fixedField: 'battery_capacity_kwh', grammarKey: 'capacity_kwh' },
        { prefix: 'load', fixedField: 'annual_consumption_kwh', grammarKey: 'annual_consumption_kwh' },
    ];

    // Whether `value` is a YAML mapping, as a scenario document and each of its blocks is
    function isMapping(value) {
        return value !== null && typeof value === 'object' && !Array.isArray(value);
    }

    // The form fields whose preview is `scenario`, a document in the preview's grammar.
    // Throws, saying why, for a document the form cannot hold.
    function scenarioFormFields(scenario) {
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
        };
        for (const component of COMPONENTS) {
            Object.assign(fields, componentFields(fleet, component));
        }
        if (scenario.location) {
            fields.location_preset = 'custom';
            fields.latitude = inputValue(scenario.location.latitude);
            fields.longitude = inputValue(scenario.location.longitude);
            fields.altitude = inputValue(scenario.location.altitude);
        }
        return fields;
    }

    // One component's form fields, read from its spec in `fleet`: a fixed number, or a distribution.
    // Throws, naming the spec, for one the form cannot hold.
    function componentFields(fleet, { prefix, fixedField, grammarKey }) {
        const spec = (fleet[prefix] || {})[grammarKey];
        const path = 'fleet_distribution.' + prefix + '.' + grammarKey;
        if (spec === undefined || spec === null || typeof spec === 'number') {
            return { [prefix + '_distribution_type']: '', [fixedField]: inputValue(spec) };
        }
        if (!isMapping(spec)) {
            throw new Error(path + ' must be a number or a distribution, got ' + JSON.stringify(spec));
        }
        const fields = { [prefix + '_distribution_type']: spec.type };
        if (spec.type === 'weighted_discrete') {
            fields[prefix + '_wd_values'] = distributionRows(spec, 'weights', 'weight', path);
        } else if (spec.type === 'shuffled_pool') {
            fields[prefix + '_sp_entries'] = distributionRows(spec, 'counts', 'count', path);
        } else if (spec.type === 'normal' || spec.type === 'uniform') {
            for (const parameter of ['mean', 'std', 'min', 'max']) {
                fields[prefix + '_' + parameter] = inputValue(spec[parameter]);
            }
        } else {
            throw new Error(path + ' has distribution type ' + JSON.stringify(spec.type) + ', which the builder does not offer');
        }
        return fields;
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

    // The fields of the form the builder sends that give one component: its fixed value, or its distribution's type and
    // the fields that type reads (all four parameters for normal and uniform alike)
    function componentFormData(form, { prefix, fixedField }) {
        const typeField = prefix + '_distribution_type';
        const type = form[typeField];
        if (!type) {
            return { [fixedField]: form[fixedField] };
        }
        const data = { [typeField]: type };
        for (const suffix of distributionFieldSuffixes(type)) {
            data[prefix + '_' + suffix] = form[prefix + '_' + suffix];
        }
        return data;
    }

    // The form fields, after a component's prefix, that hold a distribution of `type`
    function distributionFieldSuffixes(type) {
        if (type === 'weighted_discrete') return ['wd_values'];
        if (type === 'shuffled_pool') return ['sp_entries'];
        return ['mean', 'std', 'min', 'max'];
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

        // Appends `row` to `rows`, one of the form's lists of distribution rows
        addRow(rows, row) {
            rows.push(row);
            this.updatePreview();
        },

        // Whether `rows` has a row to spare: a distribution keeps at least one
        canRemoveRow(rows) {
            return rows.length > 1;
        },

        // Removes row `idx` of `rows`, unless it is the last
        removeRow(rows, idx) {
            if (!this.canRemoveRow(rows)) return;
            rows.splice(idx, 1);
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
                fields = scenarioFormFields(jsyaml.load(text));
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
                Object.assign(data, componentFormData(this, component));
            }
            return data;
        },

        init() {
            this.loadPresets();
            this.fetchPreview();
        }
    }));
});
