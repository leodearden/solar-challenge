document.addEventListener('alpine:init', () => {
    // A null or absent form value as a form input holds it: '' (a cleared input, which the server reads as absent)
    const { blankIfNull } = DistributionEditor;

    // What the page's forms accept and start at: the #page-limits element base.html writes from page_limits().
    const limits = JSON.parse(document.getElementById('page-limits').textContent);
    // The fleet components, each with its key (its fleet_distribution block), its grammar key and its editor's start
    const components = limits.components;

    // The builder form's fields other than the custom coordinates and the components' blocks
    const FORM_FIELDS = [
        'name', 'description', 'start_date', 'end_date', 'location_preset', 'n_homes', 'seed', 'import_rate',
        'seg_rate_pence_per_kwh',
    ];
    // The custom location's coordinates, which a form holds only for a location under no preset
    const CUSTOM_COORDINATES = ['latitude', 'longitude', 'altitude'];

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
        seed: limits.seed_default,
        import_rate: limits.flat_rate_start,
        seg_rate_pence_per_kwh: '',

        // Each component's distribution editor state, by its key, starting at its start in #page-limits
        dists: Object.fromEntries(components.map((component) => [component.key, structuredClone(component.start)])),

        // UI state
        yamlPreview: '# Configure your scenario...',
        importNotice: '',
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
                    await this.loadPresets();
                } else {
                    this.validationResult = { valid: false, errors: result.errors || [result.error] };
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

        // Upload YAML file: the server imports it as the builder's form
        async uploadYaml(event) {
            const file = event.target.files[0];
            if (!file) return;
            const text = await file.text();
            event.target.value = '';
            await this._loadForm(
                '/api/scenarios/import-yaml',
                { method: 'POST', headers: { 'Content-Type': 'text/yaml' }, body: text },
                file.name,
            );
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

        // Load the Load Preset menu's item `preset`, by its name and source
        async loadPreset(preset) {
            this.presetDropdownOpen = false;
            await this._loadForm(
                '/api/scenarios/presets/' + encodeURIComponent(preset.name)
                    + '?' + new URLSearchParams({ source: preset.source }),
                {},
                preset.name,
            );
        },

        // Fetch `url` with `options` for the form the server imports from the scenario `what` names, and set the
        // form to it, naming the scenario's settings the builder has no control for; for a scenario the server
        // refuses, leave every field as it is and say why in the preview
        async _loadForm(url, options, what) {
            let resp, data;
            try {
                resp = await fetch(url, options);
                data = await resp.json();
            } catch (e) {
                this.yamlPreview = '# ' + what + ' was not loaded: ' + e.message;
                return;
            }
            if (!resp.ok) {
                this.yamlPreview = '# ' + what + ' was not loaded: ' + data.error;
                return;
            }
            this.applyForm(data.form);
            // A form equal to the one shown changes nothing $watch reads, yet replaces a refusal the preview shows
            this.updatePreview();
            this.importNotice = data.not_loaded.length > 0
                ? 'Not loaded: the builder has no control for ' + data.not_loaded.join(', ') + '.'
                : '';
        },

        // Set the form state to `form`, the body getFormData posts
        applyForm(form) {
            for (const field of FORM_FIELDS) {
                this[field] = blankIfNull(form[field]);
            }
            for (const coordinate of CUSTOM_COORDINATES) {
                if (coordinate in form) this[coordinate] = form[coordinate];
            }
            for (const component of components) {
                this.dists[component.key] = DistributionEditor.load(
                    this.dists[component.key],
                    form[component.key][component.grammar_key],
                    component,
                    'fleet_distribution.' + component.key + '.' + component.grammar_key,
                );
            }
        },

        // The form the page posts, the one applyForm sets: each of FORM_FIELDS, the CUSTOM_COORDINATES for a custom
        // location, and each component's block
        getFormData() {
            const fields = this.location_preset === 'custom' ? [...FORM_FIELDS, ...CUSTOM_COORDINATES] : FORM_FIELDS;
            const data = Object.fromEntries(fields.map((field) => [field, this[field]]));
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
