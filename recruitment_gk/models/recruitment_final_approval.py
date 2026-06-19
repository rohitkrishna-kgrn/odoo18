from odoo import models, fields, api, _
from odoo.exceptions import UserError
from markupsafe import Markup, escape


class RecruitmentFinalApproval(models.Model):
    _name = 'recruitment.final.approval'
    _description = 'Final Candidate Approval Details'
    _inherit = ['recruitment.gk.base', 'mail.thread', 'mail.activity.mixin']
    _rec_name = 'candidate_id'
    _order = 'id desc'

    candidate_id = fields.Many2one(
        'recruitment.candidate', 'Candidate',
        required=True, ondelete='cascade', tracking=True,
    )
    request_id = fields.Many2one(
        'recruitment.request',
        related='candidate_id.request_id',
        string='Recruitment Request',
        store=True,
    )
    job_title = fields.Char(related='candidate_id.job_title', store=True)
    department_id = fields.Many2one(
        'hr.department', related='candidate_id.department_id', store=True,
    )
    candidate_email = fields.Char(
        related='candidate_id.email', string='Personal Email', store=False,
    )

    onboarding_date = fields.Date('Onboarding / Joining Date', tracking=True)
    odoo_account = fields.Char('Odoo Account', tracking=True,
                               help='Odoo username or login to be set up for the new hire.')
    ctc_currency = fields.Selection([
        ('aed', 'AED – UAE Dirham'),
        ('inr', 'INR – Indian Rupees'),
    ], string='CTC Currency', default='aed', tracking=True)
    annual_ctc = fields.Float('Annual CTC', tracking=True)
    reporting_manager_id = fields.Many2one(
        'hr.employee', 'Reporting Manager', tracking=True,
    )
    joining_location = fields.Char('Joining Location', tracking=True)
    system_preference = fields.Selection([
        ('laptop', 'Laptop'),
        ('desktop', 'Desktop'),
    ], 'System Preference', tracking=True)
    approval_remarks = fields.Text('Approval Remarks')
    offer_notes = fields.Text('Offer Preparation Notes')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('it_notified', 'IT Notified'),
        ('onboarding_ready', 'Onboarding Ready'),
        ('closed', 'Closed'),
    ], 'Status', default='draft', tracking=True, copy=False)

    it_onboarding_id = fields.Many2one(
        'recruitment.it.onboarding', 'IT Onboarding Record',
        copy=False, readonly=True,
    )
    it_onboarding_state = fields.Selection(
        related='it_onboarding_id.state', string='IT Onboarding Status',
    )

    def action_notify_it_team(self):
        """Finalize onboarding date, create IT checklist record, and notify IT team."""
        self.ensure_one()
        if not self.onboarding_date:
            raise UserError(_('Please set the Onboarding / Joining Date before notifying the IT team.'))
        if self.state != 'draft':
            raise UserError(_('The IT team has already been notified for this record.'))

        # Create IT onboarding checklist if not yet created
        if not self.it_onboarding_id:
            it_rec = self.env['recruitment.it.onboarding'].create({
                'candidate_id': self.candidate_id.id,
                'final_approval_id': self.id,
            })
            self.it_onboarding_id = it_rec.id

        it_group = self.env.ref('recruitment_gk.group_recruitment_it_team', raise_if_not_found=False)
        if it_group and it_group.users:
            partners = it_group.users.mapped('partner_id').filtered('email')
            if partners:
                template = self.env.ref(
                    'recruitment_gk.email_template_it_onboarding_request',
                    raise_if_not_found=False,
                )
                if template:
                    template.send_mail(
                        self.id,
                        force_send=True,
                        raise_exception=False,
                        email_values={
                            'recipient_ids': [(4, p.id) for p in partners],
                            'email_to': '',
                            'auto_delete': False,
                        },
                    )

        self.state = 'it_notified'
        self.message_post(
            body=Markup(
                'IT team notified for onboarding of <b>%s</b>. '
                'Joining Date: <b>%s</b>'
            ) % (escape(self.candidate_id.name), escape(str(self.onboarding_date))),
            subtype_xmlid='mail.mt_note',
        )

    def action_view_it_onboarding(self):
        self.ensure_one()
        if not self.it_onboarding_id:
            raise UserError(_('No IT Onboarding record found. Please notify the IT team first.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('IT Onboarding Checklist'),
            'res_model': 'recruitment.it.onboarding',
            'res_id': self.it_onboarding_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_close(self):
        for rec in self:
            rec.state = 'closed'
