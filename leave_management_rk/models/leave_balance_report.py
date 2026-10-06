from odoo import models, fields, api, tools

from .leave_period import leave_month_anchor


class LeaveBalanceReport(models.Model):
    """Read-only reporting view over leave.balance, for HR / management.

    One row per (employee, leave type, leave month) that has a leave.balance
    row — i.e. it only shows periods the monthly accrual (or the HR balance
    wizard) has actually opened. If a period looks "missing", check whether
    the accrual cron has run or a balance was seeded for it; this view is
    never the source of that data, only a read-only reflection of it.
    """
    _name = 'leave.balance.report'
    _description = 'Leave Balance Report'
    _auto = False
    _order = 'employee_name, leave_type_id, period_date desc'

    user_id = fields.Many2one('res.users', string='User', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    employee_name = fields.Char(string='Employee Name', readonly=True)
    employee_code = fields.Char(string='Employee ID', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    country = fields.Selection([
        ('india', 'India'),
        ('dubai', 'Dubai (UAE)'),
    ], string='Country / Category', readonly=True)
    leave_type_id = fields.Many2one('leave.type', string='Leave Type', readonly=True)
    leave_type_label = fields.Char(
        string='Leave Type', readonly=True,
        help="Leave type name; Dubai Sick Leave is split into Full Pay / Half Pay rows.")
    is_permission = fields.Boolean(string='Hour-Based', readonly=True)
    annual_entitlement = fields.Float(string='Total Leave Entitlement', readonly=True, aggregator=None)
    accrued = fields.Float(string='Leave Accrued / Allocated', readonly=True, aggregator=None)
    availed = fields.Float(string='Leave Availed', readonly=True, aggregator=None)
    pending = fields.Float(string='Pending Approval', readonly=True, aggregator=None)
    current_balance = fields.Float(string='Current Balance', readonly=True, aggregator=None)
    period_date = fields.Date(string='Leave Month (Anchor)', readonly=True)
    period_start = fields.Date(string='Period Start', readonly=True)
    period_end = fields.Date(string='Period End', readonly=True)
    period_label = fields.Char(string='Leave Period', readonly=True)
    is_current_period = fields.Boolean(
        string='Current Leave Month',
        compute='_compute_is_current_period',
        search='_search_is_current_period',
    )

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):
        # Every row spans exactly one leave month, so "Period Start = X" /
        # "Period End = Y" can only ever match a single month. Read them as a
        # range instead (start on/after X, end on/before Y) so a custom filter
        # over several months returns every month inside it.
        def widen(leaf):
            if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[1] == '=' and leaf[2]:
                if leaf[0] == 'period_start':
                    return ('period_start', '>=', leaf[2])
                if leaf[0] == 'period_end':
                    return ('period_end', '<=', leaf[2])
            return leaf
        return super()._search([widen(leaf) for leaf in domain or []],
                               offset=offset, limit=limit, order=order)

    @api.depends('period_date')
    def _compute_is_current_period(self):
        current = leave_month_anchor(fields.Date.today())
        for rec in self:
            rec.is_current_period = rec.period_date == current

    def _search_is_current_period(self, operator, value):
        current = leave_month_anchor(fields.Date.today())
        matches = (operator == '=') == bool(value)
        return [('period_date', '=' if matches else '!=', current)]

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW leave_balance_report AS (
                WITH availed AS (
                    SELECT
                        lr.user_id AS user_id,
                        lr.leave_type_id AS leave_type_id,
                        (CASE WHEN EXTRACT(DAY FROM lr.start_date) >= 26
                              THEN date_trunc('month', lr.start_date + interval '1 month')
                              ELSE date_trunc('month', lr.start_date)
                         END)::date AS period_date,
                        SUM(CASE WHEN lt.is_permission THEN lr.hours_requested ELSE lr.days_requested END) AS qty
                    FROM leave_request lr
                    JOIN leave_type lt ON lt.id = lr.leave_type_id
                    WHERE lr.state = 'approved'
                    GROUP BY 1, 2, 3
                ),
                pending AS (
                    SELECT
                        lr.user_id AS user_id,
                        lr.leave_type_id AS leave_type_id,
                        (CASE WHEN EXTRACT(DAY FROM lr.start_date) >= 26
                              THEN date_trunc('month', lr.start_date + interval '1 month')
                              ELSE date_trunc('month', lr.start_date)
                         END)::date AS period_date,
                        SUM(CASE WHEN lt.is_permission THEN lr.hours_requested ELSE lr.days_requested END) AS qty
                    FROM leave_request lr
                    JOIN leave_type lt ON lt.id = lr.leave_type_id
                    WHERE lr.state IN ('waiting_manager', 'manager_approved')
                    GROUP BY 1, 2, 3
                ),
                base AS (
                    SELECT
                        lb.id AS lb_id,
                        lb.user_id AS user_id,
                        lb.leave_type_id AS leave_type_id,
                        he.id AS employee_id,
                        he.name AS employee_name,
                        he.identification_id AS employee_code,
                        he.department_id AS department_id,
                        ru.country AS country,
                        lt.name AS leave_type_name,
                        lt.is_permission AS is_permission,
                        (lt.id = COALESCE(lop.res_id, 0)) AS is_lop,
                        (CASE
                            -- 'reset' leave types don't carry a real annual figure in
                            -- annual_entitlement: that field is only meaningful when
                            -- this type also uses the Dubai carry-forward pool (e.g.
                            -- Sick Leave's 45-day pool) and this row's user is in
                            -- Dubai. Otherwise the real annual number is the monthly
                            -- reset value x 12 (e.g. India Sick Leave: 1/month -> 12).
                            -- A monthly_reset_value of 99999+ is the "no real cap"
                            -- sentinel (Loss of Pay) - x12 would just inflate the
                            -- sentinel, so report 0 (no defined entitlement) instead.
                            WHEN lt.accrual_mode = 'reset' AND lt.monthly_reset_value >= 9999
                                THEN 0.0
                            WHEN lt.accrual_mode = 'reset' AND lt.dubai_annual_pool AND ru.country = 'dubai'
                                THEN lt.annual_entitlement
                            WHEN lt.accrual_mode = 'reset'
                                THEN lt.monthly_reset_value * 12
                            ELSE lt.annual_entitlement
                         END) AS annual_entitlement,
                        lb.balance AS current_balance,
                        COALESCE(av.qty, 0.0) AS availed,
                        COALESCE(pe.qty, 0.0) AS pending,
                        lb.date AS period_date,
                        ((lb.date - interval '1 month') + interval '25 days')::date AS period_start,
                        (lb.date + interval '24 days')::date AS period_end,
                        trim(to_char(lb.date, 'FMMonth YYYY')) AS period_label
                    FROM leave_balance lb
                    JOIN leave_type lt ON lt.id = lb.leave_type_id
                    JOIN res_users ru ON ru.id = lb.user_id
                    LEFT JOIN ir_model_data lop
                        ON lop.module = 'leave_management_rk' AND lop.name = 'leave_type_lop'
                    LEFT JOIN ir_model_data sick
                        ON sick.module = 'leave_management_rk' AND sick.name = 'leave_type_sick'
                    LEFT JOIN LATERAL (
                        SELECT e.id, e.name, e.identification_id, e.department_id
                        FROM hr_employee e
                        WHERE e.user_id = ru.id
                        ORDER BY e.active DESC, e.id ASC
                        LIMIT 1
                    ) he ON true
                    LEFT JOIN availed av
                        ON av.user_id = lb.user_id
                       AND av.leave_type_id = lb.leave_type_id
                       AND av.period_date = lb.date
                    LEFT JOIN pending pe
                        ON pe.user_id = lb.user_id
                       AND pe.leave_type_id = lb.leave_type_id
                       AND pe.period_date = lb.date
                    -- Dubai users never see Loss of Pay / Permission here, nor the
                    -- plain Sick Leave (they use Sick Leave - Full Pay / Half Pay).
                    WHERE NOT (COALESCE(ru.country, '') = 'dubai'
                               AND (COALESCE(lt.is_permission, false) OR lt.id = COALESCE(lop.res_id, 0)
                                    OR lt.id = COALESCE(sick.res_id, 0)))
                )
                SELECT
                    b.lb_id AS id, b.user_id, b.employee_id, b.employee_name,
                    b.employee_code, b.department_id, b.country, b.leave_type_id,
                    b.leave_type_name AS leave_type_label,
                    b.is_permission, b.annual_entitlement,
                    b.current_balance + b.availed AS accrued,
                    b.availed, b.pending, b.current_balance,
                    b.period_date, b.period_start, b.period_end, b.period_label
                FROM base b
            )
        """)
