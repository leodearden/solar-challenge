document.addEventListener('alpine:init', () => {
    // A scenario value as a form input holds it, '' (a cleared input, which the server reads as absent) for none, and
    // whether a scenario document or one of its blocks is a mapping: the distribution editor's rules
    const { blankIfNull, isMapping } = DistributionEditor;

    // What the page's forms accept and start at: the #page-limits element base.html writes from page_limits().
    const limits = JSON.parse(document.getElementById('page-limits').textContent);
    // The fleet components, each with its key (its fleet_distribution block), its grammar key and its editor's start
    const components = limits.components;

    // The form fields whose preview is `scenario`, a document in the preview's grammar. Each component's dist is its
    // one in `dists` showing the spec the scenario gives it.
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
            name: blankIfNull(scenario.name),
            description: blankIfNull(scenario.description),
            start_date: blankIfNull(period.start_date),
            end_date: blankIfNull(period.end_date),
            n_homes: blankIfNull(fleet.n_homes),
            import_rate: tariff.type === 'flat_rate' ? blankIfNull(tariff.rate_per_kwh) : '',
            seg_rate_pence_per_kwh: blankIfNull((scenario.seg || {}).rate_pence_per_kwh),
            dists: Object.fromEntries(components.map((component) => [
                component.key,
                DistributionEditor.load(
                    dists[component.key],
                    (fleet[component.key] || {})[component.grammar_key],
                    component,
                    'fleet_distribution.' + component.key + '.' + component.grammar_key,
                ),
            ])),
        };
        if (scenario.location) {
            fields.location_preset = 'custom';
            fields.latitude = blankIfNull(scenario.location.latitude);
            fields.longitude = blankIfNull(scenario.location.longitude);
            fields.altitude = blankIfNull(scenario.location.altitude);
        }
        return fields;
    }

    Alpine.data('scenarioBuilder', (initialSection) => ({
        // Form state
        name: '',
        description: '',
        start_date: limits.default_window[0],
        end_date: limits.default_window[1],
        location_preset: 'bristol',
        latitude: 51.45,
        longitude: -2.58,
        altitude: 11.0,
        n_homes: limits.fleet_size_default,
        import_rate: 0.245,
        seg_rate_pence_per_kwh: '',

        // Each component's distribution editor state, by its key, starting at its start in #page-limits
        dists: Object.fromEntries(components.map((component) => [component.key, structuredClone(component.start)])),

        // UI state
        yamlPreview: '# Configure your scenario...',
        validationResult: null,
        accordionOpen: initialSection,
        presetDropdownOpen: false,
        showSaveModal: false,
        saveName: '',
        presets: [],
        debounceTimer: null,

        // Quick period presets: each button's title names its preset in limits.period_presets
        setPeriod(title) {
            [this.start_date, this.end_date] = limits.period_presets.find((preset) => preset.title === title).window;
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
            for (const component of components) {
                data[component.key] = { [component.grammar_key]: DistributionEditor.wire(this.dists[component.key]) };
            }
            return data;
        },

        init() {
            this.loadPresets();
            this.fetchPreview();
            // The one trigger of the preview: any change to the form getFormData sends, whether a control, a button or
            // an upload made it. $watch reads every field the form sends, rows included, and only those.
            this.$watch(() => this.getFormData(), () => this.updatePreview());
        }
    }));
});
