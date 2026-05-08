/** @odoo-module **/

import { registry } from "@web/core/registry";
import { many2OneField, Many2OneField } from "@web/views/fields/many2one/many2one_field";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";

/**
 * Extends Many2XAutocomplete (where loadOptionsSource actually lives) to
 * append "(X.XX remaining)" to each subtask option in the dropdown.
 *
 * Hours are counted from both logging paths:
 *   - task_id  = subtask (logged directly on the subtask form)
 *   - subtask_id = subtask (logged via the Timesheets module)
 */
class SubtaskAutocomplete extends Many2XAutocomplete {
    async loadOptionsSource(request) {
        const options = await super.loadOptionsSource(request);

        const ids = options
            .map((o) => o.value)
            .filter((v) => typeof v === "number" && v > 0);

        if (!ids.length) return options;

        const [tasks, directLines, subtaskLines] = await Promise.all([
            this.orm.read("project.task", ids, ["name", "allocated_hours"]),
            this.orm.searchRead(
                "account.analytic.line",
                [["task_id", "in", ids]],
                ["task_id", "unit_amount"]
            ),
            this.orm.searchRead(
                "account.analytic.line",
                [["subtask_id", "in", ids]],
                ["subtask_id", "unit_amount"]
            ),
        ]);

        const usage = {};
        for (const l of directLines) {
            if (l.task_id) {
                const id = l.task_id[0];
                usage[id] = (usage[id] || 0) + l.unit_amount;
            }
        }
        for (const l of subtaskLines) {
            if (l.subtask_id) {
                const id = l.subtask_id[0];
                usage[id] = (usage[id] || 0) + l.unit_amount;
            }
        }

        const taskMap = Object.fromEntries(tasks.map((t) => [t.id, t]));

        return options.map((option) => {
            const task = taskMap[option.value];
            if (!task) return option;
            const remaining = Math.max(
                0,
                (task.allocated_hours || 0) - (usage[task.id] || 0)
            );
            return {
                ...option,
                label: `${task.name} (${remaining.toFixed(2)} remaining)`,
            };
        });
    }
}

/**
 * Many2OneField subclass that swaps in SubtaskAutocomplete so the dropdown
 * shows remaining hours without affecting the selected-value display.
 */
class SubtaskWithRemainingField extends Many2OneField {
    static components = {
        ...Many2OneField.components,
        Many2XAutocomplete: SubtaskAutocomplete,
    };
}

registry.category("fields").add("subtask_with_remaining", {
    ...many2OneField,
    component: SubtaskWithRemainingField,
    displayName: "Subtask with Remaining Hours",
});
