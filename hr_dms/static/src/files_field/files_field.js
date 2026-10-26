/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { formatDate } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { DateTimeInput } from "@web/core/datetime/datetime_input";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { FileModel } from "@web/core/file_viewer/file_model";
import {
    Many2ManyBinaryField,
    many2ManyBinaryField,
} from "@web/views/fields/many2many_binary/many2many_binary_field";

/**
 * Multi-file upload for HR documents. Differs from many2many_binary in that:
 * - PDFs and images open in Odoo's file viewer instead of downloading;
 * - links are hidden when the category does not let this user download;
 * - a saved file can only be taken off when can_remove_files says so (HR, or the employee
 *   while the document is in Draft); the server enforces it too;
 * - every file has its own expiry date (ir.attachment.hr_dms_expiry_date), saved with the form;
 * - files show as cards with Preview / Download buttons, and a saved document with several files
 *   offers "Download all" as one zip (controllers/main.py, same download rule and audit log).
 */
export class HrDmsFilesField extends Many2ManyBinaryField {
    static template = "hr_dms.FilesField";
    static components = { ...Many2ManyBinaryField.components, DateTimeInput };

    setup() {
        super.setup();
        this.fileViewer = useFileViewer();
    }

    get uploadText() {
        return _t("Upload files");
    }

    get canDownload() {
        return this.props.record.data.can_download;
    }

    get zipUrl() {
        return `/hr_dms/document/${this.props.record.resId}/download`;
    }

    get showZip() {
        const saved = this.props.record.data[this.props.name].resIds || [];
        return this.canDownload && this.props.record.resId && saved.length > 1;
    }

    isViewable(file) {
        return this.toFileModel(file).isViewable;
    }

    sizeText(file) {
        const size = file.file_size;
        if (!size) {
            return "";
        }
        if (size < 1024 * 1024) {
            return `${Math.max(1, Math.round(size / 1024))} KB`;
        }
        return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    }

    canRemove(file) {
        if (this.props.readonly) {
            return false;
        }
        const saved = this.props.record.data[this.props.name].resIds;
        return this.props.record.data.can_remove_files || !saved.includes(file.id);
    }

    canEditExpiry(file) {
        if (this.props.readonly) {
            return false;
        }
        // mirrors ir.attachment._hr_dms_check_manage: editors date any file, uploaders their new ones
        const saved = this.props.record.data[this.props.name].resIds;
        return this.props.record.data.can_edit || !saved.includes(file.id);
    }

    expiryText(file) {
        return file.hr_dms_expiry_date ? formatDate(file.hr_dms_expiry_date) : _t("No expiry");
    }

    expiryState(file) {
        const date = file.hr_dms_expiry_date;
        if (!date) {
            return false;
        }
        const today = luxon.DateTime.local().startOf("day");
        if (date < today) {
            return "expired";
        }
        return date <= today.plus({ days: 30 }) ? "expiring" : false;
    }

    async onExpiryChange(file, value) {
        const record = this.props.record.data[this.props.name].records.find((r) => r.resId === file.id);
        await record.update({ hr_dms_expiry_date: value || false });
    }

    toFileModel(file) {
        return Object.assign(new FileModel(), { id: file.id, name: file.name, mimetype: file.mimetype });
    }

    onFileClick(file) {
        const files = this.files.map((f) => this.toFileModel(f));
        const target = files.find((f) => f.id === file.id);
        if (target.isViewable) {
            this.fileViewer.open(target, files);
        } else {
            window.location.href = this.getUrl(file.id);
        }
    }
}

registry.category("fields").add("hr_dms_files", {
    ...many2ManyBinaryField,
    component: HrDmsFilesField,
    relatedFields: [
        ...many2ManyBinaryField.relatedFields,
        { name: "hr_dms_expiry_date", type: "date" },
        { name: "file_size", type: "integer", readonly: true },
    ],
});
