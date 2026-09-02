/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { useEffect } from "@odoo/owl";

const DELAY_LOG_MODELS = ["project.project", "project.task"];

/**
 * Pop the delay-reason wizard when a project or task whose deadline has passed
 * is opened with no delay log on file.
 *
 * Patched onto the base FormController rather than registered as a js_class:
 * both forms already carry one of their own (`project_task_form`,
 * `form_description_expander`), and their controllers extend this prototype, so
 * the patch reaches them without displacing that behaviour.
 *
 * The stored `delay_log_missing` flag is used only to decide whether to ask the
 * server at all — every other form open costs no extra RPC. The server method
 * re-checks the condition against today's date and returns false when nothing
 * is owed.
 */
patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        useEffect(
            () => {
                this._promptDelayLogWizard();
            },
            () => [this.model.root && this.model.root.resId]
        );
    },

    async _promptDelayLogWizard() {
        if (!DELAY_LOG_MODELS.includes(this.props.resModel) || this.env.inDialog) {
            return;
        }
        const record = this.model.root;
        if (!record || record.isNew || !record.resId || !record.data.delay_log_missing) {
            return;
        }
        const action = await this.orm.call(
            this.props.resModel,
            "action_open_delay_log_wizard",
            [[record.resId]]
        );
        if (!action) {
            return;
        }
        this.actionService.doAction(action, {
            // Reload so the banner, the badge and the flag reflect the new log.
            onClose: () => this.model.root.load(),
        });
    },
});
