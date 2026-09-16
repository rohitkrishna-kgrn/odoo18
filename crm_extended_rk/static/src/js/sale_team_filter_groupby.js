/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { SearchModel } from "@web/search/search_model";

/**
 * Sales Team quick filters on the Services lists (Proposal and Service
 * Engagement) are meant to answer "show me this team's orders, broken down per
 * salesperson" - one click, with a foldable group per salesperson.
 *
 * That cannot be expressed in the search view itself. Odoo's search arch
 * parser (web/static/src/search/search_arch_parser.js, visitFilter) turns any
 * <filter> whose context resolves a group_by field into a pure "groupBy" item
 * and then never reads its domain, so one <filter> can carry a domain or a
 * grouping, never both. The team entries therefore stay plain domain filters -
 * see crm_extended_rk/models/sale_order.py, which injects one per crm.team -
 * and the grouping is added here instead.
 *
 * Turning a team scope on switches the Salesperson grouping on with it;
 * dropping the last one switches it back off, but only when it was us that
 * switched it on. A grouping the user picked themselves is left alone.
 */

// Set by SaleOrder._SALES_TEAM_FILTER_PREFIX in models/sale_order.py, and by
// the static "My Sales Team" entry in views/sale_order_views.xml. No other
// model has filters under this prefix, so the patch is inert everywhere else.
const TEAM_SCOPE_PREFIX = "sales_team_scope_";
const GROUP_BY_FIELD = "user_id";

patch(SearchModel.prototype, {
    toggleSearchItem(searchItemId) {
        const searchItem = this.searchItems[searchItemId];
        if (!this._isSalesTeamScope(searchItem)) {
            // The user reaching for the Salesperson grouping by hand takes it
            // back off us, so dropping the team scope later leaves it standing.
            if (searchItem && this._isSalespersonGroupBy(searchItem)) {
                this._salesTeamGroupByIsOurs = false;
            }
            return super.toggleSearchItem(searchItemId);
        }
        // Unticking one team can still leave another ticked.
        const isActive = this.query.some((q) => q.searchItemId === searchItemId);
        this._syncSalesTeamGroupBy(isActive ? this._hasSalesTeamScope(searchItemId) : true);
        return super.toggleSearchItem(searchItemId);
    },

    /** Clearing the Sales Team facet with its "x" never reaches toggleSearchItem. */
    deactivateGroup(groupId) {
        const inGroup = (q) => this.searchItems[q.searchItemId]?.groupId === groupId;
        const dropsScope = this.query.some(
            (q) => inGroup(q) && this._isSalesTeamScope(this.searchItems[q.searchItemId])
        );
        if (dropsScope) {
            this._syncSalesTeamGroupBy(
                this.query.some(
                    (q) => !inGroup(q) && this._isSalesTeamScope(this.searchItems[q.searchItemId])
                )
            );
        }
        return super.deactivateGroup(groupId);
    },

    clearQuery() {
        this._salesTeamGroupByIsOurs = false;
        return super.clearQuery();
    },

    /**
     * Add or remove the Salesperson grouping to match `willHaveScope`, by
     * mutating this.query in place. Deliberately not a toggleSearchItem call:
     * that ends in _notify(), and going through it twice would reload the list
     * twice for a single click.
     *
     * @param {boolean} willHaveScope whether a team scope is active once the
     *      caller's own change has been applied
     */
    _syncSalesTeamGroupBy(willHaveScope) {
        const groupBy = Object.values(this.searchItems).find((item) =>
            this._isSalespersonGroupBy(item)
        );
        if (!groupBy) {
            return;
        }
        const index = this.query.findIndex((q) => q.searchItemId === groupBy.id);
        if (willHaveScope && index < 0) {
            this.query.push({ searchItemId: groupBy.id });
            this._salesTeamGroupByIsOurs = true;
        } else if (!willHaveScope && index >= 0 && this._salesTeamGroupByIsOurs) {
            this.query.splice(index, 1);
            this._salesTeamGroupByIsOurs = false;
        }
    },

    /** @param {number} [exceptId] id to ignore, e.g. the one being unticked */
    _hasSalesTeamScope(exceptId) {
        return this.query.some(
            (q) =>
                q.searchItemId !== exceptId &&
                this._isSalesTeamScope(this.searchItems[q.searchItemId])
        );
    },

    _isSalesTeamScope(searchItem) {
        return Boolean(
            searchItem &&
                searchItem.type === "filter" &&
                String(searchItem.name || "").startsWith(TEAM_SCOPE_PREFIX)
        );
    },

    _isSalespersonGroupBy(searchItem) {
        return searchItem.type === "groupBy" && searchItem.fieldName === GROUP_BY_FIELD;
    },
});
