# -*- coding: utf-8 -*-
################################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Bhagyadev KP (<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
################################################################################
import calendar
import io
import json
from datetime import datetime
import xlsxwriter
from odoo import models, fields, api
from odoo.tools.date_utils import get_month, get_fiscal_year, \
    get_quarter_number, subtract


class TaxReport(models.TransientModel):
    """For creating Tax report."""
    _name = 'tax.report'
    _description = 'Tax Report'

    @api.model
    def view_report(self):
        """
        View a tax report for the current month. This function retrieves
        tax-related information for the current month. It calculates the net
        amount and tax amount for both sales and purchases based on the tax
        information associated with account move lines.
            :return: Dictionary containing sale and purchase data for the
                     current month.
        """
        sale = []
        purchase = []
        tax_ids = self.env['account.move.line'].search([]).mapped(
            'tax_ids')
        today = fields.Date.today()
        for tax in tax_ids:
            tax_id = self.env['account.move.line'].search(
                [('tax_ids', '=', tax.id), ('parent_state', '=', 'posted'),
                 ('date', '>=', get_month(today)[0]),
                 ('date', '<=', get_month(today)[1])]).read(
                ['debit', 'credit'])
            tax_debit_sums = sum(record['debit'] for record in tax_id)
            tax_credit_sums = sum(record['credit'] for record in tax_id)
            net = round(tax_debit_sums + tax_credit_sums, 2)
            tax_val = round(net * (tax.amount / 100), 2)
            if tax.type_tax_use == 'sale':
                sale.append({
                    'name': tax.name,
                    'amount': "{:,.2f}".format(tax.amount),
                    'net': "{:,.2f}".format(net),
                    'tax': "{:,.2f}".format(tax_val),
                    'tax_raw': tax_val,
                })
            elif tax.type_tax_use == 'purchase':
                purchase.append({
                    'name': tax.name,
                    'amount': "{:,.2f}".format(tax.amount),
                    'net': "{:,.2f}".format(net),
                    'tax': "{:,.2f}".format(tax_val),
                    'tax_raw': tax_val,
                })
        return {
            'sale': sale,
            'purchase': purchase
        }

    @api.model
    def get_filter_values(self, start_date, end_date, comparison_number,
                          comparison_type, options, report_type):
        """
           Get filtered tax values based on various criteria.

           :param start_date: Start date of the filter period.
           :param end_date: End date of the filter period.
           :param comparison_number: Number of comparison periods.
           :param comparison_type: Type of comparison (year, month, quarter).
           :param options: Filter options.
           :param report_type: Type of report (account, tax).
           :return: Dictionary containing dynamic_date_num, sale, and purchase
                    data.
           """
        sale = []
        purchase = []
        dynamic_date_num = {}
        if options == {}:
            options = None
        if options is None:
            option_domain = ['posted']
        elif 'draft' in options:
            option_domain = ['posted', 'draft']
        tax_ids = self.env['account.move.line'].search([]).mapped(
            'tax_ids')
        start_date_first = \
            get_fiscal_year(datetime.strptime(start_date, "%Y-%m-%d").date())[
                0] if comparison_type == 'year' else datetime.strptime(
                start_date, "%Y-%m-%d").date()
        end_date_first = \
            get_fiscal_year(datetime.strptime(end_date, "%Y-%m-%d").date())[
                1] if comparison_type == 'year' else datetime.strptime(
                end_date, "%Y-%m-%d").date()
        if report_type is not None and 'account' in report_type:
            start_date = start_date_first
            end_date = end_date_first
            account_ids = self.env['account.move.line'].search([]).mapped(
                'account_id')
            for account in account_ids:
                tax_ids = self.env['account.move.line'].search(
                    [('account_id', '=', account.id)]).mapped('tax_ids')
                if tax_ids:
                    for tax in tax_ids:
                        dynamic_total_tax_sum = {}
                        dynamic_total_net_sum = {}
                        if comparison_number:
                            if comparison_type == 'year':
                                start_date = start_date_first
                                end_date = end_date_first
                                for i in range(1, eval(comparison_number) + 1):
                                    com_start_date = subtract(start_date,
                                                              years=i)
                                    com_end_date = subtract(end_date, years=i)
                                    tax_id = self.env[
                                        'account.move.line'].search(
                                        [('tax_ids', '=', tax.id),
                                         ('date', '>=', com_start_date),
                                         ('date', '<=', com_end_date),
                                         ('account_id', '=', account.id),
                                         ('parent_state', 'in',
                                          option_domain)]).read(
                                        ['debit', 'credit'])
                                    tax_debit_sums = sum(
                                        record['debit'] for record in tax_id)
                                    tax_credit_sums = sum(
                                        record['credit'] for record in tax_id)
                                    dynamic_total_net_sum[
                                        f"dynamic_total_net_sum{i}"] = tax_debit_sums + tax_credit_sums
                                    dynamic_total_tax_sum[
                                        f"dynamic_total_tax_sum{i}"] = \
                                        dynamic_total_net_sum[
                                            f"dynamic_total_net_sum{i}"] * (
                                                tax.amount / 100)
                            elif comparison_type == 'month':
                                dynamic_date_num[
                                    f"dynamic_date_num{0}"] = self.get_month_name(
                                    start_date) + ' ' + str(start_date.year)
                                for i in range(1, eval(comparison_number) + 1):
                                    com_start_date = subtract(start_date,
                                                              months=i)
                                    com_end_date = subtract(end_date, months=i)
                                    tax_id = self.env[
                                        'account.move.line'].search(
                                        [('tax_ids', '=', tax.id),
                                         ('date', '>=', com_start_date),
                                         ('account_id', '=', account.id),
                                         ('date', '<=', com_end_date),
                                         ('parent_state', 'in',
                                          option_domain)]).read(
                                        ['debit', 'credit'])
                                    tax_debit_sums = sum(
                                        record['debit'] for record in tax_id)
                                    tax_credit_sums = sum(
                                        record['credit'] for record in tax_id)
                                    dynamic_total_net_sum[
                                        f"dynamic_total_net_sum{i}"] = tax_debit_sums + tax_credit_sums
                                    dynamic_total_tax_sum[
                                        f"dynamic_total_tax_sum{i}"] = \
                                        dynamic_total_net_sum[
                                            f"dynamic_total_net_sum{i}"] * (
                                                tax.amount / 100)
                                    dynamic_date_num[
                                        f"dynamic_date_num{i}"] = self.get_month_name(
                                        com_start_date) + ' ' + str(
                                        com_start_date.year)
                            elif comparison_type == 'quarter':
                                dynamic_date_num[
                                    f"dynamic_date_num{0}"] = 'Q' + ' ' + str(
                                    get_quarter_number(
                                        start_date)) + ' ' + str(
                                    start_date.year)
                                for i in range(1, eval(comparison_number) + 1):
                                    com_start_date = subtract(start_date,
                                                              months=i * 3)
                                    com_end_date = subtract(end_date,
                                                            months=i * 3)
                                    tax_id = self.env[
                                        'account.move.line'].search(
                                        [('tax_ids', '=', tax.id),
                                         ('date', '>=', com_start_date),
                                         ('account_id', '=', account.id),
                                         ('date', '<=', com_end_date),
                                         ('parent_state', 'in',
                                          option_domain)]).read(
                                        ['debit', 'credit'])
                                    tax_debit_sums = sum(
                                        record['debit'] for record in tax_id)
                                    tax_credit_sums = sum(
                                        record['credit'] for record in tax_id)
                                    dynamic_total_net_sum[
                                        f"dynamic_total_net_sum{i}"] = tax_debit_sums + tax_credit_sums
                                    dynamic_total_tax_sum[
                                        f"dynamic_total_tax_sum{i}"] = \
                                        dynamic_total_net_sum[
                                            f"dynamic_total_net_sum{i}"] * (
                                                tax.amount / 100)
                                    dynamic_date_num[
                                        f"dynamic_date_num{i}"] = 'Q' + ' ' + str(
                                        get_quarter_number(
                                            com_start_date)) + ' ' + str(
                                        com_start_date.year)
                        tax_id = self.env['account.move.line'].search(
                            [('tax_ids', '=', tax.id),
                             ('date', '>=', start_date_first),
                             ('date', '<=', end_date_first),
                             ('parent_state', 'in', option_domain),
                             ('account_id', '=', account.id)]).read(
                            ['debit', 'credit'])
                        tax_debit_sums = sum(
                            record['debit'] for record in tax_id)
                        tax_credit_sums = sum(
                            record['credit'] for record in tax_id)
                        if tax_id and tax.type_tax_use == 'sale':
                            if comparison_number:
                                sale.append({
                                    'name': tax.name,
                                    'amount': tax.amount,
                                    'net': round(
                                        tax_debit_sums + tax_credit_sums,
                                        2),
                                    'tax': round(
                                        (tax_debit_sums + tax_credit_sums) * (
                                                tax.amount / 100), 2),
                                    'dynamic net': dynamic_total_net_sum,
                                    'dynamic tax': dynamic_total_tax_sum,
                                    'account': account.display_name,
                                })
                            else:
                                sale.append({
                                    'name': tax.name,
                                    'amount': tax.amount,
                                    'net': round(
                                        tax_debit_sums + tax_credit_sums,
                                        2),
                                    'tax': round(
                                        (tax_debit_sums + tax_credit_sums) * (
                                                tax.amount / 100), 2),
                                    'account': account.display_name,
                                })
                        elif tax_id and tax.type_tax_use == 'purchase':
                            if comparison_number:
                                purchase.append({
                                    'name': tax.name,
                                    'amount': tax.amount,
                                    'net': round(
                                        tax_debit_sums + tax_credit_sums,
                                        2),
                                    'tax': round(
                                        (tax_debit_sums + tax_credit_sums) * (
                                                tax.amount / 100), 2),
                                    'dynamic net': dynamic_total_net_sum,
                                    'dynamic tax': dynamic_total_tax_sum,
                                    'account': account.display_name,
                                })
                            else:
                                purchase.append({
                                    'name': tax.name,
                                    'amount': tax.amount,
                                    'net': round(
                                        tax_debit_sums + tax_credit_sums,
                                        2),
                                    'tax': round(
                                        (tax_debit_sums + tax_credit_sums) * (
                                                tax.amount / 100), 2),
                                    'account': account.display_name,
                                })
        elif report_type is not None and 'tax' in report_type:
            start_date = start_date_first
            end_date = end_date_first
            for tax in tax_ids:
                account_ids = self.env['account.move.line'].search(
                    [('tax_ids', '=', tax.id)]).mapped('account_id')
                for account in account_ids:
                    dynamic_total_tax_sum = {}
                    dynamic_total_net_sum = {}
                    if comparison_number:
                        if comparison_type == 'year':
                            start_date = start_date_first
                            end_date = end_date_first
                            for i in range(1, eval(comparison_number) + 1):
                                com_start_date = subtract(start_date,
                                                          years=i)
                                com_end_date = subtract(end_date, years=i)
                                tax_id = self.env[
                                    'account.move.line'].search(
                                    [('tax_ids', '=', tax.id),
                                     ('date', '>=', com_start_date),
                                     ('date', '<=', com_end_date),
                                     ('account_id', '=', account.id),
                                     ('parent_state', 'in',
                                      option_domain)]).read(
                                    ['debit', 'credit'])
                                tax_debit_sums = sum(
                                    record['debit'] for record in tax_id)
                                tax_credit_sums = sum(
                                    record['credit'] for record in tax_id)
                                dynamic_total_net_sum[
                                    f"dynamic_total_net_sum{i}"] = tax_debit_sums + tax_credit_sums
                                dynamic_total_tax_sum[
                                    f"dynamic_total_tax_sum{i}"] = \
                                    dynamic_total_net_sum[
                                        f"dynamic_total_net_sum{i}"] * (
                                            tax.amount / 100)
                        elif comparison_type == 'month':
                            dynamic_date_num[
                                f"dynamic_date_num{0}"] = self.get_month_name(
                                start_date) + ' ' + str(start_date.year)
                            for i in range(1, eval(comparison_number) + 1):
                                com_start_date = subtract(start_date, months=i)
                                com_end_date = subtract(end_date, months=i)
                                tax_id = self.env[
                                    'account.move.line'].search(
                                    [('tax_ids', '=', tax.id),
                                     ('date', '>=', com_start_date),
                                     ('date', '<=', com_end_date),
                                     ('account_id', '=', account.id),
                                     ('parent_state', 'in',
                                      option_domain)]).read(
                                    ['debit', 'credit'])
                                tax_debit_sums = sum(
                                    record['debit'] for record in tax_id)
                                tax_credit_sums = sum(
                                    record['credit'] for record in tax_id)
                                dynamic_total_net_sum[
                                    f"dynamic_total_net_sum{i}"] = tax_debit_sums + tax_credit_sums
                                dynamic_total_tax_sum[
                                    f"dynamic_total_tax_sum{i}"] = \
                                    dynamic_total_net_sum[
                                        f"dynamic_total_net_sum{i}"] * (
                                            tax.amount / 100)
                                dynamic_date_num[
                                    f"dynamic_date_num{i}"] = self.get_month_name(
                                    com_start_date) + ' ' + str(
                                    com_start_date.year)
                        elif comparison_type == 'quarter':
                            dynamic_date_num[
                                f"dynamic_date_num{0}"] = 'Q' + ' ' + str(
                                get_quarter_number(start_date)) + ' ' + str(
                                start_date.year)
                            for i in range(1, eval(comparison_number) + 1):
                                com_start_date = subtract(start_date,
                                                          months=i * 3)
                                com_end_date = subtract(end_date,
                                                        months=i * 3)
                                tax_id = self.env[
                                    'account.move.line'].search(
                                    [('tax_ids', '=', tax.id),
                                     ('date', '>=', com_start_date),
                                     ('date', '<=', com_end_date),
                                     ('account_id', '=', account.id),
                                     ('parent_state', 'in',
                                      option_domain)]).read(
                                    ['debit', 'credit'])
                                tax_debit_sums = sum(
                                    record['debit'] for record in tax_id)
                                tax_credit_sums = sum(
                                    record['credit'] for record in tax_id)
                                dynamic_total_net_sum[
                                    f"dynamic_total_net_sum{i}"] = tax_debit_sums + tax_credit_sums
                                dynamic_total_tax_sum[
                                    f"dynamic_total_tax_sum{i}"] = \
                                    dynamic_total_net_sum[
                                        f"dynamic_total_net_sum{i}"] * (
                                            tax.amount / 100)
                                dynamic_date_num[
                                    f"dynamic_date_num{i}"] = 'Q' + ' ' + str(
                                    get_quarter_number(
                                        com_start_date)) + ' ' + str(
                                    com_start_date.year)
                    tax_id = self.env['account.move.line'].search(
                        [('tax_ids', '=', tax.id),
                         ('parent_state', 'in', option_domain),
                         ('date', '>=', start_date_first),
                         ('date', '<=', end_date_first),
                         ('account_id', '=', account.id)]).read(
                        ['debit', 'credit'])
                    tax_debit_sums = sum(
                        record['debit'] for record in tax_id)
                    tax_credit_sums = sum(
                        record['credit'] for record in tax_id)
                    if tax_id and tax.type_tax_use == 'sale':
                        if comparison_number:
                            sale.append({
                                'name': tax.name,
                                'amount': tax.amount,
                                'net': round(tax_debit_sums + tax_credit_sums,
                                             2),
                                'tax': round(
                                    (tax_debit_sums + tax_credit_sums) * (
                                            tax.amount / 100), 2),
                                'dynamic net': dynamic_total_net_sum,
                                'dynamic tax': dynamic_total_tax_sum,
                                'account': account.display_name,
                            })
                        else:
                            sale.append({
                                'name': tax.name,
                                'amount': tax.amount,
                                'net': round(tax_debit_sums + tax_credit_sums,
                                             2),
                                'tax': round(
                                    (tax_debit_sums + tax_credit_sums) * (
                                            tax.amount / 100), 2),
                                'account': account.display_name,
                            })
                    elif tax_id and tax.type_tax_use == 'purchase':
                        if comparison_number:
                            purchase.append({
                                'name': tax.name,
                                'amount': tax.amount,
                                'net': round(tax_debit_sums + tax_credit_sums,
                                             2),
                                'tax': round(
                                    (tax_debit_sums + tax_credit_sums) * (
                                            tax.amount / 100), 2),
                                'dynamic net': dynamic_total_net_sum,
                                'dynamic tax': dynamic_total_tax_sum,
                                'account': account.display_name,
                            })
                        else:
                            purchase.append({
                                'name': tax.name,
                                'amount': tax.amount,
                                'net': round(tax_debit_sums + tax_credit_sums,
                                             2),
                                'tax': round(
                                    (tax_debit_sums + tax_credit_sums) * (
                                            tax.amount / 100), 2),
                                'account': account.display_name,
                            })
        else:
            start_date = start_date_first
            end_date = end_date_first
            for tax in tax_ids:
                dynamic_total_tax_sum = {}
                dynamic_total_net_sum = {}
                if comparison_number:
                    if comparison_type == 'year':
                        start_date = start_date_first
                        end_date = end_date_first
                        for i in range(1, eval(comparison_number) + 1):
                            com_start_date = subtract(start_date,
                                                      years=i)
                            com_end_date = subtract(end_date, years=i)
                            tax_id = self.env[
                                'account.move.line'].search(
                                [('tax_ids', '=', tax.id),
                                 ('date', '>=', com_start_date),
                                 ('date', '<=', com_end_date),
                                 ('parent_state', 'in', option_domain)]).read(
                                ['debit', 'credit'])
                            tax_debit_sums = sum(
                                record['debit'] for record in tax_id)
                            tax_credit_sums = sum(
                                record['credit'] for record in tax_id)
                            dynamic_total_net_sum[
                                f"dynamic_total_net_sum{i}"] = tax_debit_sums + tax_credit_sums
                            dynamic_total_tax_sum[
                                f"dynamic_total_tax_sum{i}"] = \
                                dynamic_total_net_sum[
                                    f"dynamic_total_net_sum{i}"] * (
                                        tax.amount / 100)
                    elif comparison_type == 'month':
                        dynamic_date_num[
                            f"dynamic_date_num{0}"] = self.get_month_name(
                            start_date) + ' ' + str(start_date.year)
                        for i in range(1, eval(comparison_number) + 1):
                            com_start_date = subtract(start_date, months=i)
                            com_end_date = subtract(end_date, months=i)
                            tax_id = self.env[
                                'account.move.line'].search(
                                [('tax_ids', '=', tax.id),
                                 ('date', '>=', com_start_date),
                                 ('date', '<=', com_end_date),
                                 ('parent_state', 'in', option_domain)]).read(
                                ['debit', 'credit'])
                            tax_debit_sums = sum(
                                record['debit'] for record in tax_id)
                            tax_credit_sums = sum(
                                record['credit'] for record in tax_id)
                            dynamic_total_net_sum[
                                f"dynamic_total_net_sum{i}"] = tax_debit_sums + tax_credit_sums
                            dynamic_total_tax_sum[
                                f"dynamic_total_tax_sum{i}"] = \
                                dynamic_total_net_sum[
                                    f"dynamic_total_net_sum{i}"] * (
                                        tax.amount / 100)
                            dynamic_date_num[
                                f"dynamic_date_num{i}"] = self.get_month_name(
                                com_start_date) + ' ' + str(
                                com_start_date.year)
                    elif comparison_type == 'quarter':
                        dynamic_date_num[
                            f"dynamic_date_num{0}"] = 'Q' + ' ' + str(
                            get_quarter_number(start_date)) + ' ' + str(
                            start_date.year)
                        for i in range(1, eval(comparison_number) + 1):
                            com_start_date = subtract(start_date,
                                                      months=i * 3)
                            com_end_date = subtract(end_date,
                                                    months=i * 3)
                            tax_id = self.env[
                                'account.move.line'].search(
                                [('tax_ids', '=', tax.id),
                                 ('date', '>=', com_start_date),
                                 ('date', '<=', com_end_date),
                                 ('parent_state', 'in', option_domain)]).read(
                                ['debit', 'credit'])
                            tax_debit_sums = sum(
                                record['debit'] for record in tax_id)
                            tax_credit_sums = sum(
                                record['credit'] for record in tax_id)
                            dynamic_total_net_sum[
                                f"dynamic_total_net_sum{i}"] = tax_debit_sums + tax_credit_sums
                            dynamic_total_tax_sum[
                                f"dynamic_total_tax_sum{i}"] = \
                                dynamic_total_net_sum[
                                    f"dynamic_total_net_sum{i}"] * (
                                        tax.amount / 100)
                            dynamic_date_num[
                                f"dynamic_date_num{i}"] = 'Q' + ' ' + str(
                                get_quarter_number(
                                    com_start_date)) + ' ' + str(
                                com_start_date.year)
                tax_id = self.env['account.move.line'].search(
                    [('tax_ids', '=', tax.id),
                     ('parent_state', 'in', option_domain),
                     ('date', '>=', start_date_first),
                     ('date', '<=', end_date_first)]).read(['debit', 'credit'])
                tax_debit_sums = sum(record['debit'] for record in tax_id)
                tax_credit_sums = sum(record['credit'] for record in tax_id)
                if tax.type_tax_use == 'sale':
                    if comparison_number:
                        sale.append({
                            'name': tax.name,
                            'amount': tax.amount,
                            'net': round(tax_debit_sums + tax_credit_sums, 2),
                            'tax': round((tax_debit_sums + tax_credit_sums) * (
                                    tax.amount / 100), 2),
                            'dynamic net': dynamic_total_net_sum,
                            'dynamic tax': dynamic_total_tax_sum,
                        })
                    else:
                        sale.append({
                            'name': tax.name,
                            'amount': tax.amount,
                            'net': round(tax_debit_sums + tax_credit_sums, 2),
                            'tax': round((tax_debit_sums + tax_credit_sums) * (
                                    tax.amount / 100), 2),
                        })
                elif tax.type_tax_use == 'purchase':
                    if comparison_number:
                        purchase.append({
                            'name': tax.name,
                            'amount': tax.amount,
                            'net': round(tax_debit_sums + tax_credit_sums, 2),
                            'tax': round((tax_debit_sums + tax_credit_sums) * (
                                    tax.amount / 100), 2),
                            'dynamic net': dynamic_total_net_sum,
                            'dynamic tax': dynamic_total_tax_sum,
                        })
                    else:
                        purchase.append({
                            'name': tax.name,
                            'amount': tax.amount,
                            'net': round(tax_debit_sums + tax_credit_sums, 2),
                            'tax': round((tax_debit_sums + tax_credit_sums) * (
                                    tax.amount / 100), 2),
                        })
        for rec in sale + purchase:
            for field in ('net', 'tax', 'amount'):
                if field in rec and isinstance(rec[field], (int, float)):
                    rec[field] = "{:,.2f}".format(rec[field])
            if 'dynamic net' in rec:
                rec['dynamic net'] = {
                    k: "{:,.2f}".format(v) if isinstance(v, (int, float)) else v
                    for k, v in rec['dynamic net'].items()
                }
            if 'dynamic tax' in rec:
                rec['dynamic tax'] = {
                    k: "{:,.2f}".format(v) if isinstance(v, (int, float)) else v
                    for k, v in rec['dynamic tax'].items()
                }
        return {
            'dynamic_date_num': dynamic_date_num,
            'sale': sale,
            'purchase': purchase
        }

    @api.model
    def get_uae_vat_report(self, start_date, end_date, options):
        """Compute UAE FTA VAT Return data for the given period."""
        if options is None or options == {}:
            move_states = ['posted']
        elif 'draft' in options:
            move_states = ['posted', 'draft']
        else:
            move_states = ['posted']

        today = fields.Date.today()
        if start_date:
            date_from = datetime.strptime(start_date, "%Y-%m-%d").date()
        else:
            date_from = get_month(today)[0]
        if end_date:
            date_to = datetime.strptime(end_date, "%Y-%m-%d").date()
        else:
            date_to = get_month(today)[1]

        # Ordered list: (label, display_name, [aliases for matching])
        EMIRATE_LIST = [
            ('a', 'Abu Dhabi', ['Abu Dhabi', 'Abu Dhabi Emirate']),
            ('b', 'Dubai', ['Dubai']),
            ('c', 'Sharjah', ['Sharjah']),
            ('d', 'Ajman', ['Ajman']),
            ('e', 'Umm Al Quwain', ['Umm Al Quwain', 'Umm al-Quwain']),
            ('f', 'Ras Al-Khaima', ['Ras Al Khaimah', 'Ras Al-Khaima',
                                    'Ras al-Khaimah', 'Ras Al-Khaimah']),
            ('g', 'Fujairah', ['Fujairah']),
        ]

        def fmt(v):
            return "{:,.2f}".format(round(abs(v or 0.0), 2))

        # ---- Sales / Outputs ----
        sale_moves = self.env['account.move'].search([
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('state', 'in', move_states),
            ('invoice_date', '>=', date_from),
            ('invoice_date', '<=', date_to),
        ])

        std_by_emirate = {}
        zero_base = 0.0
        exempt_base = 0.0

        for move in sale_moves:
            sign = 1 if move.move_type == 'out_invoice' else -1
            emirate = 'Other'
            if move.partner_id and move.partner_id.state_id:
                emirate = move.partner_id.state_id.name

            move_has_std = False
            move_has_zero = False

            for line in move.line_ids:
                sale_taxes = [t for t in line.tax_ids if t.type_tax_use == 'sale']
                if sale_taxes and any(t.amount != 0 for t in sale_taxes):
                    if emirate not in std_by_emirate:
                        std_by_emirate[emirate] = {'base': 0.0, 'vat': 0.0}
                    std_by_emirate[emirate]['base'] += sign * (line.credit - line.debit)
                    move_has_std = True
                elif (line.tax_line_id and
                      line.tax_line_id.type_tax_use == 'sale' and
                      line.tax_line_id.amount != 0):
                    if emirate not in std_by_emirate:
                        std_by_emirate[emirate] = {'base': 0.0, 'vat': 0.0}
                    std_by_emirate[emirate]['vat'] += sign * (line.credit - line.debit)
                elif sale_taxes and all(t.amount == 0 for t in sale_taxes):
                    zero_base += sign * (line.credit - line.debit)
                    move_has_zero = True

            if not move_has_std and not move_has_zero:
                for line in move.line_ids:
                    if (not line.tax_ids and not line.tax_line_id and
                            line.account_id.account_type in ['income', 'income_other']):
                        exempt_base += sign * (line.credit - line.debit)

        std_base = sum(v['base'] for v in std_by_emirate.values())
        std_vat = sum(v['vat'] for v in std_by_emirate.values())
        total_sale_base = std_base + zero_base + exempt_base
        total_sale_vat = std_vat

        # ---- Purchases / Inputs ----
        purchase_moves = self.env['account.move'].search([
            ('move_type', 'in', ['in_invoice', 'in_refund']),
            ('state', 'in', move_states),
            ('invoice_date', '>=', date_from),
            ('invoice_date', '<=', date_to),
        ])

        std_purch_base = 0.0
        std_purch_vat = 0.0

        for move in purchase_moves:
            sign = 1 if move.move_type == 'in_invoice' else -1
            for line in move.line_ids:
                purch_taxes = [t for t in line.tax_ids if t.type_tax_use == 'purchase']
                if purch_taxes and any(t.amount != 0 for t in purch_taxes):
                    std_purch_base += sign * (line.debit - line.credit)
                elif (line.tax_line_id and
                      line.tax_line_id.type_tax_use == 'purchase' and
                      line.tax_line_id.amount != 0):
                    std_purch_vat += sign * (line.debit - line.credit)

        total_purch_base = std_purch_base
        total_purch_vat = std_purch_vat

        # ---- Net VAT ----
        vat_due = std_vat
        vat_recoverable = std_purch_vat
        net_vat = vat_due - vat_recoverable

        # Build always-7-emirate list with proper labels
        def emirate_val(field, aliases):
            for alias in aliases:
                if alias in std_by_emirate:
                    return std_by_emirate[alias][field]
            return 0.0

        emirates = []
        for label, display, aliases in EMIRATE_LIST:
            emirates.append({
                'label': label,
                'name': display,
                'base': fmt(emirate_val('base', aliases)),
                'vat': fmt(emirate_val('vat', aliases)),
            })

        return {
            # --- VAT on Sales (Base) ---
            'sale_base_total': fmt(total_sale_base),
            's1_base': fmt(std_base),
            's2_base': '0.00',
            's3_base': '0.00',
            's4_base': fmt(zero_base),
            's5_base': fmt(exempt_base),
            's6_base': '0.00',
            's7_base': '0.00',
            's8_base': '0.00',
            's9_base': fmt(total_sale_base),
            # --- VAT on Expenses (Base) ---
            'purch_base_total': fmt(total_purch_base),
            's10_base': fmt(std_purch_base),
            's11_base': '0.00',
            's12_base': '0.00',
            's13_base': fmt(total_purch_base),
            # --- VAT on Sales (Tax) ---
            'sale_vat_total': fmt(total_sale_vat),
            's1_vat': fmt(std_vat),
            's2_vat': '0.00',
            's3_vat': '0.00',
            's4_vat': '0.00',
            's5_vat': '0.00',
            's6_vat': '0.00',
            's7_vat': '0.00',
            's8_vat': '0.00',
            's9_vat': fmt(total_sale_vat),
            # --- VAT on Expenses (Tax) ---
            'purch_vat_total': fmt(total_purch_vat),
            's10_vat': fmt(std_purch_vat),
            's11_vat': '0.00',
            's12_vat': '0.00',
            's13_vat': fmt(total_purch_vat),
            # --- Emirates (always 7) ---
            'emirates': emirates,
            # --- Net VAT Due ---
            'net_vat_total': fmt(abs(net_vat)),
            's14_vat': fmt(vat_due),
            's15_vat': fmt(vat_recoverable),
            's16_vat': fmt(abs(net_vat)),
            's16_is_credit': net_vat < 0,
        }

    @api.model
    def get_month_name(self, date):
        """
        Retrieve the abbreviated name of the month for a given date.

        :param date: The date for which to retrieve the month's abbreviated
                     name.
        :type date: datetime.date
        :return: Abbreviated name of the month (e.g., 'Jan', 'Feb', ..., 'Dec').
        :rtype: str
        """
        month_names = calendar.month_abbr
        return month_names[date.month]

    @api.model
    def get_xlsx_report(self, data, response, report_name, report_action):
        """
        Generate an XLSX report based on provided data and response stream.

        Generates an Excel workbook with specified report format, including
        subheadings,column headers, and row data for the given financial report
        data.

        :param str data: JSON-encoded data for the report.
        :param response: Response object to stream the generated report.
        :param str report_name: Name of the financial report.
        """
        data = json.loads(data)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # UAE VAT Return XLSX
        if data.get('uae_vat_mode') and data.get('uae_data'):
            uae = data['uae_data']
            sheet = workbook.add_worksheet()
            sheet.set_column(0, 0, 60)
            sheet.set_column(1, 1, 20)
            hdr_fmt = workbook.add_format({
                'bold': True, 'font_color': 'white',
                'bg_color': '#00A0AD', 'border': 1})
            total_fmt = workbook.add_format({
                'bold': True, 'bg_color': '#DFDFDF', 'border': 1})
            row_fmt = workbook.add_format({'border': 1})
            sub_fmt = workbook.add_format({'border': 1, 'indent': 2})
            amt_fmt = workbook.add_format({'border': 1, 'align': 'right'})
            amt_sub = workbook.add_format({'border': 1, 'align': 'right', 'indent': 1})

            def w(r, label, amount, lf=row_fmt, af=amt_fmt):
                sheet.write(r, 0, label, lf)
                sheet.write(r, 1, amount + ' AED', af)
                return r + 1

            r = 0
            sheet.write(r, 0, report_name, hdr_fmt)
            sheet.write(r, 1, '', hdr_fmt)
            r += 2
            # S1: Sales Base
            r = w(r, 'VAT on Sales and all other Outputs (Base)',
                  uae['sale_base_total'], hdr_fmt, hdr_fmt)
            r = w(r, '1. Standard Rated supplies (Base)', uae['s1_base'])
            for em in uae['emirates']:
                r = w(r, '   ' + em['label'] + '. ' + em['name'], em['base'], sub_fmt, amt_sub)
            r = w(r, '   Sub Total', uae['s1_base'], sub_fmt, amt_sub)
            r = w(r, '2. Tax Refunds provided to Tourists under the Tax Refunds for Tourists Scheme', uae['s2_base'])
            r = w(r, '3. Supplies subject to reverse charge provisions', uae['s3_base'])
            r = w(r, '4. Zero rated supplies', uae['s4_base'])
            r = w(r, '5. Exempt supplies', uae['s5_base'])
            r = w(r, '6. Out of scope', uae['s6_base'])
            r = w(r, '7. Goods imported into the UAE', uae['s7_base'])
            r = w(r, '8. Adjustments to goods imported into the UAE', uae['s8_base'])
            r = w(r, '9. Total', uae['s9_base'], total_fmt, total_fmt)
            r += 1
            # S2: Expenses Base
            r = w(r, 'VAT on Expenses and all other Inputs (Base)',
                  uae['purch_base_total'], hdr_fmt, hdr_fmt)
            r = w(r, '10. Standard rated expenses', uae['s10_base'])
            r = w(r, '11. Supplies subject to the reverse charge provisions', uae['s11_base'])
            r = w(r, '12. Out of scope', uae['s12_base'])
            r = w(r, '13. Totals', uae['s13_base'], total_fmt, total_fmt)
            r += 1
            # S3: Sales Tax
            r = w(r, 'VAT on Sales and all other Outputs (Tax)',
                  uae['sale_vat_total'], hdr_fmt, hdr_fmt)
            r = w(r, '1. Standard Rated supplies (Tax)', uae['s1_vat'])
            for em in uae['emirates']:
                r = w(r, '   ' + em['label'] + '. ' + em['name'], em['vat'], sub_fmt, amt_sub)
            r = w(r, '   Sub Total', uae['s1_vat'], sub_fmt, amt_sub)
            r = w(r, '2. Tax Refunds provided to Tourists under the Tax Refunds for Tourists Scheme', uae['s2_vat'])
            r = w(r, '3. Supplies subject to reverse charge provisions', uae['s3_vat'])
            r = w(r, '4. Zero rated supplies', uae['s4_vat'])
            r = w(r, '5. Exempt supplies', uae['s5_vat'])
            r = w(r, '6. Out of scope', uae['s6_vat'])
            r = w(r, '7. Goods imported into the UAE', uae['s7_vat'])
            r = w(r, '8. Adjustments to goods imported into the UAE', uae['s8_vat'])
            r = w(r, '9. Total', uae['s9_vat'], total_fmt, total_fmt)
            r += 1
            # S4: Expenses Tax
            r = w(r, 'VAT on Expenses and all other Inputs (Tax)',
                  uae['purch_vat_total'], hdr_fmt, hdr_fmt)
            r = w(r, '10. Standard rated expenses', uae['s10_vat'])
            r = w(r, '11. Supplies subject to the reverse charge provisions', uae['s11_vat'])
            r = w(r, '12. Out of scope', uae['s12_vat'])
            r = w(r, '13. Totals', uae['s13_vat'], total_fmt, total_fmt)
            r += 1
            # S5: Net VAT
            r = w(r, 'Net VAT Due', uae['net_vat_total'], hdr_fmt, hdr_fmt)
            r = w(r, '14. Total value of due tax for the period', uae['s14_vat'])
            r = w(r, '15. Total value of recoverable tax for the period', uae['s15_vat'])
            net_display = ('(' + uae['s16_vat'] + ')') if uae.get('s16_is_credit') else uae['s16_vat']
            r = w(r, '16. Net VAT due (or reclaimed) for the period',
                  net_display, total_fmt, total_fmt)
            workbook.close()
            output.seek(0)
            response.stream.write(output.read())
            output.close()
            return

        sheet = workbook.add_worksheet()
        sub_heading = workbook.add_format(
            {'align': 'center', 'bold': True, 'font_size': '10px',
             'border': 1,
             'border_color': 'black'})
        side_heading_sub = workbook.add_format(
            {'align': 'left', 'bold': True, 'font_size': '10px',
             'border': 1,
             'border_color': 'black'})
        side_heading_sub.set_indent(1)
        txt_name = workbook.add_format({'font_size': '10px', 'border': 1})
        txt_name.set_indent(2)
        sheet.set_column(0, 0, 30)
        sheet.set_column(1, 1, 20)
        sheet.set_column(2, 2, 15)
        sheet.set_column(3, 3, 15)
        col = 0
        sheet.write('A3:b4', report_name, sub_heading)
        sheet.write(5, col, '', sub_heading)
        i = 1
        for date_view in data['date_viewed']:
            sheet.merge_range(5, col + i, 5, col + i + 1, date_view,
                              sub_heading)
            i += 2
        j = 1
        prev_account = None
        prev_tax = None
        sheet.write(6, col, '', sub_heading)
        for date in data['date_viewed']:
            sheet.write(6, col + j, 'NET', sub_heading)
            sheet.write(6, col + j + 1, 'TAX', sub_heading)
            j += 1
        sheet.write(7, col, 'Sales', sub_heading)
        sheet.write(7, col + 1, ' ', sub_heading)
        sheet.write(7, col + 2, data['sale_total'], sub_heading)
        row = 8
        for sale in data['data']['sale']:
            if data['report_type']:
                if list(data['report_type'].keys())[0] == 'account':
                    if prev_account != sale['account']:
                        prev_account = sale['account']
                        sheet.write(row, col, sale['account'], txt_name)
                        sheet.write(row, col + 1, '', txt_name)
                        sheet.write(row, col + 2, '', txt_name)
                elif list(data['report_type'].keys())[0] == 'tax':
                    if prev_tax != sale['name']:
                        prev_tax = sale['name']
                        sheet.write(row, col, sale['name'] + '(' + str(
                            sale['amount']) + '%)', txt_name)
                        sheet.write(row, col + 1, '', txt_name)
                        sheet.write(row, col + 2, '', txt_name)
                row += 1
                if data['apply_comparison']:
                    if sale['dynamic net']:
                        periods = data['comparison_number_range']
                        for num in periods:
                            if sale['dynamic net'][
                                'dynamic_total_net_sum' + str(num)]:
                                sheet.write(row, col + j, sale['dynamic net'][
                                    'dynamic_total_net_sum' + str(num)],
                                            txt_name)
                            if sale['dynamic tax'][
                                'dynamic_total_tax_sum' + str(num)]:
                                sheet.write(row, col, sale['dynamic tax'][
                                    'dynamic_total_tax_sum' + str(num)],
                                            txt_name)
                            j += 1
                j = 0
                sheet.write(row, col + j, sale['name'], txt_name)
                sheet.write(row, col + j + 1, sale['net'], txt_name)
                sheet.write(row, col + j + 2, sale['tax'], txt_name)
            else:
                j = 0
                sheet.write(row, col + j, sale['name'], txt_name)
                sheet.write(row, col + j + 1, sale['net'], txt_name)
                sheet.write(row, col + j + 2, sale['tax'], txt_name)
                row += 1
        row += 1
        sheet.write(row, col, 'Purchase', sub_heading)
        sheet.write(row, col + 1, ' ', sub_heading)
        sheet.write(row, col + 2, data['purchase_total'], sub_heading)
        row += 1
        for purchase in data['data']['purchase']:
            if data['report_type']:
                if list(data['report_type'].keys())[0] == 'account':
                    if prev_account != purchase['account']:
                        prev_account = purchase['account']
                        sheet.write(row, col, purchase['account'], txt_name)
                        sheet.write(row, col + 1, '', txt_name)
                        sheet.write(row, col + 2, '', txt_name)
                elif list(data['report_type'].keys())[0] == 'tax':
                    if prev_tax != purchase['name']:
                        prev_tax = purchase['name']
                        sheet.write(row, col, purchase['name'] + '(' + str(
                            purchase['amount']) + '%)', txt_name)
                        sheet.write(row, col + 1, '', txt_name)
                        sheet.write(row, col + 2, '', txt_name)
                row += 1
                if data['apply_comparison']:
                    if purchase['dynamic net']:
                        periods = data['comparison_number_range']
                        for num in periods:
                            if purchase['dynamic net'][
                                'dynamic_total_net_sum' + str(num)]:
                                sheet.write(row, col + j,
                                            purchase['dynamic net'][
                                                'dynamic_total_net_sum' + str(
                                                    num)],
                                            txt_name)
                            if purchase['dynamic tax'][
                                'dynamic_total_tax_sum' + str(num)]:
                                sheet.write(row, col, purchase['dynamic tax'][
                                    'dynamic_total_tax_sum' + str(num)],
                                            txt_name)
                            j += 1
                j = 0
                sheet.write(row, col + j, purchase['name'], txt_name)
                sheet.write(row, col + j + 1, purchase['net'], txt_name)
                sheet.write(row, col + j + 2, purchase['tax'], txt_name)
            else:
                j = 0
                sheet.write(row, col + j, purchase['name'], txt_name)
                sheet.write(row, col + j + 1, purchase['net'], txt_name)
                sheet.write(row, col + j + 2, purchase['tax'], txt_name)
                row += 1
        row += 1
        sheet.write(row, col, 'Purchase', sub_heading)
        sheet.write(row, col + 1, ' ', sub_heading)
        sheet.write(row, col + 2, data['purchase_total'], sub_heading)
        row += 1
        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
