/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { Component } from "@odoo/owl";

// ── helpers ────────────────────────────────────────────────────────────────────

/** Convert a 24-hour float (e.g. 13.5) → { hour:1, minute:30, period:'pm' } */
function floatToAmPm(val) {
    const totalMin = Math.round((val || 0) * 60);
    const h24 = Math.floor(totalMin / 60) % 24;
    const m   = totalMin % 60;
    const period = h24 >= 12 ? 'pm' : 'am';
    let h12 = h24 % 12;
    if (h12 === 0) h12 = 12;
    return { hour: h12, minute: m, period };
}

/** Convert { hour12, minute, period } → 24-hour float */
function amPmToFloat(hour, minute, period) {
    let h = Math.max(1, Math.min(12, parseInt(hour) || 12));
    const m = Math.max(0, Math.min(59, parseInt(minute) || 0));
    if (period === 'pm' && h !== 12) h += 12;
    if (period === 'am' && h === 12) h = 0;
    return h + m / 60.0;
}

/** Build IST display string from UAE float (UAE = UTC+4, IST = UTC+5:30 → +1.5h) */
function floatToIst(uaeFloat) {
    let ist = (uaeFloat || 0) + 1.5;
    if (ist >= 24) ist -= 24;
    const totalMin = Math.round(ist * 60);
    const h24 = Math.floor(totalMin / 60) % 24;
    const m   = totalMin % 60;
    const period = h24 >= 12 ? 'PM' : 'AM';
    let h12 = h24 % 12;
    if (h12 === 0) h12 = 12;
    return `${h12}:${String(m).padStart(2, '0')} ${period}`;
}

// ── Widget component ───────────────────────────────────────────────────────────

export class FloatTimeAmPm extends Component {
    static template = "recruitment_gk.FloatTimeAmPm";

    static props = {
        id:        { type: String,  optional: true },
        name:      { type: String },
        record:    { type: Object },
        readonly:  { type: Boolean, optional: true },
        className: { type: String,  optional: true },
    };

    setup() {
        this.state = useState({ hour: '9', minute: '00', period: 'am' });
        this._lastVal = null;

        const sync = (val) => {
            if (val === this._lastVal) return;
            this._lastVal = val;
            const { hour, minute, period } = floatToAmPm(val);
            this.state.hour   = String(hour);
            this.state.minute = String(minute).padStart(2, '0');
            this.state.period = period;
        };

        onWillStart(() => sync(this.props.record.data[this.props.name] || 0));
        onWillUpdateProps((next) => sync(next.record.data[next.name] || 0));
    }

    /** Hours list 1–12 */
    get hours() {
        return Array.from({ length: 12 }, (_, i) => String(i + 1));
    }

    /** Minutes in 5-minute steps */
    get minutes() {
        return Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, '0'));
    }

    get istDisplay() {
        return floatToIst(this.props.record.data[this.props.name] || 0);
    }

    get readonlyDisplay() {
        const { hour, minute, period } = floatToAmPm(
            this.props.record.data[this.props.name] || 0
        );
        return `${hour}:${String(minute).padStart(2, '0')} ${period.toUpperCase()}`;
    }

    // ── event handlers ──────────────────────────────────────────────────────

    _commit() {
        const val = amPmToFloat(this.state.hour, this.state.minute, this.state.period);
        this._lastVal = val;
        this.props.record.update({ [this.props.name]: val });
    }

    onHourChange(ev) {
        this.state.hour = ev.target.value;
        this._commit();
    }

    onMinuteChange(ev) {
        this.state.minute = ev.target.value;
        this._commit();
    }

    onPeriodChange(ev) {
        this.state.period = ev.target.value;
        this._commit();
    }
}

registry.category("fields").add("float_time_ampm", {
    component: FloatTimeAmPm,
    displayName: "Time AM/PM",
    supportedTypes: ["float"],
});
