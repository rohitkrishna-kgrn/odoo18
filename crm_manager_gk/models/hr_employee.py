from odoo import _, api, models
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.constrains('parent_id')
    def _check_crm_manager_reporting_loop(self):
        # Core hr lets an employee end up managing themselves (A -> B -> A).
        # The Manager rules walk this chain, so a loop would make two people
        # each other's Manager.  Only employees that are themselves on a loop
        # are rejected; people reporting into one can still be edited.
        if self._has_cycle('parent_id'):
            raise ValidationError(_(
                "This Manager would create a reporting loop: an employee cannot "
                "report to themselves, directly or through someone who reports to them."))
