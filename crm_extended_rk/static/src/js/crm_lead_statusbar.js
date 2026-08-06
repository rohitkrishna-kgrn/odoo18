/** @odoo-module **/

/* CRM lead/opportunity form: the core StatusBarField widget only
 * recalculates which stages fit inline vs. fold into "..." on a window
 * "resize" event. It never re-measures when a sibling header element
 * (e.g. the Send Discovery Form button) changes the row's height for
 * other reasons, so its folding goes stale and the browser falls back
 * to raw, ungraceful CSS wrapping. Watching the statusbar's own height
 * and re-firing a "resize" event nudges the widget's existing listener
 * to recompute with current geometry, without patching Odoo core.
 *
 * Defensive by design: every step is guarded so this optional UX
 * enhancement can never throw an uncaught error that would break the
 * rest of the asset bundle / page.
 */

try {
    const watched = new WeakSet();

    const watchStatusbar = (el) => {
        if (watched.has(el)) {
            return;
        }
        watched.add(el);
        try {
            let lastHeight = el.getBoundingClientRect().height;
            const resizeObserver = new ResizeObserver(() => {
                try {
                    const { height } = el.getBoundingClientRect();
                    if (height !== lastHeight) {
                        lastHeight = height;
                        window.dispatchEvent(new Event("resize"));
                    }
                } catch {
                    // Never let this break the page.
                }
            });
            resizeObserver.observe(el);
        } catch {
            // Never let this break the page.
        }
    };

    const startWatching = () => {
        try {
            const mutationObserver = new MutationObserver(() => {
                try {
                    document
                        .querySelectorAll(".o_lead_opportunity_form .o_form_statusbar")
                        .forEach(watchStatusbar);
                } catch {
                    // Never let this break the page.
                }
            });
            mutationObserver.observe(document.body, { childList: true, subtree: true });
        } catch {
            // Never let this break the page.
        }
    };

    if (document.body) {
        startWatching();
    } else {
        document.addEventListener("DOMContentLoaded", startWatching, { once: true });
    }
} catch {
    // Never let this optional UX enhancement break page load.
}
