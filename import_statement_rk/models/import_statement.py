# -*- coding: utf-8 -*-

import base64
import io
from datetime import datetime
import openpyxl

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ImportStatementRK(models.TransientModel):
    _name = 'import.statement.rk'
    _description = 'Import Bank Statement RK'

    file = fields.Binary(string="XLSX File", required=True)
    file_name = fields.Char(string="File Name")
    journal_id = fields.Many2one(
        'account.journal',
        string="Bank Journal",
        required=True,
        domain=[('type', '=', 'bank')]
    )

    def action_import(self):
        self.ensure_one()

        if not self.file:
            raise UserError(_("Please upload a file."))

        if not self.file_name.endswith('.xlsx'):
            raise UserError(_("Only XLSX files are supported."))

        file_data = base64.b64decode(self.file)
        workbook = openpyxl.load_workbook(io.BytesIO(file_data))
        sheet = workbook.active

        statement_lines = []
        first_date = None

        for row_index, row in enumerate(sheet.iter_rows(values_only=True)):
            if row_index == 0:
                continue
            if not row or not row[0]:
                continue

            date = row[0]
            label = row[1]
            partner_name = row[2]
            amount = row[3]

            if not first_date:
                first_date = date

            partner = False
            if partner_name:
                partner = self.env['res.partner'].search(
                    [('name', '=', partner_name)], limit=1
                )

            line_vals = {
                'date': date,
                'payment_ref': label,
                'partner_id': partner.id if partner else False,
                'amount': amount,
                'journal_id': self.journal_id.id,
            }

            statement_lines.append((0, 0, line_vals))

        if not statement_lines:
            raise UserError(_("No valid rows found in file."))

        statement_vals = {
            'name': 'Import %s' % datetime.today().date(),
            'journal_id': self.journal_id.id,
            'date': first_date or fields.Date.today(),
            'line_ids': statement_lines,
        }

        statement = self.env['account.bank.statement'].create(statement_vals)

        # Force correct journal
        statement.journal_id = self.journal_id.id

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement',
            'view_mode': 'form',
            'res_id': statement.id,
        }
