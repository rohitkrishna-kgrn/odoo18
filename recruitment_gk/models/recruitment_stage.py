from odoo import models, fields


class RecruitmentStage(models.Model):
    _name = 'recruitment.stage'
    _description = 'Recruitment Pipeline Stage'
    _order = 'sequence, id'

    name = fields.Char('Stage Name', required=True, translate=True)
    sequence = fields.Integer('Sequence', default=10)
    fold = fields.Boolean('Folded in Kanban')
    stage_type = fields.Selection([
        ('draft', 'Draft'),
        ('new', 'New'),
        ('manager_review', 'Manager Review'),
        ('interview', 'Interview Round'),
        ('final_evaluation', 'Final Evaluation'),
        ('selected', 'Selected'),
        ('rejected', 'Rejected'),
    ], 'Stage Type', required=True, default='interview')
    round_number = fields.Integer('Round Number')
    active = fields.Boolean(default=True)
