# -*- coding: utf-8 -*-
import base64

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ledger_verified_by_accountant = fields.Boolean(
        string='Verified by Accountant', copy=False, tracking=True,
        help='Set when an accountant has verified this customer. The weekly '
             'outstanding email can only be enabled once this is ticked.')
    ledger_verified_by = fields.Many2one(
        'res.users', string='Verified By', readonly=True, copy=False)
    ledger_verified_date = fields.Datetime(
        string='Verified On', readonly=True, copy=False)
    ledger_email_enabled = fields.Boolean(
        string='Send Weekly Outstanding Email', default=False, copy=False,
        tracking=True,
        help='When enabled (and the customer is verified), an outstanding '
             'statement email with the open invoices attached is sent every '
             'Friday.')

    @api.constrains('ledger_email_enabled', 'ledger_verified_by_accountant')
    def _check_ledger_email_enabled(self):
        for partner in self:
            if partner.ledger_email_enabled and \
                    not partner.ledger_verified_by_accountant:
                raise ValidationError(_(
                    'You can only enable the weekly outstanding email after '
                    'the customer "%s" is verified by an accountant.')
                    % partner.display_name)

    def action_verify_for_ledger(self):
        for partner in self:
            partner.write({
                'ledger_verified_by_accountant': True,
                'ledger_verified_by': self.env.user.id,
                'ledger_verified_date': fields.Datetime.now(),
            })

    def action_unverify_for_ledger(self):
        self.write({
            'ledger_verified_by_accountant': False,
            'ledger_verified_by': False,
            'ledger_verified_date': False,
            'ledger_email_enabled': False,
        })

    # ------------------------------------------------------------------
    # Outstanding email
    # ------------------------------------------------------------------
    def _get_outstanding_moves(self):
        self.ensure_one()
        return self.env['account.move'].search([
            ('partner_id', '=', self.id),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial', 'in_payment')),
            ('amount_residual', '!=', 0),
        ], order='invoice_date asc')

    def _ledger_total_outstanding(self):
        self.ensure_one()
        total = 0.0
        for move in self._get_outstanding_moves():
            sign = -1 if move.move_type == 'out_refund' else 1
            total += move.amount_residual * sign
        return total

    def send_outstanding_email(self):
        """Send the outstanding statement email to a single partner with each
        open invoice attached as a PDF. Returns True when an email was sent."""
        self.ensure_one()
        moves = self._get_outstanding_moves()
        if not moves:
            return False
        template = self.env.ref(
            'accounting_ledger_extended_rk.mail_template_outstanding',
            raise_if_not_found=False)
        if not template:
            return False

        # Build a PDF attachment per outstanding invoice.
        attachments = self.env['ir.attachment']
        report = self.env.ref('account.account_invoices',
                              raise_if_not_found=False)
        if report:
            for move in moves:
                pdf_content, _dummy = self.env['ir.actions.report'] \
                    .sudo()._render_qweb_pdf(report.report_name, [move.id])
                attachments |= self.env['ir.attachment'].create({
                    'name': '%s.pdf' % (move.name or 'Invoice').replace(
                        '/', '_'),
                    'type': 'binary',
                    'datas': base64.b64encode(pdf_content),
                    'mimetype': 'application/pdf',
                    'res_model': 'res.partner',
                    'res_id': self.id,
                })
        template.attachment_ids = [(6, 0, attachments.ids)]
        template.send_mail(self.id, force_send=True)
        template.attachment_ids = [(5, 0, 0)]
        attachments.unlink()
        return True

    @api.model
    def _cron_send_outstanding_emails(self):
        """Weekly (Friday) job: email every verified + enabled customer their
        outstanding statement. The toggle being OFF skips the customer."""
        partners = self.search([
            ('ledger_email_enabled', '=', True),
            ('ledger_verified_by_accountant', '=', True),
        ])
        for partner in partners:
            if not partner.email:
                continue
            try:
                partner.send_outstanding_email()
            except Exception:
                self.env.cr.rollback()
                continue
            self.env.cr.commit()
        return True
