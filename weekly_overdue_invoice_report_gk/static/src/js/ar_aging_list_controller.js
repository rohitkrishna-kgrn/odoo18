/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

/**
 * Adds "Exclude Invoice" / "Include Invoice" to the AR Aging Dashboard's
 * bulk Actions menu, right after Delete. Only one of the two is ever shown
 * for a given selection — Exclude when at least one selected invoice isn't
 * excluded yet, Include when every selected invoice already is — so picking
 * an already-excluded invoice replaces Exclude with Include rather than
 * showing both. Scoped to this one list view only (js_class
 * "ar_aging_excluded_list", set on account_extended_rk's AR Aging list via
 * an inherited view) — the ordinary invoice list elsewhere is untouched.
 */
class ArAgingExcludedListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
    }

    get _hasIncludedSelected() {
        const selection = this.model.root.selection;
        return selection.length > 0 && !selection.every((r) => r.data.overdue_report_excluded);
    }

    get _allSelectedExcluded() {
        const selection = this.model.root.selection;
        return selection.length > 0 && selection.every((r) => r.data.overdue_report_excluded);
    }

    async _setExcluded(value) {
        const resIds = await this.getSelectedResIds();
        if (!resIds.length) {
            return;
        }
        await this.orm.write("account.move", resIds, { overdue_report_excluded: value });
        this.model.root.selection.forEach((record) => record.toggleSelection(false));
        await this.model.load();
    }

    getStaticActionMenuItems() {
        return {
            ...super.getStaticActionMenuItems(),
            exclude_invoice: {
                isAvailable: () => this._hasIncludedSelected,
                sequence: 45,
                icon: "fa fa-eye-slash",
                description: _t("Exclude Invoice"),
                callback: () => this._setExcluded(true),
            },
            include_invoice: {
                isAvailable: () => this._allSelectedExcluded,
                sequence: 45,
                icon: "fa fa-eye",
                description: _t("Include Invoice"),
                callback: () => this._setExcluded(false),
            },
        };
    }
}

registry.category("views").add("ar_aging_excluded_list", {
    ...listView,
    Controller: ArAgingExcludedListController,
});
