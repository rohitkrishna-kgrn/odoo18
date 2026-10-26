from odoo import fields, models


class HrDmsRejectWizard(models.TransientModel):
    _name = 'hr.dms.reject.wizard'
    _description = 'Reject HR Document'

    document_ids = fields.Many2many('hr.dms.document', string='Documents')
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        self.document_ids.action_reject(self.reason)
        return {'type': 'ir.actions.act_window_close'}


class HrDmsReturnWizard(models.TransientModel):
    _name = 'hr.dms.return.wizard'
    _description = 'Return Personal Details for Correction'

    details_id = fields.Many2one('hr.dms.personal.details', required=True)
    mode = fields.Selection([('return', 'Return for Correction'), ('reopen', 'Reopen')],
                            default='return', required=True)
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        if self.mode == 'reopen':
            self.details_id.action_reopen(self.reason)
        else:
            self.details_id.action_return(self.reason)
        return {'type': 'ir.actions.act_window_close'}


class HrDmsDraftWizard(models.TransientModel):
    _name = 'hr.dms.draft.wizard'
    _description = 'Move HR Document to Draft for Correction'

    document_ids = fields.Many2many('hr.dms.document', string='Documents')
    reason = fields.Text(string='Correction needed', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.document_ids.action_move_to_draft(self.reason)
        return {'type': 'ir.actions.act_window_close'}
