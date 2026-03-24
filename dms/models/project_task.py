# models/project_task_inherit.py
from odoo import models, fields, api, _

class ProjectTask(models.Model):
    _inherit = "project.task"

    dms_access_group_ids = fields.Many2many(
        "dms.access.group",
        string="DMS Access Groups",
        help="Select DMS Access Groups for this task",
    )

    @api.onchange('dms_access_group_ids')
    def _onchange_dms_groups(self):
        admin_group = self.env['dms.access.group'].sudo().search([('name', '=', 'Admin')], limit=1)
        if not admin_group:
            raise ValueError(_("DMS group 'Admin' not found."))

        for task in self:
            if task.dms_folder_id:
                # Keep admin group + all selected groups
                new_group_ids = task.dms_access_group_ids.ids + [admin_group.id]
                # remove duplicates just in case
                new_group_ids = list(set(new_group_ids))
                task.dms_folder_id.group_ids = [(6, 0, new_group_ids)]
