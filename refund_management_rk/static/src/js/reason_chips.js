/**
 * Free-text "chips" input: type a reason, press Enter and it becomes a chip
 * with a remove (x) button, then type the next one. No dropdown involved.
 * Stored on a Text field, one reason per line.
 */
import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

export class ReasonChipsField extends Component {
    static template = "refund_management_rk.ReasonChipsField";
    static props = { ...standardFieldProps };

    setup() {
        this.state = useState({ draft: "" });
    }

    get reasons() {
        const value = this.props.record.data[this.props.name] || "";
        return value.split("\n").map((s) => s.trim()).filter(Boolean);
    }

    get placeholder() {
        return this.props.placeholder || _t("Type a reason and press Enter...");
    }

    _save(list) {
        return this.props.record.update({ [this.props.name]: list.join("\n") });
    }

    addDraft() {
        const value = this.state.draft.replace(/\s+/g, " ").trim();
        this.state.draft = "";
        if (value && !this.reasons.includes(value)) {
            return this._save([...this.reasons, value]);
        }
    }

    removeAt(index) {
        const list = [...this.reasons];
        list.splice(index, 1);
        return this._save(list);
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            // Never let Enter submit/close the surrounding dialog.
            ev.preventDefault();
            ev.stopPropagation();
            this.addDraft();
        } else if (ev.key === "Backspace" && !this.state.draft && this.reasons.length) {
            this.removeAt(this.reasons.length - 1);
        }
    }
}

registry.category("fields").add("reason_chips", {
    component: ReasonChipsField,
    supportedTypes: ["text"],
    displayName: _t("Reason chips"),
});
