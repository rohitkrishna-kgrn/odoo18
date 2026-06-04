/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * MIS Project Dashboard
 * 4-level expandable tree: Company → Department → Project Manager → Project Cards
 */
export class MisProjectDashboard extends Component {
    static template = "mis_report_kgrn.MisProjectDashboard";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            data: [],
            loading: true,
            expanded: {},
            totalProjects: 0,
        });
        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "mis.project.wise",
                "get_dashboard_data",
                []
            );
            this.state.data = data;
            this.state.totalProjects = data.reduce(
                (sum, comp) => sum + (comp.projects_count || 0), 0
            );
        } catch (e) {
            console.error("MIS Dashboard load error:", e);
        } finally {
            this.state.loading = false;
        }
    }

    toggleNode(key) {
        this.state.expanded[key] = !this.state.expanded[key];
    }

    isExpanded(key) {
        return !!this.state.expanded[key];
    }

    fmt(value) {
        return (value || 0).toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }
}

registry.category("actions").add("mis_project_dashboard_action", MisProjectDashboard);
