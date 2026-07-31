from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    helpdesk_portal_user_ids = fields.One2many(
        'client.helpdesk.portal.user', 'user_id',
        string='Helpdesk Portal User Records',
        help='Reverse of client.helpdesk.portal.user.user_id — lets '
             'search-panel domains filter "Assigned To" down to users '
             'with Select Access enabled without needing a ticket record '
             'to compute against (unlike assignable_user_ids, which is '
             'ticket-bound and only usable on the form/kanban).',
    )
