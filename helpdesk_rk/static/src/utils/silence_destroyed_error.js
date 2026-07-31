/** @odoo-module **/

/**
 * A component's own ORM calls are wired so that, if the component is
 * destroyed before the RPC resolves, the promise rejects with
 * "Component is destroyed" instead of touching a dead component - that is
 * intentional Odoo behavior. But when the call is kicked off from a bus
 * notification handler (not a user-triggered Owl event), nothing catches
 * that rejection and it surfaces as an "Uncaught (in promise)" crash.
 * Swallow exactly that expected rejection; let anything else propagate.
 */
export function ignoreDestroyedComponentError(promise) {
    return promise.catch((error) => {
        if (error?.message !== "Component is destroyed") {
            throw error;
        }
    });
}
