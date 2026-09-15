/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Fires each url in action.params.urls as its own act_url download, one
 * after another. Used by the Credit Hold Report wizards' Download button
 * when both PDF and Excel are selected -- the user wants two separate
 * files, not a zip, so each is downloaded on its own via the same
 * `target: 'download'` idiom core uses (account.move's `download_pdf`
 * action, e.g.), which opens/downloads without navigating the SPA away
 * the way `target: 'self'` would.
 */
async function doCreditHoldMultiDownload(env, action) {
    for (const url of action.params.urls) {
        await env.services.action.doAction({
            type: "ir.actions.act_url",
            url,
            target: "download",
        });
    }
}

registry.category("actions").add(
    "account_extended_rk.credit_hold_multi_download", doCreditHoldMultiDownload);
