from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from . import tools


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    country_line_id = fields.Many2one('payroll.country.line', string='Country Payroll Line',
                                      copy=False, index=True, ondelete='set null', readonly=True)
    country_batch_id = fields.Many2one(related='country_line_id.batch_id', store=True, string='Country Payroll Batch',
                                       index=True)
    country_batch_state = fields.Selection(related='country_line_id.batch_id.state', store=True,
                                           string='Payroll Approval')
    payroll_month = fields.Selection(related='country_line_id.batch_id.month', store=True, string='Month')
    payroll_year = fields.Selection(related='country_line_id.batch_id.year', store=True, string='Year')
    payroll_currency_id = fields.Many2one(related='country_line_id.currency_id', string='Currency')
    payroll_net = fields.Monetary(related='country_line_id.net', string='Net Salary',
                                  currency_field='payroll_currency_id')
    payroll_gross = fields.Monetary(related='country_line_id.gross', string='Gross Salary',
                                    currency_field='payroll_currency_id')
    payroll_company_name = fields.Char(related='country_line_id.company_name', string='Company Name')

    def _is_my_approved_payslip(self):
        """Ownership + approval, checked on every self-service download."""
        self.ensure_one()
        slip = self.sudo()
        return (slip.employee_id.user_id == self.env.user
                and slip.country_batch_state == 'approved'
                and slip.state == 'done')

    def action_download_my_payslip(self):
        self.ensure_one()
        if not self._is_my_approved_payslip():
            raise AccessError(_("You can only download your own approved payslips."))
        return {
            'type': 'ir.actions.act_url',
            'url': '/payroll/my-payslip/%s/download' % self.id,
            'target': 'self',
        }

    # ------------------------------------------------------------ numbering
    # Payslip numbers (Payroll sequence salary.slip, gap-free) are given only when a payslip
    # is confirmed: Payroll's compute_sheet used to take one for every draft calculation,
    # so recalculated / deleted drafts left holes in the numbering.
    DRAFT_NUMBER = '/'

    def compute_sheet(self):
        unnumbered = self.filtered(lambda s: s.state in ('draft', 'verify') and not s.number)
        if unnumbered:
            unnumbered.write({'number': self.DRAFT_NUMBER})      # compute_sheet keeps an existing number
        res = super().compute_sheet()
        (self.filtered(lambda s: s.number == self.DRAFT_NUMBER)).write({'number': False})
        return res

    def _assign_payslip_number(self):
        # One continuous series for every company: the Payroll sequence is used whatever the
        # active company is (next_by_code would find nothing outside the sequence's company)
        todo = self.filtered(lambda s: not s.number or s.number == self.DRAFT_NUMBER)
        if not todo:
            return True
        seq = self.env['ir.sequence'].sudo().search([('code', '=', 'salary.slip')], order='company_id', limit=1)
        if not seq:
            raise UserError(_("The Payroll payslip sequence (salary.slip) is missing."))
        for slip in todo:
            slip.write({'number': seq._next()})
        return True

    def action_payslip_done(self):
        self.filtered(lambda s: s.state != 'done')._assign_payslip_number()
        return super().action_payslip_done()

    def unlink(self):
        locked = self.filtered(lambda s: s.country_line_id and s.country_batch_state in ('submitted', 'approved'))
        if locked and not self.env.context.get('payroll_country_system_write'):
            raise UserError(_("Payslip %s belongs to a submitted / approved country payroll batch.")
                            % ', '.join(locked.mapped(lambda s: s.number or s.name)))
        return super().unlink()
