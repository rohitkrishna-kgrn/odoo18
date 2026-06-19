/** @odoo-module */

import { DateField, dateField } from "@web/views/fields/date/date_field";
import { registry } from "@web/core/registry";

/**
 * Extends the standard DateField to restrict the calendar picker to the
 * valid date range for each reminder period row.
 *
 * Reads `period_date_min` and `period_date_max` from the same record
 * (computed server-side as the intersection of the period range and the
 * engagement start/end dates) and passes them to the datepicker so that
 * dates outside the range are visually disabled.
 */
export class PeriodDateField extends DateField {
    get pickerProps() {
        const pickerProps = super.pickerProps;
        const record = this.props.record;
        if (record) {
            const minDate = record.data.period_date_min;
            const maxDate = record.data.period_date_max;
            if (minDate) pickerProps.minDate = minDate;
            if (maxDate) pickerProps.maxDate = maxDate;
        }
        return pickerProps;
    }
}

registry.category("fields").add("period_date_field", {
    ...dateField,
    component: PeriodDateField,
});
