from odoo import models, fields, api, _


class TaskTransfer(models.Model):
    _name = 'task.transfer'
    _description = 'Task Transfer Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'transfer_date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    task_id = fields.Many2one(
        'project.task', string='Task', required=True, readonly=True, ondelete='cascade'
    )
    project_id = fields.Many2one(
        'project.project', string='Project',
        related='task_id.project_id', store=True, readonly=True
    )
    from_user_ids = fields.Many2many(
        'res.users',
        'task_transfer_from_user_rel',
        'transfer_id', 'user_id',
        string='Removed Users',
        readonly=True,
    )
    to_user_ids = fields.Many2many(
        'res.users',
        'task_transfer_to_user_rel',
        'transfer_id', 'user_id',
        string='Added Users',
        readonly=True,
    )
    transferred_by = fields.Many2one(
        'res.users', string='Transferred By', readonly=True
    )
    transfer_date = fields.Datetime(string='Transfer Date', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('task.transfer') or 'New'
        return super().create(vals_list)
