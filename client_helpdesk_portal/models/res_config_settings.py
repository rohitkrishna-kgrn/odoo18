from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    helpdesk_admin_id = fields.Many2one(
        'res.users', string='Helpdesk Admin',
        config_parameter='client_helpdesk_portal.helpdesk_admin_user_id',
        default=lambda self: self.env.ref('base.user_admin').id,
        help='Receives tickets automatically when no handler is selected. '
             'Helpdesk Admins and Managers can manually reassign tickets to '
             'users with Select Access enabled in Helpdesk Portal Users '
             '(Managers limited to their own team).',
    )

    def set_values(self):
        super().set_values()
        group = self.env.ref(
            'client_helpdesk_portal.group_helpdesk_admin',
            raise_if_not_found=False,
        )
        if group and self.helpdesk_admin_id:
            group.sudo().write({'users': [(6, 0, [self.helpdesk_admin_id.id])]})
