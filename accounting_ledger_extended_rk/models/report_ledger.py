# -*- coding: utf-8 -*-
from odoo import api, models


class ReportGeneralLedger(models.AbstractModel):
    _name = 'report.accounting_ledger_extended_rk.report_general_ledger'
    _description = 'General Partner Ledger PDF'

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        svc = self.env['account.ledger.extended.rk']
        content = svc.get_general_ledger(
            data.get('partner_id'), data.get('date_from'),
            data.get('date_to'))
        return {
            'doc_ids': docids,
            'doc_model': 'res.partner',
            'docs': content,
            'company': self.env.company,
        }


class ReportOutstandingLedger(models.AbstractModel):
    _name = 'report.accounting_ledger_extended_rk.report_outstanding_ledger'
    _description = 'Outstanding Partner Ledger PDF'

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        svc = self.env['account.ledger.extended.rk']
        content = svc.get_outstanding_ledger(
            data.get('partner_id'), data.get('date_from'),
            data.get('date_to'))
        return {
            'doc_ids': docids,
            'doc_model': 'res.partner',
            'docs': content,
            'company': self.env.company,
        }
