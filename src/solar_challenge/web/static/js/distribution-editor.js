// The spec a fleet component's distribution editor (templates/components/distribution-editor.html) posts and loads.
// An editor's dist is { type, fixed, specs }, as #page-limits writes each component's start: type names the editor
// type shown, '' for Fixed Value, and specs holds each editor type's spec as the grammar writes it, without its type.
// A component is one of #page-limits' components, whose editor_types and scalar_form name every type, so no type is
// named here. The page scripts call these outside any editor's scope, so they are one global, not scope methods.
const DistributionEditor = (() => {
    // A blank input, '' (an empty number input holds it), or an absent value, as null, which the grammar reads as absent
    function nullIfBlank(value) {
        return value === '' || value === undefined ? null : value;
    }

    // A null or absent value as an input holds it: '' (a blank input)
    function blankIfNull(value) {
        return value === null || value === undefined ? '' : value;
    }

    // `value` read through `read`: each of its entries, for a list
    function eachEntry(value, read) {
        return Array.isArray(value) ? value.map(read) : read(value);
    }

    function isMapping(value) {
        return value !== null && typeof value === 'object' && !Array.isArray(value);
    }

    // An editor type's held spec with nothing given: each parameter blank and each row list empty
    function blankSpec(editorType) {
        const spec = Object.fromEntries(editorType.parameters.map((parameter) => [parameter.key, '']));
        for (const key of editorType.rows ? editorType.rows.keys : []) {
            spec[key] = [];
        }
        return spec;
    }

    // The spec `dist` posts: Fixed Value's number, or the shown type's spec, each blank input as null
    function wire(dist) {
        if (!dist.type) {
            return nullIfBlank(dist.fixed);
        }
        const spec = { type: dist.type };
        for (const [key, value] of Object.entries(dist.specs[dist.type])) {
            spec[key] = eachEntry(value, nullIfBlank);
        }
        return spec;
    }

    // A new dist that shows `spec`, `component`'s spec read at `path`, over `dist`: a null or a number, or the scalar
    // form's mapping, at Fixed Value; a spec of one of its editor types as that type, each key it gives laid over a
    // blank spec and each null blank. Throws an Error naming `path` and the editor types for any other spec.
    function load(dist, spec, component, path) {
        if (spec === null || spec === undefined || typeof spec === 'number') {
            return { ...dist, type: '', fixed: blankIfNull(spec) };
        }
        const scalarForm = component.scalar_form;
        if (isMapping(spec) && spec.type === scalarForm.name) {
            return { ...dist, type: '', fixed: blankIfNull(spec[scalarForm.key]) };
        }
        const editorType = isMapping(spec) && component.editor_types.find((each) => each.name === spec.type);
        if (!editorType) {
            const offered = component.editor_types.map((each) => each.name).join(', ');
            const written = isMapping(spec) ? spec.type : spec;
            throw new Error(path + ' must be a fixed value or one of the distributions the ' + component.subject
                + ' editor holds (' + offered + '), got ' + JSON.stringify(written));
        }
        const held = blankSpec(editorType);
        for (const [key, value] of Object.entries(spec)) {
            if (key !== 'type') held[key] = eachEntry(value, blankIfNull);
        }
        return { ...dist, type: editorType.name, specs: { ...dist.specs, [editorType.name]: held } };
    }

    return { wire, load };
})();

document.addEventListener('alpine:init', () => {
    // The weight or count a new row of a distribution starts at
    const NEW_ROW_SHARE = 10;

    // The scope distribution_editor opens for the dist getDist returns. dist calls getDist on every read, because a
    // page that loads a scenario replaces its dists (pinned by
    // tests/e2e/test_fleet_interactions.py::test_fleet_import_yaml_shows_each_distribution_in_its_card).
    // A row is one entry of each of a spec's two parallel lists, keyed valuesKey and pairedKey.
    Alpine.data('distributionEditor', (getDist, newRowValue) => ({
        get dist() { return getDist(); },

        // Appends a row to `spec` holding newRowValue, and NEW_ROW_SHARE in its paired list
        addRow(spec, valuesKey, pairedKey) {
            spec[valuesKey].push(newRowValue);
            spec[pairedKey].push(NEW_ROW_SHARE);
        },

        // Whether a spec whose values are `values` has a row to spare: a distribution keeps at least one
        canRemoveRow(values) {
            return values.length > 1;
        },

        // Removes row `idx` of `spec`, unless it is the last
        removeRow(spec, valuesKey, pairedKey, idx) {
            if (!this.canRemoveRow(spec[valuesKey])) return;
            spec[valuesKey].splice(idx, 1);
            spec[pairedKey].splice(idx, 1);
        },
    }));
});
