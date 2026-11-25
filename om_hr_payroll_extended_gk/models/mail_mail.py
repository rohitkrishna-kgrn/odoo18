from odoo import api, fields, models


class MailMail(models.Model):
    _inherit = 'mail.mail'

    payroll_send_log_id = fields.Many2one('payroll.payslip.send.log', string='Payslip Send Log',
                                          ondelete='set null', index='btree_not_null')

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals:
            tracked = self.filtered('payroll_send_log_id')
            for mail in tracked:
                mail.payroll_send_log_id.line_id._sync_mail_state(mail)
        return res

    @api.model
    def _cron_payroll_sync_payslip_mail_state(self):
        """Safety net: re-read the mail state of queued payslip emails."""
        logs = self.env['payroll.payslip.send.log'].sudo().search([('status', '=', 'queued')])
        for log in logs:
            if log.mail_id:
                log.line_id._sync_mail_state(log.mail_id)
            else:
                log.write({'status': 'failed', 'failure_reason': 'Mail record was deleted before delivery was confirmed'})
                if log.line_id.send_log_ids.sorted('id', reverse=True)[:1] == log:
                    log.line_id._system_write({'email_status': 'failed',
                                               'email_error': log.failure_reason})
