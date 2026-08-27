from odoo import models, fields, api
from odoo.exceptions import UserError

from .leave_period import (
    leave_month_anchor,
    leave_month_bounds,
    leave_month_label,
    shift_leave_month,
)


class LeaveType(models.Model):
    _name = 'leave.type'
    _description = 'Leave Type'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    is_permission = fields.Boolean(string='Is Permission Leave', default=False)
    active = fields.Boolean(default=True)


class LeaveBalance(models.Model):
    _name = 'leave.balance'
    _description = 'Leave Balance per User per Leave Type'

    user_id = fields.Many2one('res.users', string='User', required=True)
    leave_type_id = fields.Many2one('leave.type', string='Leave Type', required=True)
    balance = fields.Float(string='Balance', default=0.0)
    date = fields.Date(
        string='Leave Month',
        help="Anchor of the leave month this balance belongs to: the 1st of the "
             "month the period is named after. The period itself runs from the "
             "26th of the previous month to the 25th of this one.")
    period_start = fields.Date(
        string='Period Start', compute='_compute_period', store=False)
    period_end = fields.Date(
        string='Period End', compute='_compute_period', store=False)
    period_label = fields.Char(
        string='Leave Period', compute='_compute_period', store=False)
    is_current_period = fields.Boolean(
        string='Current Leave Month',
        compute='_compute_is_current_period',
        search='_search_is_current_period',
        store=False)

    _sql_constraints = [
        ('user_leave_unique', 'unique(user_id, leave_type_id, date)', 'Leave balance already exists for this user, leave type, and date.'),
    ]

    @api.depends('date')
    def _compute_period(self):
        for rec in self:
            if rec.date:
                rec.period_start, rec.period_end = leave_month_bounds(rec.date)
                rec.period_label = leave_month_label(rec.date)
            else:
                rec.period_start = rec.period_end = False
                rec.period_label = ''

    @api.depends('date')
    def _compute_is_current_period(self):
        current = leave_month_anchor(fields.Date.today())
        for rec in self:
            rec.is_current_period = rec.date == current

    def _search_is_current_period(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError("Unsupported search on 'Current Leave Month'.")
        current = leave_month_anchor(fields.Date.today())
        matches = (operator == '=') == bool(value)
        return [('date', '=' if matches else '!=', current)]

    @api.depends('user_id', 'leave_type_id', 'date')
    def _compute_display_name(self):
        for rec in self:
            parts = [rec.user_id.name or '', rec.leave_type_id.name or '']
            if rec.date:
                parts.append(rec.date.strftime('%B %Y'))
            rec.display_name = ' - '.join(p for p in parts if p)

    @api.model
    def current_leave_month(self, any_date=None):
        """Anchor of the leave month covering ``any_date`` (default: today)."""
        return leave_month_anchor(any_date or fields.Date.today())

    def _get_leave_types(self):
        LeaveType = self.env['leave.type']
        return {
            'casual': LeaveType.search([('name', '=', 'Casual Leave')], limit=1),
            'sick': LeaveType.search([('name', '=', 'Sick Leave')], limit=1),
            'lop': LeaveType.search([('name', '=', 'Loss of Pay')], limit=1),
            'comp': LeaveType.search([('name', '=', 'Compensation Leave')], limit=1),
            'permission': LeaveType.search([('name', '=', 'Permission')], limit=1),
        }

    @api.model
    def update_monthly_leave_balances(self):
        types = self._get_leave_types()
        if not (types['casual'] and types['sick'] and types['lop'] and types['comp']):
            raise ValueError("One or more required leave types are missing.")

        # Runs on the 26th: that date already belongs to the new leave month,
        # so the anchor helper returns the period being opened.
        today = fields.Date.today()
        first_of_this_month = leave_month_anchor(today)

        users = self.env['res.users'].search([('country', 'in', ['india', 'dubai'])])

        for user in users:
            country = user.country

            last_casual = self.search([
                ('user_id', '=', user.id),
                ('leave_type_id', '=', types['casual'].id),
                ('date', '<', first_of_this_month),
            ], order='date desc', limit=1)
            last_casual_balance = last_casual.balance if last_casual else 0

            last_comp = self.search([
                ('user_id', '=', user.id),
                ('leave_type_id', '=', types['comp'].id),
                ('date', '<', first_of_this_month),
            ], order='date desc', limit=1)
            last_comp_balance = last_comp.balance if last_comp else 0

            if country == 'india':
                # India: sick resets to 1 (no carry forward), casual accumulates
                sick_balance = 1
                casual_balance = last_casual_balance + 1
                comp_balance = last_comp_balance

                self._update_balance(user, types['casual'], first_of_this_month, casual_balance)
                self._update_balance(user, types['sick'], first_of_this_month, sick_balance)
                self._update_balance(user, types['lop'], first_of_this_month, 99999)
                self._update_balance(user, types['comp'], first_of_this_month, comp_balance)
                if types['permission']:
                    self._update_balance(user, types['permission'], first_of_this_month, 3)

            elif country == 'dubai':
                # Dubai: yearly pool, carry forward each month
                if first_of_this_month.month == 1:
                    casual_balance = 31
                    sick_balance = 45
                else:
                    last_c = self.search([('user_id', '=', user.id), ('leave_type_id', '=', types['casual'].id)], order='date desc', limit=1)
                    casual_balance = last_c.balance if last_c else 31
                    last_s = self.search([('user_id', '=', user.id), ('leave_type_id', '=', types['sick'].id)], order='date desc', limit=1)
                    sick_balance = last_s.balance if last_s else 45

                comp_balance = last_comp_balance

                self._update_balance(user, types['casual'], first_of_this_month, casual_balance)
                self._update_balance(user, types['sick'], first_of_this_month, sick_balance)
                self._update_balance(user, types['lop'], first_of_this_month, 99999)
                self._update_balance(user, types['comp'], first_of_this_month, comp_balance)
                if types['permission']:
                    self._update_balance(user, types['permission'], first_of_this_month, 3)

    def _update_balance(self, user, leave_type, balance_date, balance):
        rec = self.search([
            ('user_id', '=', user.id),
            ('leave_type_id', '=', leave_type.id),
            ('date', '=', balance_date)
        ], limit=1)
        if rec:
            rec.balance = balance
        else:
            self.create({
                'user_id': user.id,
                'leave_type_id': leave_type.id,
                'date': balance_date,
                'balance': balance,
            })

    @api.model
    def update_user_balance_on_country_change(self, user):
        types = self._get_leave_types()
        if not (types['casual'] and types['sick'] and types['lop'] and types['comp']):
            return

        current_anchor = leave_month_anchor(fields.Date.today())
        for i in range(4):
            month_date = shift_leave_month(current_anchor, i)

            last_casual = self.search([('user_id', '=', user.id), ('leave_type_id', '=', types['casual'].id), ('date', '<', month_date)], order='date desc', limit=1)
            last_casual_balance = last_casual.balance if last_casual else 0

            last_comp = self.search([('user_id', '=', user.id), ('leave_type_id', '=', types['comp'].id), ('date', '<', month_date)], order='date desc', limit=1)
            last_comp_balance = last_comp.balance if last_comp else 0

            if user.country == 'india':
                casual_balance = last_casual_balance + 1
                sick_balance = 1
                lop_balance = 99999
                comp_balance = last_comp_balance
                perm_balance = 3

            elif user.country == 'dubai':
                if month_date.month == 1:
                    casual_balance = 31
                    sick_balance = 45
                else:
                    last_c = self.search([('user_id', '=', user.id), ('leave_type_id', '=', types['casual'].id)], order='date desc', limit=1)
                    casual_balance = last_c.balance if last_c else 31
                    last_s = self.search([('user_id', '=', user.id), ('leave_type_id', '=', types['sick'].id)], order='date desc', limit=1)
                    sick_balance = last_s.balance if last_s else 45
                lop_balance = 99999
                comp_balance = last_comp_balance
                perm_balance = 3
            else:
                continue

            self._update_balance(user, types['casual'], month_date, casual_balance)
            self._update_balance(user, types['sick'], month_date, sick_balance)
            self._update_balance(user, types['lop'], month_date, lop_balance)
            self._update_balance(user, types['comp'], month_date, comp_balance)
            if types['permission']:
                self._update_balance(user, types['permission'], month_date, perm_balance)

    @api.model
    def reset_leave_balances_dec31(self):
        """Year-end reset - seeds the January leave month (26 Dec -> 25 Jan).

        The cron now fires on 25 Dec 23:59 rather than 31 Dec 23:59, keeping it
        immediately ahead of the monthly accrual that opens the January period
        at 26 Dec 00:00 - the same ordering it had against the 1 Jan cron.
        Kept working whichever side of the 26th it is triggered from.
        """
        types = self._get_leave_types()
        anchor = leave_month_anchor(fields.Date.today())
        jan_first_next_year = (
            anchor if anchor.month == 1
            else anchor.replace(year=anchor.year + 1, month=1, day=1)
        )

        users = self.env['res.users'].search([('country', 'in', ['india', 'dubai'])])

        for user in users:
            country = user.country
            if country == 'india':
                casual_balance = 1
                sick_balance = 1
                lop_balance = 99999
            elif country == 'dubai':
                casual_balance = 31
                sick_balance = 45
                lop_balance = 99999
            else:
                continue

            if types['casual']:
                self._update_balance(user, types['casual'], jan_first_next_year, casual_balance)
            if types['sick']:
                self._update_balance(user, types['sick'], jan_first_next_year, sick_balance)
            if types['lop']:
                self._update_balance(user, types['lop'], jan_first_next_year, lop_balance)
            if types['comp']:
                self._update_balance(user, types['comp'], jan_first_next_year, 0)
            if types['permission']:
                self._update_balance(user, types['permission'], jan_first_next_year, 3)

    @api.model
    def action_manual_reset_leaves(self):
        """Manual reset button - System Admin only.

        Resets the leave month currently in progress (26th -> 25th) to defaults.
        """
        if not self.env.user.has_group('base.group_system'):
            raise UserError("Only System Administrators can perform manual leave resets.")

        types = self._get_leave_types()
        first_of_month = leave_month_anchor(fields.Date.today())

        users = self.env['res.users'].search([('country', 'in', ['india', 'dubai'])])

        for user in users:
            country = user.country
            if country == 'india':
                casual_balance = 1
                sick_balance = 1
                lop_balance = 99999
            elif country == 'dubai':
                casual_balance = 31
                sick_balance = 45
                lop_balance = 99999
            else:
                continue

            if types['casual']:
                self._update_balance(user, types['casual'], first_of_month, casual_balance)
            if types['sick']:
                self._update_balance(user, types['sick'], first_of_month, sick_balance)
            if types['lop']:
                self._update_balance(user, types['lop'], first_of_month, lop_balance)
            if types['comp']:
                self._update_balance(user, types['comp'], first_of_month, 0)
            if types['permission']:
                self._update_balance(user, types['permission'], first_of_month, 3)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Leave Reset Complete',
                'message': 'All leave balances have been reset to defaults.',
                'type': 'success',
            }
        }
