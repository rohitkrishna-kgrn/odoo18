/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";
import { onWillStart } from "@odoo/owl";
import { ListController } from "@web/views/list/list_controller";

/**
 * Excel export on every list inside the CRM app, for Sales Administrators.
 *
 * Tick the row checkboxes, open Actions > Export, choose the columns and
 * download the .xlsx - Odoo's own export dialog, which is already limited to
 * the ticked rows (or the whole filtered set via "Select all").
 *
 * Core only offers that action to the global "Access to export feature"
 * group, which would unlock export in every app. Here it is unlocked only
 * while the CRM app is the active one and only for users whose Sales access
 * is Administrator (sales_team.group_sale_manager); every other app and every
 * other user is untouched.
 */
const CRM_APP_XMLID = "crm.crm_menu_root";

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        onWillStart(async () => {
            if (this.isExportEnable) {
                return;
            }
            const app = this.env.services.menu?.getCurrentApp();
            if (app && app.xmlid === CRM_APP_XMLID) {
                this.isExportEnable = await user.hasGroup("sales_team.group_sale_manager");
            }
        });
    },
});
