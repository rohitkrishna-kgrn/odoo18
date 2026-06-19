from odoo import models, fields, api, _
from odoo.exceptions import UserError


class RecruitmentScheduleInterviewWizard(models.TransientModel):
    _name = 'recruitment.schedule.interview.wizard'
    _description = 'Schedule Interview Rounds Wizard'

    candidate_id = fields.Many2one('recruitment.candidate', required=True, readonly=True)
    round_line_ids = fields.One2many(
        'recruitment.schedule.interview.wizard.line',
        'wizard_id',
        string='Interview Rounds',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'round_line_ids' in fields_list:
            stages = self.env['recruitment.stage'].search(
                [('stage_type', '=', 'interview')],
                order='sequence asc',
            )
            seen = set()
            unique_stages = []
            for s in stages:
                if s.name not in seen:
                    seen.add(s.name)
                    unique_stages.append(s)
            lines = [
                (0, 0, {'name': s.name, 'stage_id': s.id, 'sequence': idx + 1})
                for idx, s in enumerate(unique_stages)
            ]
            res['round_line_ids'] = lines
        return res

    def action_confirm(self):
        self.ensure_one()
        if not (self.env.user.has_group('recruitment_gk.group_recruitment_hr_admin')
                or self.env.user.has_group('recruitment_gk.group_recruitment_management')):
            raise UserError(_('Only HR Admin can schedule interview rounds.'))
        if not self.round_line_ids:
            raise UserError(_('Please add at least one interview round.'))

        candidate = self.candidate_id
        first_stage = self.env['recruitment.stage'].search(
            [('stage_type', '=', 'interview')], order='sequence asc', limit=1
        )

        candidate.state = 'interview'
        if first_stage:
            candidate.stage_id = first_stage

        if candidate.request_id and candidate.request_id.state not in ('interview', 'selected', 'rejected'):
            candidate.request_id.state = 'interview'

        # Notify HR Admin + Hiring Manager that interview process is officially confirmed
        hr_admins = candidate._group_users('group_recruitment_hr_admin')
        hm = candidate.request_id.user_id if candidate.request_id else self.env['res.users'].browse()
        recipients = hr_admins | hm
        if recipients:
            candidate._send_template_email(
                'email_template_candidate_approved', candidate,
                extra_recipients=recipients,
            )

        first_round = None
        for line in self.round_line_ids.sorted('sequence'):
            round_rec = self.env['recruitment.interview.round'].create({
                'candidate_id': candidate.id,
                'stage_id': line.stage_id.id if line.stage_id else False,
                'name': line.name,
                'round_order': line.sequence,
                'state': 'draft',
            })
            if not first_round:
                first_round = round_rec

        # Open the first round form directly so HR Admin can schedule it
        if first_round:
            return {
                'type': 'ir.actions.act_window',
                'name': first_round.name,
                'res_model': 'recruitment.interview.round',
                'res_id': first_round.id,
                'view_mode': 'form',
                'target': 'current',
            }

        return {
            'type': 'ir.actions.act_window',
            'name': _('Interview Rounds'),
            'res_model': 'recruitment.interview.round',
            'view_mode': 'list,form',
            'domain': [('candidate_id', '=', candidate.id)],
            'context': {'default_candidate_id': candidate.id, 'create': False},
            'target': 'current',
        }


class RecruitmentScheduleInterviewWizardLine(models.TransientModel):
    _name = 'recruitment.schedule.interview.wizard.line'
    _description = 'Interview Round Configuration Line'
    _order = 'sequence asc'

    wizard_id = fields.Many2one(
        'recruitment.schedule.interview.wizard',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer('Order', default=10)
    name = fields.Char('Round Name', required=True)
    stage_id = fields.Many2one(
        'recruitment.stage',
        'Stage',
        domain=[('stage_type', '=', 'interview')],
    )
