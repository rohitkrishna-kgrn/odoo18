from odoo import models, fields, api, _
from odoo.exceptions import UserError


class RecruitmentSendInvitationWizard(models.TransientModel):
    _name = 'recruitment.send.invitation.wizard'
    _description = 'Send Interview Invitation Wizard'

    interview_round_id = fields.Many2one(
        'recruitment.interview.round', 'Interview Round',
        required=True, ondelete='cascade', readonly=True,
    )
    interviewer_ids = fields.Many2many(
        'res.users',
        'recruitment_send_invitation_interviewer_rel',
        'wizard_id', 'user_id',
        string='Interviewers',
        domain=[('email', '!=', False)],
    )
    candidate_id = fields.Many2one(
        'recruitment.candidate', 'Candidate',
        compute='_compute_candidate_id',
        store=False,
    )
    candidate_email = fields.Char('Candidate Email')

    @api.depends('interview_round_id')
    def _compute_candidate_id(self):
        for rec in self:
            rec.candidate_id = rec.interview_round_id.candidate_id

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        round_id = self.env.context.get('default_interview_round_id')
        if round_id:
            rnd = self.env['recruitment.interview.round'].browse(round_id)
            if rnd.exists():
                res['interview_round_id'] = rnd.id
                if rnd.interviewer_id:
                    res['interviewer_ids'] = [(6, 0, [rnd.interviewer_id.id])]
                if rnd.candidate_id.email:
                    res['candidate_email'] = rnd.candidate_id.email
        return res

    def _send_mail(self, template_xml_id, rnd, email_to):
        template = self.env.ref(
            'recruitment_gk.%s' % template_xml_id, raise_if_not_found=False,
        )
        if not template:
            return
        template.send_mail(
            rnd.id,
            force_send=True,
            raise_exception=False,
            email_values={
                'email_to': email_to,
                'recipient_ids': [],
                'auto_delete': False,
            },
        )

    def action_send(self):
        self.ensure_one()
        if not (self.env.user.has_group('recruitment_gk.group_recruitment_hr_admin')
                or self.env.user.has_group('recruitment_gk.group_recruitment_management')):
            raise UserError(_('Only HR Admin can send interview invitations.'))

        rnd = self.interview_round_id
        interviewer_emails = [u.email for u in self.interviewer_ids if u.email]

        if not interviewer_emails:
            raise UserError(_('Please add at least one interviewer before sending.'))

        # ── Email 1: to interviewer(s) — "Dear [Interviewer name],"
        self._send_mail(
            'email_template_interview_invitation',
            rnd,
            ','.join(interviewer_emails),
        )

        # ── Email 2: to candidate — "Dear [Candidate name],"
        if self.candidate_email:
            self._send_mail(
                'email_template_interview_invitation_candidate',
                rnd,
                self.candidate_email,
            )

        rnd.invitation_sent = True
        rnd.invited_user_ids = [(6, 0, self.interviewer_ids.ids)]

        log_parts = list(interviewer_emails)
        if self.candidate_email:
            log_parts.append('%s (candidate)' % self.candidate_email)
        rnd.message_post(
            body=_('Interview invitation sent to: %s') % ', '.join(log_parts),
            subtype_xmlid='mail.mt_note',
        )

        return {'type': 'ir.actions.act_window_close'}
