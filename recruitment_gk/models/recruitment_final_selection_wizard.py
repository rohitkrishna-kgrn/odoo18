from odoo import models, fields, api, _
from odoo.exceptions import UserError


class RecruitmentFinalSelectionWizard(models.TransientModel):
    _name = 'recruitment.final.selection.wizard'
    _description = 'Final Candidate Selection Wizard'

    request_id = fields.Many2one('recruitment.request', required=True, readonly=True)
    num_vacancies = fields.Integer(related='request_id.num_vacancies', string='Vacancies', readonly=True)
    candidate_ids = fields.Many2many('recruitment.candidate', string='Selected Candidates')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        request_id = self.env.context.get('default_request_id')
        if request_id:
            request = self.env['recruitment.request'].browse(request_id)
            candidates = request.candidate_ids.filtered(lambda c: c.state == 'selected')
            res['candidate_ids'] = [(6, 0, candidates.ids)]
        return res

    def action_mark_selected(self):
        self.ensure_one()
        self.request_id.state = 'selected'
        return {'type': 'ir.actions.act_window_close'}
