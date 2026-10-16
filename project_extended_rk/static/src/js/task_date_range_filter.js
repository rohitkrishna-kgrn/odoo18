/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { formatDate, serializeDateTime } from "@web/core/l10n/dates";
import { SearchBarMenu } from "@web/search/search_bar_menu/search_bar_menu";

const { DateTime } = luxon;

/**
 * "Date Range" block in the Filters dropdown of the task search: pick a From / To
 * date on the task dates (deadline, completed or created), and the tasks are narrowed to that window.
 *
 * It is created with SearchModel.createNewFilters, i.e. as its own filter group,
 * so it is AND-ed with every other active filter (project, stage, assignee,
 * Hide On Hold, ...). Applying again replaces the previous range.
 */
// A task belongs to the window if ANY of these dates falls inside it, so tasks
// are found whether they were created, completed or due in the period.
const RANGE_FIELDS = ["date_deadline", "completed_date", "create_date"];
const RANGE_LABEL = _t("Date");

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
        const label = RANGE_LABEL;
        // the boundaries are the user's local midnights; the server compares in UTC
        const lower = from ? DateTime.fromISO(from).startOf("day") : false;
        const upper = to ? DateTime.fromISO(to).plus({ days: 1 }).startOf("day") : false;
        const clause = (field) => {
            const parts = [];
            if (lower) {
                parts.push([field, ">=", serializeDateTime(lower)]);
            }
            if (upper) {
                parts.push([field, "<", serializeDateTime(upper)]);
            }
            return parts;
        };
        // (f1 range) OR (f2 range) OR (f3 range), each range being an AND of its bounds
        const domain = [];
        RANGE_FIELDS.forEach((field, i) => {
            if (i < RANGE_FIELDS.length - 1) {
                domain.push("|");
            }
            const parts = clause(field);
            if (parts.length === 2) {
                domain.push("&");
            }
            domain.push(...parts);
        });
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
