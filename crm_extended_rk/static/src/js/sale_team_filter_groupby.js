/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { SearchModel } from "@web/search/search_model";

/**
 * Sales Team quick filters on the Services lists (Proposal and Service
 * Engagement) answer "show me this team's orders, broken down per salesperson"
 * - one click, one facet, a foldable group per salesperson.
 *
 * The search view cannot express that on its own. Odoo's search arch parser
 * (web/static/src/search/search_arch_parser.js, visitFilter) turns any <filter>
 * whose context resolves a group_by field into a pure "groupBy" item and then
 * never reads its domain, so one <filter> can carry a domain or a grouping,
 * never both. The team entries therefore stay plain domain filters - see
 * crm_extended_rk/models/sale_order.py, which injects one per crm.team - and
 * the grouping is attached to them here.
 *
 * It is attached at the point where SearchModel asks an active item what it
 * contributes to the group by, rather than by switching the separate
 * "Salesperson" group by item on alongside it. Both group the list the same
 * way, but switching that item on puts a second facet in the search bar next
 * to the team's own; contributing the group by directly keeps it to one facet
 * reading just "Gokul".
 */

// Set by SaleOrder._SALES_TEAM_FILTER_PREFIX in models/sale_order.py, and by
// the static "My Sales Team" entry in views/sale_order_views.xml. No other
// model has filters under this prefix, so the patch is inert everywhere else.
const TEAM_SCOPE_PREFIX = "sales_team_scope_";
const GROUP_BY_FIELD = "user_id";

patch(SearchModel.prototype, {
    /**
     * Only "groupBy", "dateGroupBy" and "favorite" items contribute a group by
     * in the base implementation; a "filter" gets null. Team scopes contribute
     * the Salesperson grouping.
     */
    _getSearchItemGroupBys(activeItem) {
        if (this._isSalesTeamScope(this.searchItems[activeItem.searchItemId])) {
            return [GROUP_BY_FIELD];
        }
        return super._getSearchItemGroupBys(activeItem);
    },

    _getGroupBy() {
        // Two teams ticked at once, or a team alongside a Salesperson grouping
        // the user picked from the Group By menu, would otherwise ask for
        // user_id twice.
        return [...new Set(super._getGroupBy())];
    },

    _isSalesTeamScope(searchItem) {
        return Boolean(
            searchItem &&
                searchItem.type === "filter" &&
                String(searchItem.name || "").startsWith(TEAM_SCOPE_PREFIX)
        );
    },
});
