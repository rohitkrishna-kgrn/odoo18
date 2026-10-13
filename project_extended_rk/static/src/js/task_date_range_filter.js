/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { formatDate, serializeDateTime } from "@web/core/l10n/dates";
import { SearchBarMenu } from "@web/search/search_bar_menu/search_bar_menu";

const { DateTime } = luxon;

/**
 * "Date Range" block in the Filters dropdown of the task search: pick a From / To
 * date on the Deadline, and the tasks are narrowed to that window.
 *
 * It is created with SearchModel.createNewFilters, i.e. as its own filter group,
 * so it is AND-ed with every other active filter (project, stage, assignee,
 * Hide On Hold, ...). Applying again replaces the previous range.
 */
const RANGE_FIELD = { name: "date_deadline", label: _t("Deadline") };

patch(SearchBarMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.dateRange = useState({
            from: "",
            to: "",
        });
    },

    get isTaskDateRangeAvailable() {
        return this.env.searchModel.resModel === "project.task";
    },

    _activeDateRangeItems() {
        return this.env.searchModel.getSearchItems((item) => item.isTaskDateRange);
    },

    get isDateRangeActive() {
        return this._activeDateRangeItems().some((item) => item.isActive);
    },

    applyDateRange() {
        const field = RANGE_FIELD.name;
        const { from, to } = this.dateRange;
        if (!from && !to) {
            return;
        }
        const searchModel = this.env.searchModel;
        // one range at a time: drop the previous one before adding the new one
        for (const item of this._activeDateRangeItems()) {
            if (item.isActive) {
                searchModel.deactivateGroup(item.groupId);
            }
        }
        const label = RANGE_FIELD.label;
        // the boundaries are the user's local midnights; the server compares in UTC
        const lower = from ? DateTime.fromISO(from).startOf("day") : false;
        const upper = to ? DateTime.fromISO(to).plus({ days: 1 }).startOf("day") : false;
        const domain = [];
        if (lower) {
            domain.push([field, ">=", serializeDateTime(lower)]);
        }
        if (upper) {
            domain.push([field, "<", serializeDateTime(upper)]);
        }
        let description;
        if (from && to) {
            description = `${label}: ${formatDate(DateTime.fromISO(from))} → ${formatDate(DateTime.fromISO(to))}`;
        } else if (from) {
            description = `${label} ≥ ${formatDate(DateTime.fromISO(from))}`;
        } else {
            description = `${label} ≤ ${formatDate(DateTime.fromISO(to))}`;
        }
        searchModel.createNewFilters([{ description, domain: JSON.stringify(domain), isTaskDateRange: true }]);
    },

    clearDateRange() {
        for (const item of this._activeDateRangeItems()) {
            if (item.isActive) {
                this.env.searchModel.deactivateGroup(item.groupId);
            }
        }
        this.dateRange.from = "";
        this.dateRange.to = "";
    },
});
