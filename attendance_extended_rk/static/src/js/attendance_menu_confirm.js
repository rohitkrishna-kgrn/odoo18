/** @odoo-module **/

import { ActivityMenu } from "@hr_attendance/components/attendance_menu/attendance_menu";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(ActivityMenu.prototype, {
    setup() {
        super.setup();
        this.dialog = useService("dialog");
    },

    async signInOut() {
        this.dropdown.close();

        const doSignInOut = super.signInOut.bind(this);
        this.dialog.add(ConfirmationDialog, {
            title: this.state.checkedIn ? _t("Confirm Check Out") : _t("Confirm Check In"),
            body: this.state.checkedIn
                ? _t("Are you sure you want to check out?")
                : _t("Are you sure you want to check in?"),
            confirm: () => doSignInOut(),
            cancel: () => {},
        });
    },
});
