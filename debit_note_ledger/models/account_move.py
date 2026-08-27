from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = 'account.move'

    is_debit_note = fields.Boolean(string='Is Debit Note', copy=False)
    debit_note_number = fields.Char(string='Debit Note Number', copy=False, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('debit_origin_id'):
                vals['is_debit_note'] = True
        records = super().create(vals_list)
        for move in records:
            if move.move_type == 'in_invoice' and move.is_debit_note and not move.debit_note_number:
                sequence = move._get_vendor_debit_note_sequence()
                move.debit_note_number = sequence.next_by_id()
        return records

    def _get_vendor_debit_note_fy_label(self):
        self.ensure_one()
        ref_date = self.invoice_date or self.date or fields.Date.context_today(self)
        start_year = ref_date.year if ref_date.month >= 4 else ref_date.year - 1
        return "%02d-%02d" % (start_year % 100, (start_year + 1) % 100)

    def _get_vendor_debit_note_sequence(self):
        self.ensure_one()
        fy_label = self._get_vendor_debit_note_fy_label()
        code = 'debit_note_ledger.vendor.%s' % fy_label
        Sequence = self.env['ir.sequence'].sudo()
        sequence = Sequence.search([
            ('code', '=', code),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not sequence:
            sequence = Sequence.create({
                'name': _('Vendor Debit Note %s', fy_label),
                'code': code,
                'prefix': 'DN/%s/' % fy_label,
                'padding': 4,
                'number_next': 1,
                'number_increment': 1,
                'company_id': self.company_id.id,
            })
        return sequence

    @api.constrains('ref', 'move_type', 'is_debit_note')
    def _check_vendor_debit_note_ref_required(self):
        for move in self:
            if move.move_type == 'in_invoice' and move.is_debit_note and not move.ref:
                raise ValidationError(_(
                    "Bill Reference is mandatory on Vendor Debit Notes. "
                    "Please enter a Bill Reference before saving."
                ))

    @api.constrains('sale_order_line_id', 'move_type', 'is_debit_note')
    def _check_vendor_debit_note_sale_order_required(self):
        for move in self:
            if move.move_type == 'in_invoice' and move.is_debit_note and not move.sale_order_line_id:
                raise ValidationError(_(
                    "Sale Order Line is mandatory on Vendor Debit Notes. "
                    "Please link this debit note before saving."
                ))
