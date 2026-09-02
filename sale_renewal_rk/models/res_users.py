# models/res_users.py
from odoo import models, fields


class ResUsers(models.Model):
    _inherit = 'res.users'

    sales_team = fields.Boolean(
        string="Sales Team",
        help="Marks this user as a member of the sales team. It does two things:\n\n"
             "- lets them create quotations in the 'New' stage;\n"
             "- lets them open and edit every quotation, including ones where "
             "somebody else is the salesperson, even on the 'User: Own Documents "
             "Only' Sales access level.\n\n"
             "Untick it and the user falls back to whatever their Sales access "
             "level under Access Rights allows.")

    def _get_invalidation_fields(self):
        """Toggling 'Sales Team' has to bust the record-rule cache.

        The domain of the 'Sales Team members work on all orders' rule reads
        user.sales_team, and ir.rule._compute_domain is ormcache'd per uid. Without
        this the checkbox would appear to do nothing until the next server restart.
        """
        return super()._get_invalidation_fields() | {'sales_team'}
