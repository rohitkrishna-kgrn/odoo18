from odoo import models, fields, api
from datetime import timedelta, date

class LeaveType(models.Model):
    _name = 'leave.type'
    _description = 'Leave Type'
    _order = 'name'

    name = fields.Char(string='Name', required=True)

    current_user_balance = fields.Integer(string='Current Leave Balance', compute='_compute_current_user_balance')

    display_name = fields.Char(string='Display Name', compute='_compute_display_name')
    _rec_name = 'display_name'

    @api.depends('name')
    def _compute_display_name(self):
        for record in self:
            leave_balance = record.current_user_balance or 0
            record.display_name = f"{record.name} - {leave_balance}"

    def _compute_current_user_balance(self):
        LeaveBalance = self.env['leave.balance']
        today = date.today()
        first_of_month = today.replace(day=1)
        current_user = self.env.user

        for leave_type in self:
            balance_record = LeaveBalance.search([
                ('user_id', '=', current_user.id),
                ('leave_type_id', '=', leave_type.id),
                ('date', '=', first_of_month),
            ], limit=1)
            leave_type.current_user_balance = int(balance_record.balance) if balance_record else 0


class LeaveBalance(models.Model):
    _name = 'leave.balance'
    _description = 'Leave Balance per User per Leave Type'

    user_id = fields.Many2one('res.users', string='User', required=True)
    leave_type_id = fields.Many2one('leave.type', string='Leave Type', required=True)
    balance = fields.Float(string='Balance', default=0.0)
    date = fields.Date(string='Date')  # Usually first day of the month

    _sql_constraints = [
        ('user_leave_unique', 'unique(user_id, leave_type_id, date)', 'Leave balance already exists for this user, leave type, and date.'),
    ]

    @api.model
    def update_monthly_leave_balances(self):
        LeaveType = self.env['leave.type']
        User = self.env['res.users']

        # Get leave types by exact names
        casual_leave = LeaveType.search([('name', '=', 'Casual Leave')], limit=1)
        sick_leave = LeaveType.search([('name', '=', 'Sick Leave')], limit=1)
        loss_of_pay = LeaveType.search([('name', '=', 'Loss of Pay')], limit=1)
        wfh_leave = LeaveType.search([('name', '=', 'Work from Home')], limit=1)
        compensation_leave = LeaveType.search([('name', '=', 'Compensation Leave')], limit=1)

        if not (casual_leave and sick_leave and loss_of_pay and wfh_leave and compensation_leave):
            raise ValueError("One or more required leave types are missing.")

        today = fields.Date.today()
        first_of_this_month = today.replace(day=1)
        last_month_date = (first_of_this_month - timedelta(days=1)).replace(day=1)

        users = User.search([])

        for user in users:
            country = user.country

            last_casual_record = self.search([
                ('user_id', '=', user.id),
                ('leave_type_id', '=', casual_leave.id),
                ('date', '=', last_month_date)
            ], limit=1)
            last_casual_balance = last_casual_record.balance if last_casual_record else 0

            last_comp_record = self.search([
                ('user_id', '=', user.id),
                ('leave_type_id', '=', compensation_leave.id),
                ('date', '=', last_month_date)
            ], limit=1)
            last_comp_balance = last_comp_record.balance if last_comp_record else 0

            # Check if user took casual leave last month
            took_casual_last_month = user.took_leave(casual_leave, last_month_date)

            if country == 'india':
                # India: 1 Sick Leave/month, 1 Casual Leave/month (carried over if not taken), LOP = ∞
                sick_balance = 1
                casual_balance = 1 if took_casual_last_month else last_casual_balance + 1

                # Compensation leave carries forward balance, no monthly addition
                comp_balance = last_comp_balance

                self._update_balance(user, casual_leave, first_of_this_month, casual_balance)
                self._update_balance(user, sick_leave, first_of_this_month, sick_balance)
                self._update_balance(user, loss_of_pay, first_of_this_month, 99999)
                self._update_balance(user, compensation_leave, first_of_this_month, comp_balance)
                self._update_balance(user, wfh_leave, first_of_this_month, 99999)  # Unlimited WFH

            elif country == 'dubai':
                # Dubai: 31 CL, 45 SL initially, carry forward monthly, reset in Jan
                if first_of_this_month.month == 1:
                    casual_balance = 31
                    sick_balance = 45
                else:
                    last_casual_record = self.search([
                        ('user_id', '=', user.id),
                        ('leave_type_id', '=', casual_leave.id),
                    ], order='date desc', limit=1)
                    casual_balance = last_casual_record.balance if last_casual_record else 31

                    last_sick_record = self.search([
                        ('user_id', '=', user.id),
                        ('leave_type_id', '=', sick_leave.id),
                    ], order='date desc', limit=1)
                    sick_balance = last_sick_record.balance if last_sick_record else 45

                comp_balance = last_comp_balance

                self._update_balance(user, casual_leave, first_of_this_month, casual_balance)
                self._update_balance(user, sick_leave, first_of_this_month, sick_balance)
                self._update_balance(user, loss_of_pay, first_of_this_month, 99999)
                self._update_balance(user, compensation_leave, first_of_this_month, comp_balance)
                self._update_balance(user, wfh_leave, first_of_this_month, 99999)  # Unlimited WFH
        
        now = datetime.now()
        next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        cron = self.env.ref('your_module.ir_cron_update_leave_balances')
        if cron:
            cron.write({'nextcall': next_month.strftime('%Y-%m-%d %H:%M:%S')})

    def _update_balance(self, user, leave_type, date, balance):
        rec = self.search([
            ('user_id', '=', user.id),
            ('leave_type_id', '=', leave_type.id),
            ('date', '=', date)
        ], limit=1)

        if rec:
            rec.balance = balance
        else:
            self.create({
                'user_id': user.id,
                'leave_type_id': leave_type.id,
                'date': date,
                'balance': balance,
            })

    @api.model
    def update_user_balance_on_country_change(self, user):
        LeaveType = self.env['leave.type']
        casual_leave = LeaveType.search([('name', '=', 'Casual Leave')], limit=1)
        sick_leave = LeaveType.search([('name', '=', 'Sick Leave')], limit=1)
        loss_of_pay = LeaveType.search([('name', '=', 'Loss of Pay')], limit=1)
        wfh_leave = LeaveType.search([('name', '=', 'Work from Home')], limit=1)
        compensation_leave = LeaveType.search([('name', '=', 'Compensation Leave')], limit=1)

        if not (casual_leave and sick_leave and loss_of_pay and wfh_leave and compensation_leave):
            return

        today = date.today()
        for i in range(4):
            month_date = (today.replace(day=1) + timedelta(days=31*i)).replace(day=1)

            last_casual_record = self.search([
                ('user_id', '=', user.id),
                ('leave_type_id', '=', casual_leave.id),
                ('date', '=', (month_date - timedelta(days=1)).replace(day=1)),
            ], limit=1)
            last_casual_balance = last_casual_record.balance if last_casual_record else 0

            last_comp_record = self.search([
                ('user_id', '=', user.id),
                ('leave_type_id', '=', compensation_leave.id),
                ('date', '=', (month_date - timedelta(days=1)).replace(day=1)),
            ], limit=1)
            last_comp_balance = last_comp_record.balance if last_comp_record else 0

            took_casual_last_month = user.took_leave(casual_leave, (month_date - timedelta(days=1)).replace(day=1))

            if user.country == 'india':
                casual_balance = 1 if took_casual_last_month else last_casual_balance + 1
                sick_balance = 1
                lop_balance = 99999
                comp_balance = last_comp_balance

            elif user.country == 'dubai':
                if month_date.month == 1:
                    casual_balance = 31
                    sick_balance = 45
                else:
                    last_casual = self.search([
                        ('user_id', '=', user.id),
                        ('leave_type_id', '=', casual_leave.id),
                    ], order='date desc', limit=1)
                    casual_balance = last_casual.balance if last_casual else 31

                    last_sick = self.search([
                        ('user_id', '=', user.id),
                        ('leave_type_id', '=', sick_leave.id),
                    ], order='date desc', limit=1)
                    sick_balance = last_sick.balance if last_sick else 45

                lop_balance = 99999
                comp_balance = last_comp_balance

            else:
                continue

            self._update_balance(user, casual_leave, month_date, casual_balance)
            self._update_balance(user, sick_leave, month_date, sick_balance)
            self._update_balance(user, loss_of_pay, month_date, lop_balance)
            self._update_balance(user, compensation_leave, month_date, comp_balance)
            self._update_balance(user, wfh_leave, month_date, 99999)  # Unlimited WFH

    @api.model
    def reset_leave_balances_jan1(self):
        LeaveType = self.env['leave.type']
        User = self.env['res.users']

        casual_leave = LeaveType.search([('name', '=', 'Casual Leave')], limit=1)
        sick_leave = LeaveType.search([('name', '=', 'Sick Leave')], limit=1)
        loss_of_pay = LeaveType.search([('name', '=', 'Loss of Pay')], limit=1)
        wfh_leave = LeaveType.search([('name', '=', 'Work from Home')], limit=1)
        compensation_leave = LeaveType.search([('name', '=', 'Compensation Leave')], limit=1)

        jan_first = fields.Date.today().replace(month=1, day=1)

        users = User.search([])

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

            # Compensation Leave resets to 0 on Jan 1
            comp_balance = 0

            self._update_balance(user, casual_leave, jan_first, casual_balance)
            self._update_balance(user, sick_leave, jan_first, sick_balance)
            self._update_balance(user, loss_of_pay, jan_first, lop_balance)
            self._update_balance(user, compensation_leave, jan_first, comp_balance)
            self._update_balance(user, wfh_leave, jan_first, 99999)  # Unlimited WFH

        now = datetime.now()
        year = now.year + 1 if now.month == 12 else now.year
        next_jan1 = datetime(year=year, month=1, day=1, hour=0, minute=0, second=0)
        cron = self.env.ref('your_module.ir_cron_reset_leave_balances_jan1')
        if cron:
            cron.write({'nextcall': next_jan1.strftime('%Y-%m-%d %H:%M:%S')})
