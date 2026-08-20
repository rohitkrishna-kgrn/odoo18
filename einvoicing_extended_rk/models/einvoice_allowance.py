# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from . import einvoice_lookups as lk


class EinvoiceAllowance(models.Model):
    """A document-level or line-level allowance (discount) or charge.

    Line allowances come off the line's ``LineExtensionAmount``; document
    allowances then adjust the taxable base per VAT category, which is why a
    document discount also moves the VAT. The platform recomputes all of it —
    only the amounts here have to be right.
    """
    _name = 'einvoice.allowance'
    _description = 'eInvoice Allowance / Charge'
    _order = 'move_id, move_line_id, sequence, id'

    sequence = fields.Integer(default=10)
    move_id = fields.Many2one(
        'account.move', string='Invoice', ondelete='cascade', index=True)
    move_line_id = fields.Many2one(
        'account.move.line', string='Invoice Line', ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', related='move_id.company_id', store=True)
    currency_id = fields.Many2one('res.currency', related='move_id.currency_id')

    charge_indicator = fields.Selection(
        [('false', 'Allowance (discount)'), ('true', 'Charge')],
        string='Type', default='false', required=True,
        help='Sent as chargeIndicator: "false" reduces the amount, "true" adds to it.',
    )
    reason_code = fields.Selection(
        lk.ALLOWANCE_REASON_CODES, string='Reason Code',
        help='UNTDID 5189 (allowance) / 7161 (charge) code.',
    )
    reason = fields.Char(string='Reason')
    percent = fields.Float(string='Percentage %', digits=(16, 4))
    base_amount = fields.Monetary(string='Base Amount')
    amount = fields.Monetary(string='Amount', required=True)
    vat_category = fields.Selection(
        lk.VAT_CATEGORY_CODES, string='VAT Category', default='S')
    vat_rate = fields.Float(string='VAT Rate %', default=5.0, digits=(16, 4))

    @api.constrains('move_id', 'move_line_id')
    def _check_owner(self):
        for rec in self:
            if not rec.move_id and not rec.move_line_id:
                raise ValidationError(_(
                    'An allowance or charge must belong to an invoice or an invoice line.'))

    @api.onchange('percent', 'base_amount')
    def _onchange_percent(self):
        """Derive the amount when a percentage of a base is given."""
        for rec in self:
            if rec.percent and rec.base_amount:
                rec.amount = rec.base_amount * rec.percent / 100.0

    def _einv_payload(self):
        """The allowances[] entry for this record."""
        self.ensure_one()
        vals = {
            'chargeIndicator': self.charge_indicator,
            'amount': round(self.amount, 2),
        }
        if self.reason_code:
            vals['reasonCode'] = self.reason_code
        if self.reason:
            vals['reason'] = self.reason
        if self.percent:
            vals['percent'] = round(self.percent, 4)
        if self.base_amount:
            vals['baseAmount'] = round(self.base_amount, 2)
        if self.vat_category:
            vals['vatCategory'] = self.vat_category
            if self.vat_category in lk.VAT_TAXED_CATEGORIES:
                vals['vatRate'] = self.vat_rate
        return vals

    @api.model
    def _einv_from_payload(self, data, move=None, line=None):
        """Build values for an allowance received on an inbound AP document."""
        charge = str(data.get('chargeIndicator', 'false')).lower()
        return {
            'move_id': move.id if move else False,
            'move_line_id': line.id if line else False,
            'charge_indicator': 'true' if charge in ('true', '1') else 'false',
            'reason_code': data.get('reasonCode') or False,
            'reason': data.get('reason') or False,
            'percent': float(data.get('percent') or 0.0),
            'base_amount': float(data.get('baseAmount') or 0.0),
            'amount': float(data.get('amount') or 0.0),
            'vat_category': data.get('vatCategory') or 'S',
            'vat_rate': float(data.get('vatRate') or 0.0),
        }
