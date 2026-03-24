from odoo import models, fields, api
from odoo.exceptions import UserError


class ProjectTransferWizard(models.TransientModel):
    _name = 'project.transfer.wizard'
    _description = 'Project Transfer Wizard'

    from_user_id = fields.Many2one(
        'res.users',
        string="From User",
        required=True
    )

    to_user_id = fields.Many2one(
        'res.users',
        string="To User",
        required=True
    )

    def _ensure_allowed_user(self):
        """Check if the current user belongs to the allowed group"""
        allowed_group = self.env.ref('project_transfer_rk.group_project_transfer_user', raise_if_not_found=False)
        if not allowed_group:
            raise UserError("Access configuration error: Project Transfer group not found.")
        if self.env.user.id not in allowed_group.users.ids:
            raise UserError("You do not have permission to access the Project Transfer.")

    def action_transfer_project(self):
        self.ensure_one()

        # Check access only here
        self._ensure_allowed_user()

        if self.from_user_id == self.to_user_id:
            raise UserError("From User and To User cannot be the same.")

        projects = self.env['project.project'].search([
            ('user_id', '=', self.from_user_id.id)
        ])

        if not projects:
            raise UserError("No projects found for selected From User.")

        projects.write({
            'user_id': self.to_user_id.id
        })

        return {
            'type': 'ir.actions.act_window_close'
        }