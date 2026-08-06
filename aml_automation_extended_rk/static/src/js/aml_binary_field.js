import { registry } from "@web/core/registry";
import { ListBinaryField, listBinaryField } from "@web/views/fields/binary/binary_field";

/**
 * Stock ListBinaryField only shows the filename once the row has a real
 * database id (see web.BinaryField's readonly branch: `resId and data[name]`).
 * Lines in the AML "Request Additional Documents" wizards are transient and
 * never get a resId until the whole form is sent, so the filename vanished
 * the moment you tabbed to the next line even though the file was still
 * attached. This widget only swaps the template so the filename always
 * shows once set; it reuses the parent's upload/download/clear logic as-is.
 */
export class AmlListBinaryField extends ListBinaryField {
    static template = "aml_automation_extended_rk.AmlListBinaryField";
}

registry.category("fields").add("aml_binary", {
    ...listBinaryField,
    component: AmlListBinaryField,
});
