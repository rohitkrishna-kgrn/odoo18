/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { FileModel } from "@web/core/file_viewer/file_model";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";

/**
 * Read-only display of an x2many of ir.attachment records with, next to
 * each file's download link, a "Preview" button that opens Odoo's native
 * file viewer (image/PDF/video lightbox) without leaving the form.
 */
export class AttachmentPreviewField extends Component {
    static template = "client_helpdesk_portal.AttachmentPreviewField";
    static props = { ...standardFieldProps };

    setup() {
        this.fileViewer = useFileViewer();
        this.filesCacheKey = null;
        this.filesCache = [];
    }

    /**
     * useFileViewer's open() locates the clicked file inside the files
     * array via Array.indexOf (reference equality), so this must keep
     * returning the *same* FileModel instances across calls/renders —
     * rebuilding fresh objects every time would make that lookup fail
     * (index -1, i.e. an undefined file reaching the viewer template).
     */
    get files() {
        const fieldData = this.props.record.data[this.props.name];
        const records = fieldData ? fieldData.records : [];
        // Keyed on the datapoint's local id, not resId: resId can be falsy
        // (e.g. right after an upload, before the x2many reloads from the
        // server), which would otherwise collide two different states into
        // the same cache key and serve stale/blank FileModels.
        const key = records.map((record) => record.id).join(",");
        if (key === this.filesCacheKey) {
            return this.filesCache;
        }
        this.filesCacheKey = key;
        this.filesCache = records.map((record) => {
            const file = new FileModel();
            Object.assign(file, {
                id: record.resId,
                name: record.data.name,
                filename: record.data.name,
                mimetype: record.data.mimetype,
                checksum: record.data.checksum,
            });
            return file;
        });
        return this.filesCache;
    }

    onPreview(file) {
        if (!file.isViewable) {
            return;
        }
        // Open just this one file (files defaults to [file] in open()).
        // Passing a separately-recomputed sibling array here is what causes
        // useFileViewer's open() to do `siblings.indexOf(file)` against a
        // *different* set of FileModel instances than the one the click
        // handler closed over — a reference-equality mismatch that returns
        // -1, leaving the viewer with startIndex -1 and crashing on
        // `props.files[-1].displayName`. Single-file open sidesteps that
        // entirely: the file is trivially found at index 0 of its own array.
        this.fileViewer.open(file);
    }
}

registry.category("fields").add("attachment_preview_list", {
    component: AttachmentPreviewField,
    supportedTypes: ["one2many", "many2many"],
    relatedFields: [
        { name: "name", type: "char" },
        { name: "mimetype", type: "char" },
        { name: "checksum", type: "char" },
    ],
});
