from odoo import models, fields, api, _
from odoo.exceptions import UserError


class RecruitmentCandidateSendHMWizard(models.TransientModel):
    _name = 'recruitment.candidate.send.hm.wizard'
    _description = 'Send Candidate to Hiring Manager Request'

    candidate_id = fields.Many2one(
        'recruitment.candidate', required=True, readonly=True, string='Candidate',
    )
    request_id = fields.Many2one(
        'recruitment.request',
        string='Hiring Manager Request',
        required=True,
        domain=[('state', 'not in', ('rejected', 'draft'))],
    )
    available_vacancies = fields.Integer(
        compute='_compute_available_vacancies',
        string='Available Vacancies',
    )

    @api.depends('request_id')
    def _compute_available_vacancies(self):
        for rec in self:
            if rec.request_id:
                req = rec.request_id
                selected = len(req.candidate_ids.filtered(lambda c: c.state == 'selected'))
                rec.available_vacancies = max(0, req.num_vacancies - selected)
            else:
                rec.available_vacancies = 0

    def action_send(self):
        self.ensure_one()
        request = self.request_id
        candidate = self.candidate_id

        selected_count = len(request.candidate_ids.filtered(lambda c: c.state == 'selected'))
        if selected_count >= request.num_vacancies:
            raise UserError(
                _('All vacancies for "%s" are already filled. Please choose a different request.') % request.name
            )

        candidate.write({'request_id': request.id})
        candidate.message_post(
            body=_('Candidate sent to fill vacancy in request: %s') % request.name,
            subtype_xmlid='mail.mt_note',
        )
        request.message_post(
            body=_('Candidate <b>%s</b> has been assigned to fill a vacancy in this request.') % candidate.name,
            subtype_xmlid='mail.mt_note',
        )

        new_selected = len(request.candidate_ids.filtered(lambda c: c.state == 'selected'))
        if new_selected >= request.num_vacancies:
            if request.state not in ('selected', 'rejected'):
                request.state = 'selected'

        return {'type': 'ir.actions.act_window_close'}
