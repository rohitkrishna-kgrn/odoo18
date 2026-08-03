/** @odoo-module **/

import { CheckInOut } from "@hr_attendance/components/check_in_out/check_in_out";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(CheckInOut.prototype, {
    setup() {
        super.setup();
        this.dialog = useService("dialog");
    },

    async signInOut() {
        const doSignInOut = super.signInOut.bind(this);
        this.dialog.add(ConfirmationDialog, {
            title: this.props.checkedIn ? _t("Confirm Check Out") : _t("Confirm Check In"),
            body: this.props.checkedIn
                ? _t("Are you sure you want to check out?")
                : _t("Are you sure you want to check in?"),
            confirm: () => doSignInOut(),
            cancel: () => {},
        });
    },
});
