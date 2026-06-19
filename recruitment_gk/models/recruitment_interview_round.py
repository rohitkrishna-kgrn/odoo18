import pytz
from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class RecruitmentInterviewRound(models.Model):
    _name = 'recruitment.interview.round'
    _description = 'Interview Round'
    _inherit = ['recruitment.gk.base', 'mail.thread', 'mail.activity.mixin']
    _order = 'round_order asc, id asc'

    name = fields.Char('Round Name', required=True)
    candidate_id = fields.Many2one(
        'recruitment.candidate', 'Candidate',
        required=True, ondelete='cascade',
    )
    stage_id = fields.Many2one('recruitment.stage', 'Stage', tracking=True)

    # ── round ordering ─────────────────────────────────────────────────────
    round_order = fields.Integer(
        'Round Order', default=1,
        help='Position in the interview sequence. Lower = earlier round.',
    )

    # ── scheduling ─────────────────────────────────────────────────────────
    interview_date = fields.Date(
        'Interview Date',
        default=fields.Date.today,
    )
    interview_time = fields.Float(
        'Interview Time (UAE)',
        default=lambda self: self._default_interview_time(),
        help='Time of the interview in UAE timezone (Asia/Dubai). Uses 12-hour AM/PM format.',
    )
    interview_time_uae = fields.Char(
        'Interview Time (UAE)',
        compute='_compute_interview_time_uae',
        help='Interview time formatted in UAE (Asia/Dubai) 12-hour AM/PM.',
    )
    interview_time_ist = fields.Char(
        'Interview Time (IST)',
        compute='_compute_interview_time_ist',
        help='Auto-calculated India Standard Time (UAE +1:30 h).',
    )
    interview_datetime = fields.Datetime(
        'Interview Date & Time',
        help='Stored in UTC; derived from Interview Date + Time (UAE).',
    )
    interviewer_id = fields.Many2one('res.users', 'Interviewer')
    invited_user_ids = fields.Many2many(
        'res.users',
        'recruitment_interview_round_invited_user_rel',
        'round_id', 'user_id',
        string='Invited Users',
        copy=False,
    )
    meeting_link = fields.Char('Meeting Link / URL')
    location_type = fields.Selection([
        ('online', 'Online'),
        ('offline', 'Offline'),
    ], 'Location')
    venue = fields.Char('Venue')
    interview_notes = fields.Text('Pre-Interview Notes')
    invitation_sent = fields.Boolean('Invitation Sent', default=False, copy=False)

    # ── reschedule tracking ────────────────────────────────────────────────
    is_rescheduled = fields.Boolean('Is Rescheduled', default=False, copy=False)
    original_round_id = fields.Many2one(
        'recruitment.interview.round', 'Original Round',
        copy=False, ondelete='set null',
    )

    # ── round result ───────────────────────────────────────────────────────
    round_result = fields.Selection([
        ('selected', 'Round Selected'),
        ('rejected', 'Round Rejected'),
    ], 'Round Result', copy=False)

    # ── feedback ───────────────────────────────────────────────────────────
    technical_rating = fields.Selection(
        [('5', 'Outstanding'), ('4', 'Very Good'), ('3', 'Good'),
         ('2', 'Average'), ('1', 'Below Normal')],
        'Technical Rating',
    )
    communication_rating = fields.Selection(
        [('5', 'Outstanding'), ('4', 'Very Good'), ('3', 'Good'),
         ('2', 'Average'), ('1', 'Below Normal')],
        'Communication Rating',
    )
    overall_rating = fields.Selection(
        [('5', 'Outstanding'), ('4', 'Very Good'), ('3', 'Good'),
         ('2', 'Average'), ('1', 'Below Normal')],
        'Overall Rating',
    )
    feedback_comments = fields.Text('Feedback Comments')
    recommendation = fields.Selection([
        ('strong_yes', 'Strong Yes'),
        ('yes', 'Yes'),
        ('maybe', 'Maybe'),
        ('no', 'No'),
        ('strong_no', 'Strong No'),
    ], 'Recommendation')
    rejection_remark = fields.Text('Rejection Remarks')

    # ── state: draft → scheduled → completed → selected → passed / rejected ──
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('selected', 'Selected'),
        ('passed', 'Passed'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], 'Status', default='draft', tracking=True)

    # ── sequential scheduling guard ────────────────────────────────────────
    can_schedule = fields.Boolean(
        compute='_compute_can_schedule',
        string='Can Schedule',
    )
    # ── last-round flag ────────────────────────────────────────────────────
    is_last_round = fields.Boolean(
        compute='_compute_is_last_round',
        string='Is Last Round',
    )

    # ── related (stored) ──────────────────────────────────────────────────
    candidate_name = fields.Char(related='candidate_id.name', store=True, string='Candidate')
    request_id = fields.Many2one(related='candidate_id.request_id', store=True)
    job_title = fields.Char(related='candidate_id.request_id.job_title', store=True)
    department_id = fields.Many2one(
        related='candidate_id.request_id.department_id', store=True,
    )

    # ── helpers ────────────────────────────────────────────────────────────

    def _default_interview_time(self):
        tz = pytz.timezone('Asia/Dubai')
        now = datetime.now(tz)
        return now.hour + now.minute / 60.0

    @api.depends('interview_time')
    def _compute_interview_time_uae(self):
        for rec in self:
            uae = rec.interview_time or 0.0
            total_min = round(uae * 60)
            h24 = (total_min // 60) % 24
            m = total_min % 60
            period = 'PM' if h24 >= 12 else 'AM'
            h12 = h24 % 12 or 12
            rec.interview_time_uae = '%d:%02d %s' % (h12, m, period)

    @api.depends('interview_time')
    def _compute_interview_time_ist(self):
        for rec in self:
            uae = rec.interview_time or 0.0
            # UAE is UTC+4, IST is UTC+5:30 → IST = UAE + 1.5 h
            ist = uae + 1.5
            if ist >= 24.0:
                ist -= 24.0
            total_min = round(ist * 60)
            h24 = (total_min // 60) % 24
            m = total_min % 60
            period = 'PM' if h24 >= 12 else 'AM'
            h12 = h24 % 12 or 12
            rec.interview_time_ist = '%d:%02d %s' % (h12, m, period)

    def _datetime_from_parts(self, date, time_float):
        """Convert interview_date + interview_time (UAE) to UTC datetime."""
        if not date:
            return False
        tz = pytz.timezone('Asia/Dubai')
        hours = int(time_float or 0)
        minutes = int(round(((time_float or 0) - hours) * 60))
        local_dt = tz.localize(datetime(
            date.year, date.month, date.day,
            min(hours, 23), min(minutes, 59),
        ))
        return local_dt.astimezone(pytz.utc).replace(tzinfo=None)

    @api.onchange('interview_date', 'interview_time')
    def _onchange_interview_date_time(self):
        self.interview_datetime = self._datetime_from_parts(
            self.interview_date, self.interview_time
        )

    @api.depends(
        'round_order', 'state',
        'candidate_id.interview_ids.round_order',
        'candidate_id.interview_ids.state',
    )
    def _compute_can_schedule(self):
        for rec in self:
            if rec.state != 'draft':
                rec.can_schedule = True
                continue
            prev_rounds = rec.candidate_id.interview_ids.filtered(
                lambda r: r.id != rec.id and r.round_order < rec.round_order
            )
            if not prev_rounds:
                rec.can_schedule = True
            else:
                incomplete = prev_rounds.filtered(
                    lambda r: r.state not in (
                        'completed', 'selected', 'passed', 'rejected', 'cancelled'
                    )
                )
                rec.can_schedule = not bool(incomplete)

    @api.depends(
        'round_order',
        'candidate_id.interview_ids.round_order',
        'candidate_id.interview_ids.state',
    )
    def _compute_is_last_round(self):
        for rec in self:
            higher = rec.candidate_id.interview_ids.filtered(
                lambda r: r.id != rec.id
                and r.round_order > rec.round_order
                and r.state != 'cancelled'
            )
            rec.is_last_round = not bool(higher)

    # ── email helper ───────────────────────────────────────────────────────

    def _send_template_email(self, template_xml_id, record, extra_recipients=None):
        self.env['recruitment.request']._send_template_email(
            template_xml_id, record, extra_recipients=extra_recipients
        )

    def _group_users(self, xml_id):
        return self.env['recruitment.request']._group_users(xml_id)

    def _check_hr_admin(self):
        if not (self.env.user.has_group('recruitment_gk.group_recruitment_hr_admin')
                or self.env.user.has_group('recruitment_gk.group_recruitment_management')):
            raise UserError(_('Only HR Admin can schedule or manage interview rounds.'))

    # ── actions ────────────────────────────────────────────────────────────

    def action_start(self):
        """Move from draft → scheduled (validates sequential order)."""
        self._check_hr_admin()
        for rec in self:
            if not rec.can_schedule:
                raise UserError(_(
                    'Previous interview round(s) must be completed before '
                    'scheduling this round: %s'
                ) % rec.name)
            rec.state = 'scheduled'

    def action_complete(self):
        self._check_hr_admin()
        self.write({'state': 'completed'})

    def action_round_selected(self):
        """Mark this round as Selected."""
        self.ensure_one()
        self._check_hr_admin()
        self.write({'state': 'selected', 'round_result': 'selected'})

    def action_send_interview_invitation(self):
        """Open the Send Invitation popup wizard."""
        self.ensure_one()
        self._check_hr_admin()
        if not self.interview_date:
            raise UserError(_('Please set the Interview Date before sending invitation.'))
        if not self.interviewer_id:
            raise UserError(_('Please set the Interviewer before sending invitation.'))
        if not self.location_type:
            raise UserError(_('Please set the Location type before sending invitation.'))
        if self.location_type == 'online' and not self.meeting_link:
            raise UserError(_('Please add a Meeting Link for online interviews.'))
        if self.location_type == 'offline' and not self.venue:
            raise UserError(_('Please add a Venue for offline interviews.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Interview Invitation'),
            'res_model': 'recruitment.send.invitation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_interview_round_id': self.id},
        }

    def action_reschedule(self):
        """Open wizard to collect reschedule reason before proceeding."""
        self.ensure_one()
        self._check_hr_admin()
        if not self.invitation_sent:
            raise UserError(_('Rescheduling is only allowed after an interview invitation has been sent.'))
        if self.state not in ('scheduled',):
            raise UserError(_('Only scheduled rounds can be rescheduled.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reschedule Interview'),
            'res_model': 'recruitment.reschedule.reason.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_interview_round_id': self.id},
        }

    def _do_reschedule(self, reason):
        """Cancel this round, create a rescheduled copy, and send cancellation emails."""
        self.ensure_one()
        invited = self.invited_user_ids
        interviewer_emails = [u.email for u in invited if u.email]
        candidate_email = self.candidate_id.email if self.candidate_id else ''

        # ── Email 1: to interviewer(s) ────────────────────────────────────
        if interviewer_emails:
            cancel_template = self.env.ref(
                'recruitment_gk.email_template_interview_cancelled',
                raise_if_not_found=False,
            )
            if cancel_template:
                cancel_template.send_mail(
                    self.id,
                    force_send=True,
                    raise_exception=False,
                    email_values={
                        'email_to': ','.join(interviewer_emails),
                        'recipient_ids': [],
                        'auto_delete': False,
                    },
                )

        # ── Email 2: to candidate ─────────────────────────────────────────
        if candidate_email:
            candidate_cancel_template = self.env.ref(
                'recruitment_gk.email_template_interview_cancelled_candidate',
                raise_if_not_found=False,
            )
            if candidate_cancel_template:
                candidate_cancel_template.send_mail(
                    self.id,
                    force_send=True,
                    raise_exception=False,
                    email_values={
                        'email_to': candidate_email,
                        'recipient_ids': [],
                        'auto_delete': False,
                    },
                )

        self.state = 'cancelled'
        self.message_post(
            body=_('Interview round cancelled and rescheduled. Reason: %s') % reason,
            subtype_xmlid='mail.mt_note',
        )

        new_round = self.env['recruitment.interview.round'].create({
            'name': self.name,
            'candidate_id': self.candidate_id.id,
            'stage_id': self.stage_id.id if self.stage_id else False,
            'round_order': self.round_order,
            'interview_date': self.interview_date,
            'interview_time': self.interview_time,
            'interview_datetime': self.interview_datetime,
            'interviewer_id': self.interviewer_id.id if self.interviewer_id else False,
            'meeting_link': self.meeting_link,
            'location_type': self.location_type,
            'venue': self.venue,
            'interview_notes': self.interview_notes,
            'is_rescheduled': True,
            'original_round_id': self.id,
            'state': 'scheduled',
        })
        new_round.message_post(
            body=_('Rescheduled from round: %s. Reason: %s') % (self.name, reason),
            subtype_xmlid='mail.mt_note',
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Rescheduled Interview Round'),
            'res_model': 'recruitment.interview.round',
            'res_id': new_round.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_pass_to_next(self):
        """Unlock the next pre-created draft round without changing the current round's state."""
        self.ensure_one()
        self._check_hr_admin()
        if not self.feedback_comments:
            raise UserError(_('Please add Feedback Comments before unlocking the next round.'))

        candidate = self.candidate_id

        # Find the next draft round (pre-created by the schedule wizard)
        next_round = candidate.interview_ids.filtered(
            lambda r: r.state == 'draft' and r.round_order > self.round_order
        ).sorted('round_order')[:1]

        hr_admins = self._group_users('group_recruitment_hr_admin')
        hiring_managers = self._group_users('group_recruitment_hiring_manager')
        self._send_template_email(
            'email_template_interview_passed', self,
            extra_recipients=(hr_admins | hiring_managers),
        )

        if next_round:
            if next_round.stage_id:
                candidate.stage_id = next_round.stage_id
            candidate.message_post(
                body=_('Next interview round unlocked: <b>%s</b>') % next_round.name,
                subtype_xmlid='mail.mt_note',
            )
            # Navigate to the next round so the Start Scheduling button is immediately visible
            return {
                'type': 'ir.actions.act_window',
                'name': next_round.name,
                'res_model': 'recruitment.interview.round',
                'res_id': next_round.id,
                'view_mode': 'form',
                'target': 'current',
            }
        else:
            final = self.env['recruitment.stage'].search(
                [('stage_type', '=', 'final_evaluation')], limit=1
            )
            if final:
                candidate.stage_id = final
            candidate.message_post(
                body=_('All interview rounds completed. Ready for final decision.'),
                subtype_xmlid='mail.mt_note',
            )

    def action_reject(self):
        """Open rejection remarks popup without pre-setting round_result (wizard sets it on confirm)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject Candidate'),
            'res_model': 'recruitment.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_candidate_id': self.candidate_id.id,
                'default_interview_round_id': self.id,
            },
        }
