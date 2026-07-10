from odoo import models, fields, api, tools


class MisProjectRevenue(models.Model):
    """One row per task — task-level summary shown in the list view."""
    _name = 'mis.project.revenue'
    _description = 'MIS Task Revenue'
    _auto = False
    _rec_name = 'task_name'
    _order = 'department_id, project_id, task_id'

    # ── Grouping ──────────────────────────────────────────────────────────
    company_id         = fields.Many2one('res.company',     string='Company',         readonly=True)
    department_id      = fields.Many2one('hr.department',   string='Department',      readonly=True)
    project_manager_id = fields.Many2one('res.users',       string='Project Manager', readonly=True)
    project_id         = fields.Many2one('project.project', string='Project',         readonly=True)
    sale_order_id      = fields.Many2one('sale.order',      string='Sale Order',      readonly=True)

    # ── Task ─────────────────────────────────────────────────────────────
    task_id            = fields.Many2one('project.task',    string='Task',            readonly=True)
    task_name          = fields.Char(string='Task',                                   readonly=True)
    sale_order_line_id = fields.Many2one('sale.order.line', string='SO Line',         readonly=True)

    # ── Task-level aggregates ─────────────────────────────────────────────
    task_value             = fields.Float(string='Task Unit Value',          readonly=True)
    total_weighted_hours   = fields.Float(string='Total Weighted Hours',     readonly=True, digits=(16, 2))
    total_employee_revenue = fields.Float(string='Total Employee Revenue',   readonly=True, digits=(16, 2))
    task_create_date       = fields.Date(string='Task Created Date',         readonly=True)

    currency_id        = fields.Many2one('res.currency',   string='Currency',         readonly=True)

    # ── One2many to per-user lines (shown in form view) ───────────────────
    user_line_ids = fields.One2many(
        'mis.project.revenue.line', 'task_revenue_id',
        string='Employee Breakdown', readonly=True,
    )

    # ─────────────────────────────────────────────────────────────────────
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH task_timesheet AS (
                    SELECT
                        aal.task_id,
                        aal.user_id,
                        he.mis_revenue_role_id,
                        COALESCE(mrr.multiplier, 1)                          AS role_multiplier,
                        SUM(aal.unit_amount)                                 AS actual_hours,
                        SUM(aal.unit_amount) * COALESCE(mrr.multiplier, 1)   AS weighted_hours
                    FROM   account_analytic_line aal
                    JOIN   res_users     ru  ON ru.id  = aal.user_id
                    LEFT JOIN hr_employee he  ON he.user_id = aal.user_id AND he.active = TRUE
                    LEFT JOIN mis_revenue_role mrr ON mrr.id = he.mis_revenue_role_id
                    WHERE  aal.task_id IS NOT NULL AND aal.unit_amount > 0
                    GROUP  BY aal.task_id, aal.user_id, he.mis_revenue_role_id, mrr.multiplier
                ),
                task_totals AS (
                    SELECT
                        task_id,
                        SUM(weighted_hours) AS total_weighted_hours
                    FROM task_timesheet
                    GROUP BY task_id
                )
                SELECT
                    pt.id                                                    AS id,
                    pt.id                                                    AS task_id,
                    pp.company_id,
                    pp.department_id,
                    pp.user_id                                               AS project_manager_id,
                    pp.id                                                    AS project_id,
                    so.id                                                    AS sale_order_id,
                    CASE WHEN LEFT(pt.name::text, 1) = '{'
                         THEN (pt.name::jsonb)->>'en_US'
                         ELSE pt.name::text
                    END                                                      AS task_name,
                    sol.id                                                   AS sale_order_line_id,
                    CASE WHEN sol.product_uom_qty > 0
                         THEN sol.price_subtotal / sol.product_uom_qty
                         ELSE 0 END                                          AS task_value,
                    COALESCE(tt.total_weighted_hours, 0)                     AS total_weighted_hours,
                    /* total revenue = task_value when hours are logged, else 0 */
                    CASE WHEN COALESCE(tt.total_weighted_hours, 0) > 0
                         THEN (CASE WHEN sol.product_uom_qty > 0
                                    THEN sol.price_subtotal / sol.product_uom_qty
                                    ELSE 0 END)
                         ELSE 0 END                                          AS total_employee_revenue,
                    pt.create_date::date                                     AS task_create_date,
                    rc.currency_id
                FROM   project_task       pt
                JOIN   project_project    pp  ON pp.id  = pt.project_id
                JOIN   sale_order_line    sol ON sol.id = pt.sale_line_id
                JOIN   sale_order         so  ON so.id  = sol.order_id
                JOIN   res_company        rc  ON rc.id  = pp.company_id
                JOIN   task_totals        tt  ON tt.task_id = pt.id
                WHERE  pt.active = TRUE AND pp.active = TRUE
            )
        """ % self._table)

    # ── Role-based access ─────────────────────────────────────────────────
    @api.model
    def _get_access_domain(self):
        user = self.env.user
        if user.has_group('mis_report_kgrn.group_mis_admin'):
            return []
        if user.has_group('mis_report_kgrn.group_mis_manager'):
            emp = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
            if emp:
                subordinates = self.env['hr.employee'].search([('parent_id', '=', emp.id)])
                user_ids = (subordinates.mapped('user_id') | user).ids
            else:
                user_ids = [user.id]
            return [('project_manager_id', 'in', user_ids)]
        return [('project_manager_id', '=', user.id)]

    @api.model
    def search(self, domain=None, offset=0, limit=None, order=None):
        domain = self._get_access_domain() + list(domain or [])
        return super().search(domain, offset=offset, limit=limit, order=order)

    @api.model
    def search_count(self, domain=None, limit=None):
        domain = self._get_access_domain() + list(domain or [])
        if limit is not None:
            return super().search_count(domain, limit=limit)
        return super().search_count(domain)

    @api.model
    def read_group(self, domain, fields, groupby,
                   offset=0, limit=None, orderby=False, lazy=True):
        domain = self._get_access_domain() + list(domain or [])
        return super().read_group(domain, fields, groupby,
                                  offset=offset, limit=limit,
                                  orderby=orderby, lazy=lazy)


class MisProjectRevenueLine(models.Model):
    """One row per (task × employee) — shown inside the task form view."""
    _name = 'mis.project.revenue.line'
    _description = 'MIS Task Revenue - Employee Line'
    _auto = False
    _rec_name = 'user_id'
    _order = 'actual_hours desc'

    # ── Parent link ───────────────────────────────────────────────────────
    task_revenue_id = fields.Many2one(
        'mis.project.revenue', string='Task', readonly=True,
    )

    # ── Employee & Role ──────────────────────────────────────────────────
    user_id             = fields.Many2one('res.users',        string='Employee',      readonly=True)
    mis_revenue_role_id = fields.Many2one('mis.revenue.role', string='MIS Role',      readonly=True)
    role_multiplier     = fields.Float(string='Multiplier',                           readonly=True, digits=(16, 2))

    # ── Calculations ─────────────────────────────────────────────────────
    actual_hours            = fields.Float(string='Actual Hours',                     readonly=True, digits=(16, 2))
    weighted_hours          = fields.Float(string='Weighted Hours (hrs × mult)',      readonly=True, digits=(16, 2))
    total_weighted_hours    = fields.Float(string='Total Task Weighted Hours',        readonly=True, digits=(16, 2))
    value_per_weighted_hour = fields.Float(string='Value per Weighted Hour',          readonly=True, digits=(16, 4))
    employee_revenue        = fields.Float(string='Employee Revenue',                 readonly=True, digits=(16, 2))

    currency_id = fields.Many2one('res.currency', string='Currency',                  readonly=True)

    # ─────────────────────────────────────────────────────────────────────
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH task_timesheet AS (
                    SELECT
                        aal.task_id,
                        aal.user_id,
                        he.mis_revenue_role_id,
                        COALESCE(mrr.multiplier, 1)                          AS role_multiplier,
                        SUM(aal.unit_amount)                                 AS actual_hours,
                        SUM(aal.unit_amount) * COALESCE(mrr.multiplier, 1)   AS weighted_hours
                    FROM   account_analytic_line aal
                    JOIN   res_users     ru  ON ru.id  = aal.user_id
                    LEFT JOIN hr_employee he  ON he.user_id = aal.user_id AND he.active = TRUE
                    LEFT JOIN mis_revenue_role mrr ON mrr.id = he.mis_revenue_role_id
                    WHERE  aal.task_id IS NOT NULL AND aal.unit_amount > 0
                    GROUP  BY aal.task_id, aal.user_id, he.mis_revenue_role_id, mrr.multiplier
                ),
                task_total_weighted AS (
                    SELECT task_id, SUM(weighted_hours) AS total_weighted_hours
                    FROM   task_timesheet
                    GROUP  BY task_id
                )
                SELECT
                    ROW_NUMBER() OVER (
                        ORDER BY pt.id, tt.actual_hours DESC
                    )                                                        AS id,
                    pt.id                                                    AS task_revenue_id,
                    tt.user_id,
                    tt.mis_revenue_role_id,
                    tt.role_multiplier,
                    tt.actual_hours,
                    tt.weighted_hours,
                    COALESCE(twt.total_weighted_hours, 0)                    AS total_weighted_hours,
                    CASE WHEN COALESCE(twt.total_weighted_hours, 0) > 0
                         THEN (CASE WHEN sol.product_uom_qty > 0
                                    THEN sol.price_subtotal / sol.product_uom_qty
                                    ELSE 0 END)
                              / twt.total_weighted_hours
                         ELSE 0 END                                          AS value_per_weighted_hour,
                    CASE WHEN COALESCE(twt.total_weighted_hours, 0) > 0
                         THEN ((CASE WHEN sol.product_uom_qty > 0
                                     THEN sol.price_subtotal / sol.product_uom_qty
                                     ELSE 0 END)
                               / twt.total_weighted_hours)
                              * tt.weighted_hours
                         ELSE 0 END                                          AS employee_revenue,
                    rc.currency_id
                FROM   project_task        pt
                JOIN   project_project     pp  ON pp.id  = pt.project_id
                JOIN   sale_order_line     sol ON sol.id = pt.sale_line_id
                JOIN   sale_order          so  ON so.id  = sol.order_id
                JOIN   res_company         rc  ON rc.id  = pp.company_id
                JOIN   task_timesheet      tt  ON tt.task_id  = pt.id
                JOIN   task_total_weighted twt ON twt.task_id = pt.id
                WHERE  pt.active = TRUE AND pp.active = TRUE
            )
        """ % self._table)
