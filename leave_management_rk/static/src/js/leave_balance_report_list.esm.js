/** @odoo-module **/
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";

// Same list, but group headers show only the name (no "(count)").
export class LeaveBalanceReportListRenderer extends ListRenderer {
    static groupRowTemplate = "leave_management_rk.ListRenderer.GroupRow";
}

registry.category("views").add("leave_balance_report_list", {
    ...listView,
    Renderer: LeaveBalanceReportListRenderer,
});
