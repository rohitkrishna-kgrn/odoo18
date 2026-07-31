/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { url } from "@web/core/utils/urls";
import { Component, useState, onWillUpdateProps } from "@odoo/owl";

const HIDDEN_PDF_TOOLBAR_SELECTORS = [
    "#sidebarToggleButton",
    "#editorModeButtons",
    "#editorModeSeparator",
    "#printButton",
    "#downloadButton",
    "#secondaryToolbarToggle",
];

export class AttachmentPreview extends Component {
    static template = "helpdesk_rk.AttachmentPreview";
    static props = { ...standardWidgetProps };

    setup() {
        this.state = useState({ expanded: false });

        onWillUpdateProps((nextProps) => {
            if (nextProps.record.resId !== this.props.record.resId) {
                this.state.expanded = false;
            }
        });
    }

    get resId() {
        return this.props.record.resId;
    }

    get isImage() {
        return this.props.record.data.attachment_is_image;
    }

    get isPdf() {
        return this.props.record.data.attachment_is_pdf;
    }

    get imageUrl() {
        return url("/web/image", {
            model: "helpdesk_rk.ticket",
            field: "attachment",
            id: this.resId,
        });
    }

    get fileUrl() {
        return url("/web/content", {
            model: "helpdesk_rk.ticket",
            field: "attachment",
            id: this.resId,
        });
    }

    get pdfViewerUrl() {
        return `/web/static/lib/pdfjs/web/viewer.html?file=${encodeURIComponent(this.fileUrl)}`;
    }

    toggleExpanded() {
        this.state.expanded = !this.state.expanded;
    }

    onPdfLoad(ev) {
        const doc = ev.target.contentDocument;
        if (!doc || doc.getElementById("o_helpdesk_pdf_toolbar_style")) {
            return;
        }
        const style = doc.createElement("style");
        style.id = "o_helpdesk_pdf_toolbar_style";
        style.textContent = `${HIDDEN_PDF_TOOLBAR_SELECTORS.join(", ")} { display: none !important; }`;
        doc.head.appendChild(style);
    }
}

export const attachmentPreview = {
    component: AttachmentPreview,
};

registry.category("view_widgets").add("attachment_preview", attachmentPreview);
