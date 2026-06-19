/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { FilterMenu } from "@web/search/filter_menu/filter_menu";

const MIS_MODELS = ["mis.project.wise", "mis.outstanding.line"];

class MisDateRangeFilter extends Component {
    static template = "mis_report_kgrn.MisDateRangeFilter";
    static props = {};

    setup() {
        this.state = useState({ dateFrom: "", dateTo: "" });
    }

    onFromChange(ev) {
        this.state.dateFrom = ev.target.value;
    }

    onToChange(ev) {
        this.state.dateTo = ev.target.value;
    }

    onApply() {
        const { dateFrom, dateTo } = this.state;
        const domain = [];
        if (dateFrom) domain.push(["project_create_date", ">=", dateFrom]);
        if (dateTo)   domain.push(["project_create_date", "<=", dateTo]);
        if (!domain.length) return;

        const parts = [];
        if (dateFrom) parts.push(`from ${dateFrom}`);
        if (dateTo)   parts.push(`to ${dateTo}`);

        this.env.searchModel.dispatch("createNewFilters", [
            { description: `Created ${parts.join(" ")}`, domain },
        ]);
    }

    onClear() {
        this.state.dateFrom = "";
        this.state.dateTo = "";
    }
}

// Register MisDateRangeFilter as a sub-component of FilterMenu
FilterMenu.components = {
    ...(FilterMenu.components || {}),
    MisDateRangeFilter,
};

// Expose isMisModel on FilterMenu instances so the template can use it
patch(FilterMenu.prototype, {
    get isMisModel() {
        return MIS_MODELS.includes(this.env.searchModel?.resModel);
    },
});
