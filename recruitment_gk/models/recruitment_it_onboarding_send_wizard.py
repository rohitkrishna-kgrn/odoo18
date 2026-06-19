from odoo import models, fields, api, _
from odoo.exceptions import UserError
from markupsafe import Markup, escape


class RecruitmentItOnboardingSendWizard(models.TransientModel):
    _name = 'recruitment.it.onboarding.send.wizard'
    _description = 'Send Onboarding Ready Notification Wizard'

    it_onboarding_id = fields.Many2one(
        'recruitment.it.onboarding', required=True, ondelete='cascade',
    )
    candidate_id = fields.Many2one(
        'recruitment.candidate',
        related='it_onboarding_id.candidate_id',
        readonly=True,
    )
    onboarding_date = fields.Date(
        related='it_onboarding_id.onboarding_date',
        readonly=True,
    )
    candidate_email = fields.Char('Candidate Email')
    reporting_manager_id = fields.Many2one(
        'hr.employee', 'Reporting Manager',
        related='it_onboarding_id.final_approval_id.reporting_manager_id',
        readonly=True,
    )
    hr_admin_ids = fields.Many2many(
        'res.users',
        'rec_it_send_wizard_hr_admin_rel',
        'wizard_id', 'user_id',
        string='HR Admins',
    )

    def action_send(self):
        self.ensure_one()
        onboarding = self.it_onboarding_id

        if not onboarding.all_tasks_done:
            raise UserError(_(
                'Please complete all IT onboarding tasks before sending the notification.'
            ))

        log_parts = []
        if self.candidate_email:
            log_parts.append('%s (candidate)' % self.candidate_email)
        mgr = self.reporting_manager_id
        if mgr:
            mgr_email = mgr.work_email or (mgr.user_id.email if mgr.user_id else '')
            if mgr_email:
                log_parts.append('%s (reporting manager: %s)' % (mgr_email, mgr.name))
        for user in self.hr_admin_ids:
            if user.email:
                log_parts.append('%s (HR)' % user.email)

        if not self.candidate_email and not self.reporting_manager_id and not self.hr_admin_ids:
            raise UserError(_('Please provide at least one email address to send the notification.'))

        # ── Candidate email (no hardware preference) ──────────────────────
        candidate_template = self.env.ref(
            'recruitment_gk.email_template_onboarding_ready', raise_if_not_found=False,
        )
        if candidate_template and self.candidate_email:
            attachment_ids = [(4, att.id) for att in onboarding.document_ids]
            candidate_template.send_mail(
                onboarding.id,
                force_send=True,
                raise_exception=False,
                email_values={
                    'email_to': self.candidate_email,
                    'recipient_ids': [],
                    'attachment_ids': attachment_ids,
                    'auto_delete': False,
                },
            )

        # ── Internal email to HR + Reporting Manager (includes hardware preference) ──
        internal_emails = []
        mgr = self.reporting_manager_id
        if mgr:
            mgr_email = mgr.work_email or (mgr.user_id.email if mgr.user_id else '')
            if mgr_email:
                internal_emails.append(mgr_email)
        for user in self.hr_admin_ids:
            if user.email and user.email not in internal_emails:
                internal_emails.append(user.email)

        internal_template = self.env.ref(
            'recruitment_gk.email_template_onboarding_ready_internal', raise_if_not_found=False,
        )
        if internal_template and internal_emails:
            internal_template.send_mail(
                onboarding.id,
                force_send=True,
                raise_exception=False,
                email_values={
                    'email_to': ','.join(internal_emails),
                    'recipient_ids': [],
                    'auto_delete': False,
                },
            )

        onboarding.state = 'completed'
        onboarding.notification_sent = True

        if onboarding.final_approval_id and onboarding.final_approval_id.state == 'it_notified':
            onboarding.final_approval_id.state = 'onboarding_ready'
            onboarding.final_approval_id.message_post(
                body=_('IT onboarding completed. Onboarding setup notification sent to candidate.'),
                subtype_xmlid='mail.mt_note',
            )

        onboarding.message_post(
            body=Markup(
                'Onboarding ready notification sent to: <b>%s</b>. '
                'Offer preparation process can begin.'
            ) % escape(', '.join(log_parts)),
            subtype_xmlid='mail.mt_note',
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Candidate'),
            'res_model': 'recruitment.candidate',
            'res_id': onboarding.candidate_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
