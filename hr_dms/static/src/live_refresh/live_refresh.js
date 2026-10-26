/** @odoo-module **/
import { onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { debounce } from "@web/core/utils/timing";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { ListController } from "@web/views/list/list_controller";

/**
 * Live refresh for Employee Documents: the server sends "hr_dms/changed" ({model: [ids]}) after
 * every committed change (models/live_refresh.py), and the open list, kanban or form reloads.
 * Nothing reloads under someone's hands: a form with unsaved changes, a list row being edited
 * or a list with selected rows is left alone.
 */
const LIVE_MODELS = ["hr.dms.document", "hr.dms.personal.details", "hr.dms.category"];

function useHrDmsLiveRefresh(resModel, reload) {
    if (!LIVE_MODELS.includes(resModel)) {
        return;
    }
    const bus = useService("bus_service");
    let pendingIds = new Set();
    const flush = debounce(() => {
        const ids = [...pendingIds];
        pendingIds = new Set();
        reload(ids);
    }, 300);
    const onChanged = (payload) => {
        const ids = payload[resModel];
        if (ids) {
            ids.forEach((id) => pendingIds.add(id));
            flush();
        }
    };
    onMounted(() => {
        bus.subscribe("hr_dms/changed", onChanged);
        bus.start();
    });
    onWillUnmount(() => {
        flush.cancel();
        bus.unsubscribe("hr_dms/changed", onChanged);
    });
}

async function reloadList(model) {
    const root = model.root;
    if (root.editedRecord || root.selection?.length) {
        return;
    }
    await model.load();
}

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        useHrDmsLiveRefresh(this.props.resModel, async (ids) => {
            const root = this.model.root;
            if (!root.resId || !ids.includes(root.resId) || (await root.isDirty())) {
                return;
            }
            await root.load();
        });
    },
});

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        useHrDmsLiveRefresh(this.props.resModel, () => reloadList(this.model));
    },
});

patch(KanbanController.prototype, {
    setup() {
        super.setup(...arguments);
        useHrDmsLiveRefresh(this.props.resModel, () => reloadList(this.model));
    },
});
