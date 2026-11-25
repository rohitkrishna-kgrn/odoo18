from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.payroll_logs import SEND_STATUS


class PayrollCountrySendWizard(models.TransientModel):
    """Send Selected: every employee of the approved batch, each with a Select tick."""
    _name = 'payroll.country.send.wizard'
    _description = 'Send Payslips - pick employees'

    batch_id = fields.Many2one('payroll.country.batch', required=True, readonly=True)
    line_ids = fields.One2many('payroll.country.send.wizard.line', 'wizard_id', string='Employees')
    selected_count = fields.Integer(compute='_compute_selected_count', string='Selected')

    @api.depends('line_ids.selected')
    def _compute_selected_count(self):
        for wiz in self:
            wiz.selected_count = len(wiz.line_ids.filtered('selected'))

    @api.model
    def _open_for(self, batch):
        batch._check_officer_rights()
        if batch.state != 'approved':
            raise UserError(_("Payslips can be sent only after approval."))
        lines = batch.sudo().line_ids.filtered(lambda l: l.state == 'approved').sorted(
            lambda l: (l.company_name or '', l.employee_name or ''))
        wizard = self.create({
            'batch_id': batch.id,
            'line_ids': [(0, 0, {'payroll_line_id': l.id, 'selected': l.send_selected}) for l in lines],
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'name': _("Send Payslips - %s") % batch.name,
        }

    def _reopen(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new', 'name': _("Send Payslips - %s") % self.batch_id.name}

    def action_select_unsent(self):
        """Tick everyone who has not received the payslip yet (sent / queued stay unticked)."""
        for row in self.line_ids:
            row.selected = row.email_status not in ('sent', 'queued')
        return self._reopen()

    def action_clear(self):
        self.line_ids.write({'selected': False})
        return self._reopen()

    def action_send(self):
        self.ensure_one()
        rows = self.line_ids.filtered('selected')
        if not rows:
            raise UserError(_("No employee is selected. Tick the employees to email. Nothing was sent."))
        # an explicitly ticked, already-sent payslip is sent again
        return rows.payroll_line_id.with_env(self.env)._send_payslips(allow_resend=True)


class PayrollCountrySendWizardLine(models.TransientModel):
    _name = 'payroll.country.send.wizard.line'
    _description = 'Send Payslips - employee'
    _order = 'company_name, employee_name'

    wizard_id = fields.Many2one('payroll.country.send.wizard', required=True, ondelete='cascade')
    payroll_line_id = fields.Many2one('payroll.country.line', required=True, readonly=True, ondelete='cascade')
    selected = fields.Boolean(string='Select')
    employee_name = fields.Char(related='payroll_line_id.employee_name', string='Employee')
    employee_code = fields.Char(related='payroll_line_id.employee_code', string='Employee ID')
    company_name = fields.Char(related='payroll_line_id.company_name', string='Company', store=True)
    work_email = fields.Char(related='payroll_line_id.work_email', string='Email')
    payslip_ref = fields.Char(related='payroll_line_id.payslip_ref', string='Payslip')
    email_status = fields.Selection(related='payroll_line_id.email_status', string='Email Status')
    email_sent_date = fields.Datetime(related='payroll_line_id.email_sent_date', string='Sent On')
