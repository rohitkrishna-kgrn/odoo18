/**
 * Keep the Chatter pinned to the right of the Upselling form.
 *
 * Odoo only puts the chatter aside on XXL screens (>= 1534px); below that it
 * drops under the sheet and the user has to scroll to reach it. For the
 * Upselling form we lower that threshold to XL (>= 1200px). Narrower screens
 * keep the standard bottom chatter so the layout never breaks.
 */
import { patch } from "@web/core/utils/patch";
import { SIZES } from "@web/core/ui/ui_service";
import { FormRenderer } from "@web/views/form/form_renderer";

patch(FormRenderer.prototype, {
    mailLayout(hasAttachmentContainer) {
        const layout = super.mailLayout(...arguments);
        if (
            layout === "BOTTOM_CHATTER" &&
            this.props.record?.resModel === "upselling" &&
            this.uiService.size >= SIZES.XL
        ) {
            return "SIDE_CHATTER";
        }
        return layout;
    },
});
