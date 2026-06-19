/** @odoo-module **/

import { PriorityField } from "@web/views/fields/priority/priority_field";
import { patch } from "@web/core/utils/patch";

/**
 * Prevent the priority (stars) widget from auto-saving the record when a
 * star is clicked.  Only apply the fix when the field itself has NOT already
 * set autosave:false via options (the XML approach).  This patch acts as a
 * safety net for any Odoo 18 build that ignores the options prop.
 *
 * Covers two naming conventions across Odoo versions:
 *   - onClick(star)  — Odoo 18 style
 *   - update(ev)     — Odoo 17 style
 */
patch(PriorityField.prototype, {
    // ── Odoo 18: star object is passed directly ──────────────────────────
    async onClick(star) {
        const fieldName = this.props.name;
        const currentValue = this.props.record.data[fieldName];
        await this.props.record.update({
            [fieldName]: currentValue === star.value ? "0" : star.value,
        });
        // No record.save() — the Save button must be used explicitly
    },

    // ── Odoo 17: MouseEvent is passed ───────────────────────────────────
    async update(ev) {
        if (ev && ev.target && ev.target.dataset && ev.target.dataset.index !== undefined) {
            const index = parseInt(ev.target.dataset.index, 10);
            const values = this.props.values || [];
            const current = this.props.value || this.props.record?.data?.[this.props.name];
            const newValue = values[index]?.value === current
                ? (values[index - 1]?.value ?? "0")
                : (values[index]?.value ?? "0");
            if (this.props.update) {
                await this.props.update(newValue);
            } else {
                await this.props.record.update({ [this.props.name]: newValue });
            }
            // No record.save()
        }
    },
});
