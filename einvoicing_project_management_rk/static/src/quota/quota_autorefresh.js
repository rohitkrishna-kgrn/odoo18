/** @odoo-module **/
import { onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { formView } from "@web/views/form/form_view";
import { FormController } from "@web/views/form/form_controller";

/**
 * Auto-refresh of the invoice quota when a Phase 1 / Unidentified page opens.
 *
 * The page renders straight away from the stored figures. Once mounted, it
 * asks the server to re-check quotas older than a few minutes
 * (refresh_stale_quotas), and reloads only if something was re-checked. This
 * is a separate RPC, not part of the page load, so a slow or unreachable API
 * never holds the page up.
 */
async function refreshQuotas(orm, resModel, ids) {
    try {
        return await orm.call(resModel, "refresh_stale_quotas", [], { ids: ids || false });
    } catch (error) {
        console.warn("Invoice quota refresh failed", error);
        return 0;
    }
}

export class EpmQuotaListController extends ListController {
    setup() {
        super.setup();
        this.epmOrm = useService("orm");
        onMounted(async () => {
            const refreshed = await refreshQuotas(this.epmOrm, this.props.resModel);
            // never reload under a row that is being edited in place
            if (refreshed && !this.model.root.editedRecord) {
                await this.model.load();
            }
        });
    }
}

export class EpmQuotaFormController extends FormController {
    setup() {
        super.setup();
        onMounted(async () => {
            const record = this.model.root;
            if (!record.resId) {
                return; // a new, unsaved record has nothing to check yet
            }
            const refreshed = await refreshQuotas(this.orm, this.props.resModel, [record.resId]);
            if (refreshed && this.model.root.resId === record.resId && !(await this.model.root.isDirty())) {
                await this.model.load();
            }
        });
    }
}

registry.category("views").add("epm_quota_list", { ...listView, Controller: EpmQuotaListController });
registry.category("views").add("epm_quota_form", { ...formView, Controller: EpmQuotaFormController });
