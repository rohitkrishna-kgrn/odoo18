/** @odoo-module */
/**
 * Force the sub-tasks one2many field (used inside the task form's Sub-tasks
 * tab) to render in Kanban view by default instead of List view.
 *
 * Odoo's form_controller hard-codes "list" as the desktop default whenever the
 * field's `mode` attribute contains a comma, so we patch extractProps here to
 * override the resolved viewMode to "kanban" when the kanban sub-view is
 * available.
 */
import { registry } from "@web/core/registry";
import {
    SubtaskOne2ManyField,
    subtaskOne2ManyField,
} from "@project/components/subtask_one2many_field/subtask_one2many_field";

const fieldsRegistry = registry.category("fields");
const original = subtaskOne2ManyField.extractProps;

fieldsRegistry.add(
    "subtasks_one2many",
    {
        ...subtaskOne2ManyField,
        component: SubtaskOne2ManyField,
        extractProps(fieldInfo, dynamicInfo) {
            const props = original(fieldInfo, dynamicInfo);
            // Switch to kanban when the kanban sub-view has been fetched.
            // The view is fetched by form_controller only when fieldInfo.viewMode
            // is already "kanban" (set via mode="kanban" in the arch xpath),
            // so this guard prevents a broken render when kanban is unavailable.
            if (props.views && props.views.kanban) {
                props.viewMode = "kanban";
            }
            return props;
        },
    },
    { force: true }
);
