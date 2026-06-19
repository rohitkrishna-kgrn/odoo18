/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import {
    Many2ManyBinaryField,
    many2ManyBinaryField,
} from "@web/views/fields/many2many_binary/many2many_binary_field";

// ── Popup viewer dialog ────────────────────────────────────────────────────────
export class CvFileViewerDialog extends Component {
    static template = "recruitment_gk.CvFileViewerDialog";
    static components = { Dialog };
    static props = {
        close:    { type: Function },
        name:     { type: String },
        url:      { type: String },
        mimetype: { type: String, optional: true },
    };

    get isViewable() {
        const m = this.props.mimetype || "";
        return m.startsWith("image/") || m === "application/pdf";
    }
}

// ── Custom field widget ────────────────────────────────────────────────────────
export class CvAttachmentDownload extends Many2ManyBinaryField {
    static template = "recruitment_gk.CvAttachmentDownload";

    setup() {
        super.setup();
        this.dialogService = useService("dialog");
    }

    openFile(file) {
        this.dialogService.add(CvFileViewerDialog, {
            name:     file.name,
            url:      "/web/content/" + file.id,
            mimetype: file.mimetype || "",
        });
    }
}

registry.category("fields").add("cv_attachment_download", {
    ...many2ManyBinaryField,
    component: CvAttachmentDownload,
    displayName: "CV Attachment Download",
});
