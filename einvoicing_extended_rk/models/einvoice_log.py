# -*- coding: utf-8 -*-
import json

from odoo import _, api, fields, models


class EinvoiceLog(models.Model):
    """Audit trail of every exchange with the KGRN platform.

    Both directions land here: AR pushes we make, and AP documents pushed to
    us. The support process asks for ``requestId`` plus the timestamp, so both
    are stored verbatim alongside the raw bodies.
    """
    _name = 'einvoice.log'
    _description = 'eInvoice Transmission Log'
    _order = 'create_date desc, id desc'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, index=True)
    move_id = fields.Many2one(
        'account.move', string='Document', ondelete='set null', index=True)
    direction = fields.Selection(
        [('ar', 'AR — outbound'), ('ap', 'AP — inbound')],
        string='Direction', required=True, index=True)
    operation = fields.Selection(
        [('push', 'Invoice push'),
         ('whoami', 'Token check'),
         ('token', 'Token generation'),
         ('receive', 'Document received'),
         ('test', 'Webhook test')],
        string='Operation', required=True, default='push')
    endpoint = fields.Char(string='Endpoint')
    http_status = fields.Integer(string='HTTP Status')
    success = fields.Boolean(string='Success')
    request_id = fields.Char(string='Request ID', index=True,
                             help='Correlation id — quote it in a support ticket.')
    unique_invoice_number = fields.Char(string='Unique Invoice Number', index=True)
    record_id = fields.Char(string='Platform Record ID')
    instance_id = fields.Char(string='Peppol Instance ID', index=True)
    error_code = fields.Char(string='Error Code')
    message = fields.Text(string='Message')
    request_body = fields.Text(string='Request Body')
    response_body = fields.Text(string='Response Body')
    user_id = fields.Many2one(
        'res.users', string='User', default=lambda self: self.env.user)

    @api.depends('direction', 'operation', 'move_id', 'unique_invoice_number')
    def _compute_display_name(self):
        for log in self:
            label = dict(self._fields['operation'].selection).get(log.operation, '')
            ref = log.move_id.name or log.unique_invoice_number or ''
            log.display_name = ('%s %s' % (label, ref)).strip()

    @api.model
    def _log(self, vals):
        """Create a log entry, pretty-printing any dict bodies."""
        for key in ('request_body', 'response_body'):
            body = vals.get(key)
            if isinstance(body, (dict, list)):
                vals[key] = json.dumps(body, indent=2, default=str, ensure_ascii=False)
        return self.sudo().create(vals)

    def action_open_document(self):
        self.ensure_one()
        if not self.move_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Document'),
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }
