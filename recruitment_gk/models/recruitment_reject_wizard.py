from odoo import models, fields, _


class RecruitmentRejectWizard(models.TransientModel):
    _name = 'recruitment.reject.wizard'
    _description = 'Reject Candidate Wizard'

    candidate_id = fields.Many2one('recruitment.candidate', 'Candidate', required=True)
    interview_round_id = fields.Many2one('recruitment.interview.round', 'Interview Round')
    rejection_remark = fields.Text('Rejection Remarks', required=True)

    def action_confirm_reject(self):
        rejected_stage = self.env['recruitment.stage'].search(
            [('stage_type', '=', 'rejected')], limit=1
        )
        candidate = self.candidate_id
        candidate.state = 'rejected'
        candidate.rejection_remark = self.rejection_remark
        if rejected_stage:
            candidate.stage_id = rejected_stage
        if self.interview_round_id:
            self.interview_round_id.write({
                'state': 'rejected',
                'round_result': 'rejected',
                'rejection_remark': self.rejection_remark,
            })
        candidate.message_post(
            body=_('Candidate rejected. Reason: %s') % self.rejection_remark,
            subtype_xmlid='mail.mt_note',
        )

        # Move request to Rejected if all candidates on this request are rejected
        if candidate.request_id and candidate.request_id.state not in ('selected', 'rejected'):
            other_candidates = candidate.request_id.candidate_ids.filtered(
                lambda c: c.id != candidate.id and c.state not in ('rejected',)
            )
            if not other_candidates:
                candidate.request_id.state = 'rejected'

        # Determine recipients based on who rejected and at which stage
        req_model = self.env['recruitment.request']
        hr_admins = req_model._group_users('group_recruitment_hr_admin')
        specific_hm = candidate.request_id.user_id if candidate.request_id else self.env['res.users'].browse()
        prev_state = self.env.context.get('candidate_previous_state', '')

        if self.interview_round_id:
            # Rejected from an interview round → notify HR Admins + specific HM
            recipients = (hr_admins | specific_hm)
        elif prev_state == 'manager_review':
            # HM rejected at review stage → notify HR Admins only (req. 3)
            recipients = hr_admins
        else:
            # Final rejection after all rounds → notify specific HM (req. 5)
            recipients = specific_hm or hr_admins

        req_model._send_template_email(
            'email_template_candidate_rejected',
            candidate,
            extra_recipients=recipients,
        )

        return {'type': 'ir.actions.act_window_close'}
