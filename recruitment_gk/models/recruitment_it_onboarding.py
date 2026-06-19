from odoo import models, fields, api, _
from odoo.exceptions import UserError


class RecruitmentItOnboarding(models.Model):
    _name = 'recruitment.it.onboarding'
    _description = 'IT Onboarding Checklist'
    _inherit = ['recruitment.gk.base', 'mail.thread', 'mail.activity.mixin']
    _rec_name = 'candidate_id'
    _order = 'id desc'

    candidate_id = fields.Many2one(
        'recruitment.candidate', 'Candidate',
        required=True, ondelete='cascade', tracking=True,
    )
    final_approval_id = fields.Many2one(
        'recruitment.final.approval', 'Final Approval',
        ondelete='set null',
    )
    onboarding_date = fields.Date(
        related='final_approval_id.onboarding_date',
        string='Joining Date', store=True,
    )
    job_title = fields.Char(related='candidate_id.job_title', store=True)
    department_id = fields.Many2one(
        'hr.department', related='candidate_id.department_id', store=True,
    )
    personal_email = fields.Char(
        related='candidate_id.email', string='Personal Email', store=False,
    )
    joining_location = fields.Char(
        related='final_approval_id.joining_location',
        string='Joining Location', store=True,
    )

    # ── Step 1: Email Account ──────────────────────────────────────────────
    email_created = fields.Boolean('Email Account Created', tracking=True)
    email_editing = fields.Boolean('Email Account – Edit Mode')
    official_email = fields.Char('Official Email Address')
    official_email_password = fields.Char('Email Account Password')

    # ── Step 2: Odoo Account ───────────────────────────────────────────────
    odoo_account_created = fields.Boolean('Odoo Account Created', tracking=True)
    odoo_editing = fields.Boolean('Odoo Account – Edit Mode')
    odoo_username = fields.Char('Odoo Username')
    odoo_password = fields.Char('Odoo Account Password')
    odoo_link = fields.Char('Odoo Link', default='odoo.dubaiaudit.com')
    odoo_notes = fields.Char(
        'Odoo Notes',
        default='Odoo Invitation link will be shared in separate official mail id',
    )

    # ── Step 3: Wave Account ───────────────────────────────────────────────
    wave_account_created = fields.Boolean('Wave Account Created', tracking=True)
    wave_editing = fields.Boolean('Wave Account – Edit Mode')
    wave_username = fields.Char('Wave Username / ID')
    wave_password = fields.Char('Wave Account Password')

    # ── Step 4: Hardware & IT Assets ──────────────────────────────────────
    laptop_arranged = fields.Boolean('Hardware & IT Assets Arranged', tracking=True)
    hardware_editing = fields.Boolean('Hardware – Edit Mode')
    hardware_preference = fields.Selection([
        ('laptop', 'Laptop'),
        ('desktop', 'Desktop'),
    ], 'Preferred Device')
    laptop_notes = fields.Char('Asset Details / Notes')

    # ── Step 5: Documentation ─────────────────────────────────────────────
    setup_docs_shared = fields.Boolean('Documentation Shared', tracking=True)
    docs_editing = fields.Boolean('Documentation – Edit Mode')
    setup_docs_notes = fields.Char('Documentation Notes')
    document_ids = fields.Many2many(
        'ir.attachment',
        'recruitment_it_onboarding_doc_rel',
        'onboarding_id', 'attachment_id',
        string='Setup Documentation Files',
    )

    it_notes = fields.Text('Additional IT Notes')

    state = fields.Selection([
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ], 'Status', default='pending', tracking=True)

    all_tasks_done = fields.Boolean(
        compute='_compute_all_tasks_done', store=True,
        string='All Tasks Completed',
    )
    notification_sent = fields.Boolean(
        'Notification Sent', default=False, tracking=True,
    )
    is_it_team = fields.Boolean(compute='_compute_is_it_team')

    def _compute_is_it_team(self):
        is_it = self.env.user.has_group('recruitment_gk.group_recruitment_it_team')
        for rec in self:
            rec.is_it_team = is_it

    @api.depends(
        'email_created', 'odoo_account_created',
        'laptop_arranged', 'setup_docs_shared',
    )
    def _compute_all_tasks_done(self):
        for rec in self:
            rec.all_tasks_done = all([
                rec.email_created,
                rec.odoo_account_created,
                rec.laptop_arranged,
                rec.setup_docs_shared,
            ])

    # ── State transitions ──────────────────────────────────────────────────

    def action_mark_in_progress(self):
        for rec in self:
            if rec.state == 'pending':
                rec.state = 'in_progress'

    # ── Step 1: Email Account ──────────────────────────────────────────────

    def action_complete_email_account(self):
        self.ensure_one()
        if not self.official_email:
            raise UserError(_('Please enter the Official Email Address before completing this step.'))
        first_time = not self.email_created
        self.email_created = True
        self.email_editing = False
        if first_time:
            # Notify HR admins on first completion only
            hr_admin_group = self.env.ref(
                'recruitment_gk.group_recruitment_hr_admin', raise_if_not_found=False,
            )
            if hr_admin_group and hr_admin_group.users:
                template = self.env.ref(
                    'recruitment_gk.email_template_it_email_account_created', raise_if_not_found=False,
                )
                if template:
                    partners = hr_admin_group.users.mapped('partner_id').filtered('email')
                    if partners:
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
            self.message_post(
                body=_('Email account created: %s. HR team notified to create Odoo access.') % self.official_email,
                subtype_xmlid='mail.mt_note',
            )
        else:
            self.message_post(
                body=_('Email account details updated.'),
                subtype_xmlid='mail.mt_note',
            )

    def action_edit_email_account(self):
        self.ensure_one()
        self.email_editing = True

    @api.onchange('official_email')
    def _onchange_official_email(self):
        if self.official_email and not self.odoo_username:
            self.odoo_username = self.official_email

    # ── Step 2: Odoo Account ──────────────────────────────────────────────

    def action_complete_odoo_account(self):
        self.ensure_one()
        if not self.odoo_username:
            raise UserError(_('Please enter the Odoo Username before completing this step.'))
        first_time = not self.odoo_account_created
        self.odoo_account_created = True
        self.odoo_editing = False
        msg = _('Odoo account created. Username: %s') % self.odoo_username if first_time \
            else _('Odoo account details updated.')
        self.message_post(body=msg, subtype_xmlid='mail.mt_note')

    def action_edit_odoo_account(self):
        self.ensure_one()
        self.odoo_editing = True

    # ── Step 3: Wave Account ──────────────────────────────────────────────

    def action_complete_wave_account(self):
        self.ensure_one()
        first_time = not self.wave_account_created
        self.wave_account_created = True
        self.wave_editing = False
        msg = _('Wave account created. Username: %s') % self.wave_username if first_time \
            else _('Wave account details updated.')
        self.message_post(body=msg, subtype_xmlid='mail.mt_note')

    def action_edit_wave_account(self):
        self.ensure_one()
        self.wave_editing = True

    # ── Step 4: Hardware & IT Assets ─────────────────────────────────────

    def action_complete_hardware(self):
        self.ensure_one()
        first_time = not self.laptop_arranged
        self.laptop_arranged = True
        self.hardware_editing = False
        if first_time:
            notes_part = (' – %s' % self.laptop_notes) if self.laptop_notes else ''
            self.message_post(
                body=_('Hardware & IT Assets arranged%s.') % notes_part,
                subtype_xmlid='mail.mt_note',
            )
        else:
            self.message_post(
                body=_('Hardware & IT Assets details updated.'),
                subtype_xmlid='mail.mt_note',
            )

    def action_edit_hardware(self):
        self.ensure_one()
        self.hardware_editing = True

    # ── Step 5: Documentation ─────────────────────────────────────────────

    def action_complete_documentation(self):
        self.ensure_one()
        if not self.document_ids:
            raise UserError(_('Please upload at least one documentation file before completing this step.'))
        first_time = not self.setup_docs_shared
        self.setup_docs_shared = True
        self.docs_editing = False
        if first_time:
            self.message_post(
                body=_('Setup documentation completed. %d file(s) uploaded.') % len(self.document_ids),
                subtype_xmlid='mail.mt_note',
            )
        else:
            self.message_post(
                body=_('Documentation details updated.'),
                subtype_xmlid='mail.mt_note',
            )

    def action_edit_documentation(self):
        self.ensure_one()
        self.docs_editing = True

    # ── Send onboarding ready notification ────────────────────────────────

    def action_send_onboarding_ready(self):
        """Open wizard to confirm recipients and send onboarding ready notification."""
        self.ensure_one()
        if not self.all_tasks_done:
            raise UserError(_(
                'Please complete all IT onboarding tasks before sending the notification.'
            ))

        hr_admin_group = self.env.ref(
            'recruitment_gk.group_recruitment_hr_admin', raise_if_not_found=False,
        )
        hr_users = hr_admin_group.users if hr_admin_group else self.env['res.users']

        wizard = self.env['recruitment.it.onboarding.send.wizard'].create({
            'it_onboarding_id': self.id,
            'candidate_email': self.personal_email or '',
            'hr_admin_ids': [(6, 0, hr_users.ids)],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Onboarding Ready Notification'),
            'res_model': 'recruitment.it.onboarding.send.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
