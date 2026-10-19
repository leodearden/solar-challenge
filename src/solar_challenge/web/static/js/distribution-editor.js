document.addEventListener('alpine:init', () => {
    // The weight or count a new row of a distribution starts at
    const NEW_ROW_SHARE = 10;

    // The scope distribution_editor (templates/components/distribution-editor.html) opens for the distribution getDist
    // returns. dist calls getDist on every read, because a page that loads a scenario replaces its distributions
    // (pinned by test_fleet_import_yaml_shows_each_distribution_in_its_card).
    Alpine.data('distributionEditor', (getDist, newRowValue) => ({
        get dist() { return getDist(); },

        // Appends a row to `rows` holding newRowValue, and NEW_ROW_SHARE under `pairedKey`
        addRow(rows, pairedKey) {
            rows.push({ value: newRowValue, [pairedKey]: NEW_ROW_SHARE });
        },

        // Whether `rows` has a row to spare: a distribution keeps at least one
        canRemoveRow(rows) {
            return rows.length > 1;
        },

        // Removes row `idx` of `rows`, unless it is the last
        removeRow(rows, idx) {
            if (this.canRemoveRow(rows)) rows.splice(idx, 1);
        },
    }));
});
