from odoo import models, fields, api, tools


class MisOutstandingLine(models.Model):
    _name = 'mis.outstanding.line'
    _description = 'MIS Outstanding Report'
    _auto = False
    _rec_name = 'project_name'
    _order = 'company_id, project_manager_id, project_name'

    # ── Identifiers ──────────────────────────────────────────────────────
    project_id = fields.Many2one('project.project', string='Project', readonly=True)
    project_name = fields.Char(string='Project', readonly=True)
    project_manager_id = fields.Many2one('res.users', string='Project Manager', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True)
    so_number = fields.Char(string='SO Number', readonly=True)
    salesperson_id = fields.Many2one('res.users', string='Salesperson', readonly=True)
    customer_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    # ── Project value ─────────────────────────────────────────────────────
    project_value_ex_vat = fields.Float(string='Project Value (Ex VAT)', readonly=True)
    project_value_inc_vat = fields.Float(string='Project Value (Inc VAT)', readonly=True)

    # ── SO amounts ───────────────────────────────────────────────────────
    so_total_ex_vat = fields.Float(string='SO Total (Ex VAT)', readonly=True)
    so_total_inc_vat = fields.Float(string='SO Total (Inc VAT)', readonly=True)

    # ── Task counts ──────────────────────────────────────────────────────
    tasks_total = fields.Integer(string='Total Tasks', readonly=True)
    tasks_completed = fields.Integer(string='Completed Tasks', readonly=True)
    tasks_pending = fields.Integer(string='Pending Tasks', readonly=True)

    # ── Completed task value ──────────────────────────────────────────────
    completed_tasks_value_ex_vat = fields.Float(
        string='Completed Tasks Value (Ex VAT)', readonly=True)

    # ── Completed + PAID ──────────────────────────────────────────────────
    completed_invoiced_qty = fields.Integer(
        string='Completed & Paid (Qty)', readonly=True)
    completed_invoiced_amount = fields.Float(
        string='Completed & Paid (Amount)', readonly=True)

    # ── Completed + POSTED but NOT PAID ──────────────────────────────────
    completed_posted_not_paid_qty = fields.Integer(
        string='Completed, Posted Not Paid (Qty)', readonly=True)
    completed_posted_not_paid_amount = fields.Float(
        string='Completed, Posted Not Paid (Amount)', readonly=True)

    # ── Completed + NO INVOICE at all ────────────────────────────────────
    completed_not_invoiced_qty = fields.Integer(
        string='Completed, No Invoice (Qty)', readonly=True)
    completed_not_invoiced_amount = fields.Float(
        string='Completed, No Invoice (Amount)', readonly=True)

    # ── Advance ──────────────────────────────────────────────────────────
    advance_amount = fields.Float(string='Advance Amount (SO)', readonly=True)

    # ── Deadline (uses project.project.date = planned end date) ──────────
    deadline = fields.Date(string='Planned End Date', readonly=True)
    days_overdue = fields.Integer(string='Days Overdue', readonly=True)

    # ── Invoice date ─────────────────────────────────────────────────────
    last_invoice_date = fields.Date(string='Last Invoice Date', readonly=True)
    invoice_days_ago = fields.Integer(string='Invoice Raised (Days Ago)', readonly=True)

    # ── Dates ────────────────────────────────────────────────────────────
    create_date = fields.Date(string='Created Date', readonly=True)

    # ── Completion status ────────────────────────────────────────────────
    is_completed = fields.Boolean(string='Completed', readonly=True)

    # ─────────────────────────────────────────────────────────────────────
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH proj_sol AS (
                    SELECT
                        sol.project_id,
                        sol.order_id,
                        SUM(sol.price_subtotal) AS project_value_ex_vat,
                        SUM(sol.price_total)    AS project_value_inc_vat
                    FROM   sale_order_line sol
                    WHERE  sol.project_id IS NOT NULL
                    GROUP  BY sol.project_id, sol.order_id
                ),
                inv_sol_posted AS (
                    /* SOLs with at least one POSTED invoice */
                    SELECT DISTINCT solr.order_line_id AS sale_line_id
                    FROM   sale_order_line_invoice_rel solr
                    JOIN   account_move_line aml ON aml.id = solr.invoice_line_id
                    JOIN   account_move      am  ON am.id  = aml.move_id
                    WHERE  am.state     = 'posted'
                    AND    am.move_type = 'out_invoice'
                ),
                inv_sol_paid AS (
                    /* SOLs with at least one PAID posted invoice */
                    SELECT DISTINCT solr.order_line_id AS sale_line_id
                    FROM   sale_order_line_invoice_rel solr
                    JOIN   account_move_line aml ON aml.id = solr.invoice_line_id
                    JOIN   account_move      am  ON am.id  = aml.move_id
                    WHERE  am.state         = 'posted'
                    AND    am.payment_state IN ('paid', 'in_payment')
                    AND    am.move_type     = 'out_invoice'
                ),
                proj_inv_date AS (
                    SELECT
                        sol.project_id,
                        MAX(CASE WHEN am.state = 'posted'
                            THEN am.invoice_date ELSE NULL END) AS last_invoice_date
                    FROM   sale_order_line sol
                    JOIN   sale_order_line_invoice_rel solr ON solr.order_line_id = sol.id
                    JOIN   account_move_line aml ON aml.id = solr.invoice_line_id
                    JOIN   account_move      am  ON am.id  = aml.move_id
                    WHERE  sol.project_id IS NOT NULL
                    AND    am.move_type = 'out_invoice'
                    GROUP  BY sol.project_id
                ),
                task_agg AS (
                    SELECT
                        pt.project_id,
                        COUNT(pt.id)                                                AS tasks_total,
                        SUM(CASE WHEN pt.state_additional = 'completed'
                            THEN 1 ELSE 0 END)                                      AS tasks_completed,

                        SUM(CASE WHEN pt.state_additional = 'completed'
                            THEN COALESCE(sol.price_subtotal, 0)
                                 / NULLIF(sol.product_uom_qty, 0)
                            ELSE 0 END)                                             AS completed_value_ex_vat,

                        /* completed + PAID */
                        SUM(CASE WHEN pt.state_additional = 'completed'
                                      AND isp.sale_line_id IS NOT NULL
                            THEN 1 ELSE 0 END)                                      AS completed_invoiced_qty,
                        SUM(CASE WHEN pt.state_additional = 'completed'
                                      AND isp.sale_line_id IS NOT NULL
                            THEN COALESCE(sol.price_subtotal, 0)
                                 / NULLIF(sol.product_uom_qty, 0)
                            ELSE 0 END)                                             AS completed_invoiced_amount,

                        /* completed + POSTED but NOT PAID */
                        SUM(CASE WHEN pt.state_additional = 'completed'
                                      AND iso.sale_line_id IS NOT NULL
                                      AND isp.sale_line_id IS NULL
                            THEN 1 ELSE 0 END)                                      AS completed_posted_not_paid_qty,
                        SUM(CASE WHEN pt.state_additional = 'completed'
                                      AND iso.sale_line_id IS NOT NULL
                                      AND isp.sale_line_id IS NULL
                            THEN COALESCE(sol.price_subtotal, 0)
                                 / NULLIF(sol.product_uom_qty, 0)
                            ELSE 0 END)                                             AS completed_posted_not_paid_amount,

                        /* completed + NO POSTED INVOICE */
                        SUM(CASE WHEN pt.state_additional = 'completed'
                                      AND iso.sale_line_id IS NULL
                            THEN 1 ELSE 0 END)                                      AS completed_not_invoiced_qty,
                        SUM(CASE WHEN pt.state_additional = 'completed'
                                      AND iso.sale_line_id IS NULL
                            THEN COALESCE(sol.price_subtotal, 0)
                                 / NULLIF(sol.product_uom_qty, 0)
                            ELSE 0 END)                                             AS completed_not_invoiced_amount
                    FROM   project_task       pt
                    LEFT JOIN sale_order_line sol  ON sol.id = pt.sale_line_id
                    LEFT JOIN inv_sol_posted  iso  ON iso.sale_line_id = pt.sale_line_id
                    LEFT JOIN inv_sol_paid    isp  ON isp.sale_line_id = pt.sale_line_id
                    WHERE  pt.active = TRUE
                    GROUP  BY pt.project_id
                )
                SELECT
                    pp.id                                                           AS id,
                    pp.id                                                           AS project_id,
                    COALESCE(
                        pp.name->>'en_US',
                        (SELECT value FROM jsonb_each_text(pp.name) LIMIT 1)
                    )                                                               AS project_name,
                    pp.user_id                                                      AS project_manager_id,
                    pp.department_id                                                AS department_id,
                    pp.company_id                                                   AS company_id,
                    so.id                                                           AS sale_order_id,
                    so.name                                                         AS so_number,
                    so.user_id                                                      AS salesperson_id,
                    so.partner_id                                                   AS customer_id,
                    COALESCE(ps.project_value_ex_vat,  0)                          AS project_value_ex_vat,
                    COALESCE(ps.project_value_inc_vat, 0)                          AS project_value_inc_vat,
                    so.amount_untaxed                                               AS so_total_ex_vat,
                    so.amount_total                                                 AS so_total_inc_vat,
                    COALESCE(ta.tasks_total,                      0)::integer       AS tasks_total,
                    COALESCE(ta.tasks_completed,                  0)::integer       AS tasks_completed,
                    (COALESCE(ta.tasks_total, 0)
                        - COALESCE(ta.tasks_completed, 0))::integer                AS tasks_pending,
                    COALESCE(ta.completed_value_ex_vat,           0)               AS completed_tasks_value_ex_vat,
                    COALESCE(ta.completed_invoiced_qty,            0)::integer      AS completed_invoiced_qty,
                    COALESCE(ta.completed_invoiced_amount,         0)               AS completed_invoiced_amount,
                    COALESCE(ta.completed_posted_not_paid_qty,     0)::integer      AS completed_posted_not_paid_qty,
                    COALESCE(ta.completed_posted_not_paid_amount,  0)               AS completed_posted_not_paid_amount,
                    COALESCE(ta.completed_not_invoiced_qty,        0)::integer      AS completed_not_invoiced_qty,
                    COALESCE(ta.completed_not_invoiced_amount,     0)               AS completed_not_invoiced_amount,
                    so.advance_amount                                               AS advance_amount,

                    pp.create_date::date                                            AS create_date,

                    pp.date                                                         AS deadline,
                    CASE WHEN pp.date IS NOT NULL AND pp.date < CURRENT_DATE
                         THEN (CURRENT_DATE - pp.date)::integer
                         ELSE 0 END                                                AS days_overdue,

                    pid.last_invoice_date                                           AS last_invoice_date,
                    CASE WHEN pid.last_invoice_date IS NOT NULL
                         THEN (CURRENT_DATE - pid.last_invoice_date)::integer
                         ELSE NULL END                                             AS invoice_days_ago,

                    /* completed = all tasks done (tasks_pending derived inline) */
                    (COALESCE(ta.tasks_total, 0) > 0
                     AND COALESCE(ta.tasks_total, 0) = COALESCE(ta.tasks_completed, 0)) AS is_completed,

                    rc.currency_id                                                  AS currency_id
                FROM  project_project  pp
                JOIN  proj_sol         ps  ON ps.project_id = pp.id
                JOIN  sale_order       so  ON so.id         = ps.order_id
                JOIN  res_company      rc  ON rc.id         = pp.company_id
                LEFT JOIN task_agg     ta  ON ta.project_id = pp.id
                LEFT JOIN proj_inv_date pid ON pid.project_id = pp.id
                WHERE pp.active = TRUE
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
        return ['|',
                ('project_manager_id', '=', user.id),
                ('salesperson_id', '=', user.id)]

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
