from odoo import fields, models


class ClientHelpdeskPortalUser(models.Model):
    _name = 'client.helpdesk.portal.user'
    _description = 'Helpdesk Portal User'
    _rec_name = 'employee_id'
    _order = 'employee_id'

    employee_id = fields.Many2one(
        'hr.employee', string='User', required=True, ondelete='cascade', index=True,
    )
    department_id = fields.Many2one(
        related='employee_id.department_id', string='Department', store=True, readonly=True,
    )
    user_id = fields.Many2one(
        related='employee_id.user_id', string='Linked Odoo User', store=True, readonly=True,
        help='The employee\'s Odoo login. A ticket is assigned to a user, '
             'not just an employee record — without one linked here, this '
             'employee is excluded from the "Assigned To" dropdown even '
             'with Select Access enabled, and any older ticket that '
             'requested them falls back to the Helpdesk Admin.',
    )
    active = fields.Boolean(
        related='employee_id.active', store=True,
        help='Follows the employee\'s active status in Employees — this '
             'record disappears from the list on its own once the '
             'employee is archived there, instead of needing its own '
             'toggle here. Deliberately NOT tied to the linked Odoo '
             'user\'s active status: most employees here won\'t have an '
             'enabled login, but Admin/Manager still need to see and '
             'manage their Select Access setting from this screen. The '
             '"Assigned To" dropdown enforces active-login separately, '
             'via _get_assignable_users() on client.helpdesk.ticket.',
    )
    select_access = fields.Boolean(
        'Select Access', default=False,
        help='Only employees with Select Access enabled AND a Linked Odoo '
             'User appear in the "Assigned To" dropdown on the public '
             'ticket submission form, shown there as "Employee Name - '
             'Department Name".',
    )

    _sql_constraints = [
        ('employee_uniq', 'unique(employee_id)',
         'This employee already has a Helpdesk Portal User record.'),
    ]
