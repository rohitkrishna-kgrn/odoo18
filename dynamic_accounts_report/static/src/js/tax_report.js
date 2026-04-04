/** @odoo-module */
const { Component } = owl;
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useRef, useState } from "@odoo/owl";
import { BlockUI } from "@web/core/ui/block_ui";
import { download } from "@web/core/network/download";
const actionRegistry = registry.category("actions");
const today = luxon.DateTime.now();
let monthNamesShort = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

class TaxReport extends owl.Component {
    async setup() {
        super.setup(...arguments);
         this.initial_render = true;
        this.orm = useService('orm');
        this.action = useService('action');
        this.tbody = useRef('tbody');
        this.end_date = useRef('date_to');
        this.start_date = useRef('date_from');
        this.global = useRef('global');
        this.account = useRef('account');
        this.tax = useRef('tax');
        this.period = useRef('periods');
        this.period_year = useRef('period_year');
        this.unfoldButton = useRef('unfoldButton');
        this.state = useState({
            move_line: null,
            data: null,
            sale_total: 0.0,
            purchase_total: 0.0,
            total: null,
            journals: null,
            selected_analytic: [],
            analytic_account: null,
            selected_journal_list: [],
            selected_analytic_account_rec: [],
            date_range: 'month',
            date_type: 'month',
            apply_comparison: false,
            comparison_type: null,
            date_viewed: [],
            comparison_number: null,
            options: null,
            report_type: null,
            uae_vat_mode: false,
            uae_data: null,
            method: {
                'accural': true
            },
        });
        this.load_data(self.initial_render = true);
    }
    async load_data() {
        /**
         * Loads the data for the trial balance report.
         */
        let move_line_list = []
        let move_lines_total = ''
        var self = this;
        var action_title = self.props.action.display_name;
        try {
            var self = this;
            var today = new Date();
            var startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
            var endOfMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0);
            self.state.data = await self.orm.call("tax.report", "view_report", []);
            self.start_date.el.value = startOfMonth.getFullYear() + '-' + String(startOfMonth.getMonth() + 1).padStart(2, '0') + '-' + String(startOfMonth.getDate()).padStart(2, '0');
            self.end_date.el.value = endOfMonth.getFullYear() + '-' + String(endOfMonth.getMonth() + 1).padStart(2, '0') + '-' + String(endOfMonth.getDate()).padStart(2, '0');
            self.state.date_viewed.push(monthNamesShort[today.getMonth()] + '  ' + today.getFullYear())
            self.state.data.sale.forEach((value) => {
                const v = value.tax_raw !== undefined ? value.tax_raw : (parseFloat(String(value.tax).replace(/,/g, '')) || 0);
                self.state.sale_total += v;
            });
            self.state.data.purchase.forEach((value) => {
                const v = value.tax_raw !== undefined ? value.tax_raw : (parseFloat(String(value.tax).replace(/,/g, '')) || 0);
                self.state.purchase_total += v;
            });
        }
        catch (el) {
            window.location.href;
        }
    }
    async applyFilter(val, ev, is_delete) {
        if (ev && ev.target && ev.target.attributes["data-value"] && ev.target.attributes["data-value"].value == 'no comparison') {
            const lastIndex = this.state.date_viewed.length - 1;
            this.state.date_viewed.splice(0, lastIndex);
        }
        if (val && val.target.name === 'start_date') {
            this.state.date_viewed = []
            this.state.date_viewed.push('From' + ' ' + this.formatDate(this.start_date.el.value) + ' ' + 'To' + ' ' + this.formatDate(this.end_date.el.value))
            this.state.date_range = {
                ...this.state.date_range,
                start_date: val.target.value
            };
        } else if (val && val.target.name === 'end_date') {
            this.state.date_viewed = []
            this.state.date_viewed.push('From' + ' ' + this.formatDate(this.start_date.el.value) + 'To' + ' ' + this.formatDate(this.end_date.el.value))
            this.state.date_range = {
                ...this.state.date_range,
                end_date: val.target.value
            };
        } else if (val && val.target.attributes["data-value"].value == 'month') {
            this.start_date.el.value = today.startOf('month').toFormat('yyyy-MM-dd')
            this.end_date.el.value = today.endOf('month').toFormat('yyyy-MM-dd')
            this.state.date_viewed = []
            this.state.date_viewed.push(today.monthShort + ' ' + today.c.year)
            this.state.date_type = val.target.attributes["data-value"].value
            this.state.comparison_type = this.state.date_type
            this.state.date_range = {
                start_date: this.start_date.el.value,
                end_date: this.end_date.el.value
            };
        } else if (val && val.target.attributes["data-value"].value == 'year') {
            this.start_date.el.value = today.startOf('year').toFormat('yyyy-MM-dd')
            this.end_date.el.value = today.endOf('year').toFormat('yyyy-MM-dd')
            this.state.date_viewed = []
            this.state.date_viewed.push(today.c.year)
            this.state.date_type = val.target.attributes["data-value"].value
            this.state.comparison_type = this.state.date_type
            this.state.date_range = {
                start_date: this.start_date.el.value,
                end_date: this.end_date.el.value
            };
        } else if (val && val.target.attributes["data-value"].value == 'quarter') {
            this.start_date.el.value = today.startOf('quarter').toFormat('yyyy-MM-dd')
            this.end_date.el.value = today.endOf('quarter').toFormat('yyyy-MM-dd')
            this.state.date_viewed = []
            this.state.date_viewed.push('Q' + ' ' + today.quarter)
            this.state.comparison_type = 'quarter'
            this.state.date_type = val.target.attributes["data-value"].value
            this.state.date_range = {
                start_date: this.start_date.el.value,
                end_date: this.end_date.el.value
            };
        } else if (val && val.target.attributes["data-value"].value == 'last-month') {
            this.start_date.el.value = today.startOf('month').minus({ days: 1 }).startOf('month').toFormat('yyyy-MM-dd')
            this.end_date.el.value = today.startOf('month').minus({ days: 1 }).toFormat('yyyy-MM-dd')
            this.state.date_viewed = []
            this.state.date_viewed.push(today.startOf('month').minus({ days: 1 }).monthShort + ' ' + today.startOf('month').minus({ days: 1 }).c.year)
            this.state.date_type = 'month'
            this.state.comparison_type = this.state.date_type
            this.state.date_range = {
                start_date: this.start_date.el.value,
                end_date: this.end_date.el.value
            };
        } else if (val && val.target.attributes["data-value"].value == 'last-year') {
            this.start_date.el.value = today.startOf('year').minus({ days: 1 }).startOf('year').toFormat('yyyy-MM-dd')
            this.end_date.el.value = today.startOf('year').minus({ days: 1 }).toFormat('yyyy-MM-dd')
            this.state.date_viewed = []
            this.state.date_viewed.push(today.startOf('year').minus({ days: 1 }).c.year)
            this.state.date_type = 'year'
            this.state.comparison_type = this.state.date_type
            this.state.date_range = {
                start_date: this.start_date.el.value,
                end_date: this.end_date.el.value
            };
        } else if (val && val.target.attributes["data-value"].value == 'last-quarter') {
            this.start_date.el.value = today.startOf('quarter').minus({ days: 1 }).startOf('quarter').toFormat('yyyy-MM-dd')
            this.end_date.el.value = today.startOf('quarter').minus({ days: 1 }).toFormat('yyyy-MM-dd')
            this.state.date_viewed = []
            this.state.date_viewed.push('Q' + ' ' + today.startOf('quarter').minus({ days: 1 }).quarter)
            this.state.date_type = 'quarter'
            this.state.comparison_type = this.state.date_type
            this.state.date_range = {
                start_date: this.start_date.el.value,
                end_date: this.end_date.el.value
            };
        } else if (val && val.target.attributes["data-value"].value === 'draft') {
            if (val.target.classList.contains("selected-filter")) {
                const { draft, ...updatedAccount } = this.state.options;
                this.state.options = updatedAccount;
                val.target.classList.remove("selected-filter");
            } else {
                this.state.options = {
                    ...this.state.options,
                    'draft': true
                };
                val.target.classList.add("selected-filter");
            }
        } else if (val && val.target.attributes["data-value"].value === 'account tax') {
            if (val.target.classList.contains("selected-filter")) {
                const { account, ...updatedAccount } = this.state.report_type;
                this.state.report_type = updatedAccount;
                val.target.classList.remove("selected-filter");
            } else {
                this.state.report_type = {
                    'account': true
                };
                val.target.classList.add("selected-filter");
                if(this.tax.el.classList.contains("selected-filter")) {
                    this.tax.el.classList.remove("selected-filter");
                }
                if(this.global.el.classList.contains("selected-filter")) {
                    this.global.el.classList.remove("selected-filter");
                }
            }
        } else if (val && val.target.attributes["data-value"].value === 'tax account') {
            if (val.target.classList.contains("selected-filter")) {
                const { tax, ...updatedAccount } = this.state.report_type;
                this.state.report_type = updatedAccount;
                val.target.classList.remove("selected-filter");
            } else {
                this.state.report_type = {
                    'tax': true
                };
                val.target.classList.add("selected-filter");
                if(this.account.el.classList.contains("selected-filter")) {
                    this.account.el.classList.remove("selected-filter");
                }
                if(this.global.el.classList.contains("selected-filter")) {
                    this.global.el.classList.remove("selected-filter");
                }
            }
        } else if (val && val.target.attributes["data-value"].value === 'global') {
            if (val.target.classList.contains("selected-filter")) {
                const { global, ...updatedAccount } = this.state.report_type;
                this.state.report_type = updatedAccount;
                val.target.classList.remove("selected-filter");
            } else {
                this.state.report_type = null
                val.target.classList.add("selected-filter");
                if(this.account.el.classList.contains("selected-filter")) {
                    this.account.el.classList.remove("selected-filter");
                }
                if(this.tax.el.classList.contains("selected-filter")) {
                    this.tax.el.classList.remove("selected-filter");
                }
            }
        }
        if (this.state.apply_comparison == true) {
            if (this.state.comparison_type == 'year') {
                this.state.date_viewed = []
                if (this.start_date.el.value) {
                    var current_year = new Date(this.start_date.el.value).getFullYear();
                    var month = new Date(this.start_date.el.value).getMonth();
                } else {
                    var current_year = new Date(today).getFullYear();
                    var month = new Date(today).getMonth()
                }
                this.state.comparison_number = this.period_year.el.value
                for (var i = this.state.comparison_number; i >= 0; i--) {
                    var date = monthNamesShort[month] + ' ' + (current_year - i);
                    this.state.date_viewed.push(date);
                }
            } else if (this.state.comparison_type == 'month') {
                this.state.date_viewed = []
                this.state.comparison_number = this.period.el.value
            } else if (this.state.comparison_type == 'quarter') {
                this.state.date_viewed = []
                this.state.comparison_number = this.period.el.value
            }
        }
        this.state.data = await this.orm.call("tax.report", "get_filter_values", [this.start_date.el.value, this.end_date.el.value, this.state.comparison_number, this.state.comparison_type, this.state.options,this.state.report_type,]);
        var sale_total = 0.0
        var purchase_total = 0.0
        this.state.data.sale.forEach((value) => {
            sale_total += typeof value.tax === 'number' ? value.tax : parseFloat(String(value.tax).replace(/,/g, '')) || 0;
        });
        this.state.data.purchase.forEach((value) => {
            purchase_total += typeof value.tax === 'number' ? value.tax : parseFloat(String(value.tax).replace(/,/g, '')) || 0;
        });
        var date_viewed = []
        if (this.state.data.dynamic_date_num) {
            let iterable = Array.isArray(this.state.data.dynamic_date_num)
                ? this.state.data.dynamic_date_num
                : Object.values(this.state.data.dynamic_date_num);
            for (const date_num of iterable) {
                if (!date_viewed.includes(date_num)) {
                    date_viewed.push(date_num);
                }
            }
        }
        if (date_viewed.length !== 0) {
            this.state.date_viewed = date_viewed.reverse()
        }
        this.state.sale_total = sale_total
        this.state.purchase_total = purchase_total
        if (this.state.uae_vat_mode) {
            await this.loadUAEData();
        }
    }
    async loadUAEData() {
        const start = this.start_date.el ? this.start_date.el.value : '';
        const end = this.end_date.el ? this.end_date.el.value : '';
        this.state.uae_data = await this.orm.call(
            'tax.report', 'get_uae_vat_report',
            [start, end, this.state.options]
        );
    }
    async toggleUAEMode() {
        this.state.uae_vat_mode = !this.state.uae_vat_mode;
        if (this.state.uae_vat_mode) {
            await this.loadUAEData();
        }
    }
    formatDate(dateString) {
        if (!dateString) return '';
        const date = new Date(dateString);
        const day = date.getDate().toString().padStart(2, '0');
        const month = (date.getMonth() + 1).toString().padStart(2, '0');
        const year = date.getFullYear();
        return `${day}/${month}/${year}`;
    }
    async printPdf(ev) {
        /**
         * Asynchronously generates and prints a PDF report.
         * Triggers an action to generate a PDF report based on the current state and settings.
         *
         * @param {Event} ev - Event object triggering the PDF report generation.
         * @returns {Promise} A promise that resolves after the PDF report action is triggered.
         */
        ev.preventDefault();
        var self = this;
        var action_title = self.props.action.display_name;
        let comparison_number_range = self.comparison_number_range
        let date_viewed = self.state.date_viewed
        if (self.state.apply_comparison) {
             if (self.comparison_number_range.length > 10) {
                comparison_number_range = self.comparison_number_range.slice(-10);
                date_viewed = self.state.date_viewed.slice(-11);
             }
         }
        return self.action.doAction({
            'type': 'ir.actions.report',
            'report_type': 'qweb-pdf',
            'report_name': 'dynamic_accounts_report.tax_report',
            'report_file': 'dynamic_accounts_report.tax_report',
            'data': {
                'data': self.state.data,
                'sale_total': self.state.sale_total,
                'purchase_total': self.state.purchase_total,
                'date_viewed': date_viewed,
                'apply_comparison': self.state.apply_comparison,
                'comparison_number_range': comparison_number_range,
                'report_type': self.state.report_type,
                'filters': this.filter(),
                'title': action_title,
                'report_name': self.props.action.display_name,
                'uae_vat_mode': self.state.uae_vat_mode,
                'uae_data': self.state.uae_data,
            },
            'display_name': self.props.action.display_name,
        });
    }
    async print_xlsx() {
        /**
         * Asynchronously generates and downloads an XLSX report.
         * Triggers an action to generate an XLSX report based on the current state and settings,
         * and initiates the download of the generated XLSX file.
         *
         * @returns {void} No explicit return value.
         */
        var self = this;
        var action_title = self.props.action.display_name;
        var datas = {
                'data': self.state.data,
                'sale_total': self.state.sale_total,
                'purchase_total': self.state.purchase_total,
                'date_viewed': self.state.date_viewed,
                'apply_comparison': self.state.apply_comparison,
                'comparison_number_range': self.comparison_number_range,
                'report_type': self.state.report_type,
                'filters': this.filter(),
                'title': action_title,
                'report_name': self.props.action.display_name,
                'uae_vat_mode': self.state.uae_vat_mode,
                'uae_data': self.state.uae_data,
        }
        var action = {
            'data': {
                'model': 'tax.report',
                'data': JSON.stringify(datas),
                'output_format': 'xlsx',
                'report_action': self.props.action.id,
                'report_name': action_title,
            },
        };
        BlockUI;
        await download({
            url: '/xlsx_report',
            data: action.data,
            complete: () => unblockUI,
            error: (error) => self.call('crash_manager', 'rpc_error', error),
        });
    }
    filter() {
    var self=this;
    let startDate, endDate;
    let startYear, startMonth, startDay, endYear, endMonth, endDay;
        if (self.state.date_range){
            const today = new Date();
            if (self.state.date_range === 'year') {
                startDate = new Date(today.getFullYear(), 0, 1);
                endDate = new Date(today.getFullYear(), 11, 31);
            } else if (self.state.date_range === 'quarter') {
                const currentQuarter = Math.floor(today.getMonth() / 3);
                startDate = new Date(today.getFullYear(), currentQuarter * 3, 1);
                endDate = new Date(today.getFullYear(), (currentQuarter + 1) * 3, 0);
            } else if (self.state.date_range === 'month') {
                startDate = new Date(today.getFullYear(), today.getMonth(), 1);
                endDate = new Date(today.getFullYear(), today.getMonth() + 1, 0);
            } else if (self.state.date_range === 'last-month') {
                startDate = new Date(today.getFullYear(), today.getMonth() - 1, 1);
                endDate = new Date(today.getFullYear(), today.getMonth(), 0);
            } else if (self.state.date_range === 'last-year') {
                startDate = new Date(today.getFullYear() - 1, 0, 1);
                endDate = new Date(today.getFullYear() - 1, 11, 31);
            } else if (self.state.date_range === 'last-quarter') {
                const lastQuarter = Math.floor((today.getMonth() - 3) / 3);
                startDate = new Date(today.getFullYear(), lastQuarter * 3, 1);
                endDate = new Date(today.getFullYear(), (lastQuarter + 1) * 3, 0);
            }
        // Get the date components for start and end dates
        if (startDate) {
        startYear = startDate.getFullYear();
        startMonth = startDate.getMonth() + 1;
        startDay = startDate.getDate();
        }
        if (endDate) {
        endYear = endDate.getFullYear();
        endMonth = endDate.getMonth() + 1;
        endDay = endDate.getDate();
        }
        }
        let filters = {
            'options': self.state.options,
            'comparison_type': self.state.comparison_type,
            'comparison_number_range': self.state.comparison_number,
            'start_date': null,
            'end_date': null,
        };
        // Check if start and end dates are available before adding them to the filters object
        if (startYear !== undefined && startMonth !== undefined && startDay !== undefined &&
            endYear !== undefined && endMonth !== undefined && endDay !== undefined) {
            filters['start_date'] = `${startYear}-${startMonth < 10 ? '0' : ''}${startMonth}-${startDay < 10 ? '0' : ''}${startDay}`;
            filters['end_date'] = `${endYear}-${endMonth < 10 ? '0' : ''}${endMonth}-${endDay < 10 ? '0' : ''}${endDay}`;
        }
        return filters
    }
    onPeriodChange(ev) {
        /**
         * Event handler for period change.
         * Updates the value of 'period_year' element based on the event target value.
         *
         * @param {Event} ev - Event object triggered by the period change.
         * @returns {void} No explicit return value.
         */
        this.period_year.el.value = ev.target.value
    }
    onPeriodYearChange(ev) {
        /**
         * Event handler for period year change.
         * Updates the value of 'period' element based on the event target value.
         *
         * @param {Event} ev - Event object triggered by the period year change.
         * @returns {void} No explicit return value.
         */
        this.period.el.value = ev.target.value
    }
    applyComparisonPeriod(ev) {
        /**
         * Applies a comparison period and triggers data filtering.
         * Sets 'apply_comparison' flag to true and updates 'comparison_type'.
         * Invokes 'applyFilter' method to apply filters and load data.
         *
         * @param {Event} ev - Event object triggering the comparison period application.
         * @returns {void} No explicit return value.
         */
        this.state.apply_comparison = true
        this.state.comparison_type = this.state.date_type
        this.applyFilter(null, ev)
    }
    applyComparisonYear(ev) {
        /**
         * Applies a comparison year and triggers data filtering.
         * Sets 'apply_comparison' flag to true and updates 'comparison_type' to 'year'.
         * Invokes 'applyFilter' method to apply filters and load data.
         *
         * @param {Event} ev - Event object triggering the comparison year application.
         * @returns {void} No explicit return value.
         */
        this.state.apply_comparison = true
        this.state.comparison_type = 'year'
        this.applyFilter(null, ev)
    }
    async applyComparison(ev) {
        /**
         * Disables comparison mode, resets comparison settings, and triggers data filtering.
         * Sets 'apply_comparison' flag to false and clears 'comparison_type' and 'comparison_number'.
         * Removes all date view entries except the current month/year.
         * Invokes 'applyFilter' method to apply filters and load data.
         *
         * @param {Event} ev - Event object triggering the comparison mode removal.
         * @returns {void} No explicit return value.
         */
        this.state.apply_comparison = false
        this.state.comparison_type = null
        this.state.comparison_number = null
        const lastIndex = this.state.date_viewed.length - 1;
        this.state.date_viewed.splice(0, lastIndex);
        this.applyFilter(null, ev)
    }
    formatNum(val) {
        if (val === undefined || val === null || val === '') return '';
        const n = typeof val === 'string' ? parseFloat(val.replace(/,/g, '')) : val;
        if (isNaN(n)) return '';
        return n.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }
    async applyManualFilter() {
        await this.applyFilter(null, null);
    }
    _groupData(lines) {
        if (!lines || lines.length === 0) return [];
        const reportType = this.state.report_type;
        const fmt = (v) => {
            const n = typeof v === 'string' ? parseFloat(v.replace(/,/g, '')) : (v || 0);
            return isNaN(n) ? '0.00' : n.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        };
        const rawNum = (v) => {
            const n = typeof v === 'string' ? parseFloat(v.replace(/,/g, '')) : v;
            return isNaN(n) ? 0 : (n || 0);
        };
        // Global view: no grouping, flat rows
        if (!reportType || Object.keys(reportType).length === 0) {
            return lines.map(line => ({
                key: line.name + ' (' + line.amount + '%)',
                items: [],
                line: line,
                total_net: fmt(line.net),
                total_tax: fmt(line.tax),
                dynamic_net_sums: {},
                dynamic_tax_sums: {},
            }));
        }
        const groupType = Object.keys(reportType)[0]; // 'account' or 'tax'
        const headerKey = groupType === 'account' ? 'account' : 'name';
        const groupMap = new Map();
        for (const line of lines) {
            const key = line[headerKey] || 'Unknown';
            if (!groupMap.has(key)) {
                groupMap.set(key, {
                    key,
                    items: [],
                    net_sum: 0,
                    tax_sum: 0,
                    dynamic_net_sums: {},
                    dynamic_tax_sums: {},
                });
            }
            const g = groupMap.get(key);
            g.net_sum += rawNum(line.net);
            g.tax_sum += rawNum(line.tax);
            if (line['dynamic net']) {
                for (const [k, v] of Object.entries(line['dynamic net'])) {
                    g.dynamic_net_sums[k] = (g.dynamic_net_sums[k] || 0) + rawNum(v);
                }
            }
            if (line['dynamic tax']) {
                for (const [k, v] of Object.entries(line['dynamic tax'])) {
                    g.dynamic_tax_sums[k] = (g.dynamic_tax_sums[k] || 0) + rawNum(v);
                }
            }
            g.items.push(line);
        }
        return Array.from(groupMap.values()).map(g => ({
            key: g.key,
            items: g.items,
            line: null,
            total_net: fmt(g.net_sum),
            total_tax: fmt(g.tax_sum),
            dynamic_net_sums: g.dynamic_net_sums,
            dynamic_tax_sums: g.dynamic_tax_sums,
        }));
    }
    get groupedSaleData() {
        if (!this.state.data || !this.state.data.sale) return [];
        return this._groupData(this.state.data.sale);
    }
    get groupedPurchaseData() {
        if (!this.state.data || !this.state.data.purchase) return [];
        return this._groupData(this.state.data.purchase);
    }
    get comparison_number_range() {
        /**
         * Generates an array of numbers representing a comparison number range.
         * The range includes numbers from 1 up to the 'comparison_number' value in the state.
         *
         * @returns {Array} An array of numbers representing the comparison number range.
         */
        const range = [];
        for (let i = 1; i <= this.state.comparison_number; i++) {
            range.push(i);
        }
        return range.reverse();
    }
}
TaxReport.template = 'tax_r_template_new';
actionRegistry.add("tax_r", TaxReport);
