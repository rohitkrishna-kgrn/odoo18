from odoo import models, fields, api, tools


class MisPerformanceLine(models.Model):
    """
    KGRN Performance Management Framework (HR-PMS-001).

    One row per (applicable employee × month) from the policy effective
    date (2026-07-01) to the current month. Combines two revenue sources:

      • delivery_revenue — weighted-timesheet revenue attribution for
        Audit/Tax/Accounting/E-Invoicing (Operations) teams. Each analytic
        line contributes  hours × role_multiplier × (task_value / task_total_weighted_hours),
        allocated to the month the time was logged.

      • sales_revenue — gross (untaxed) value of confirmed sale orders,
        attributed to the salesperson by order-confirmation month.

    Obligation & target follow the office location (UAE 3×/5×, India 5×/10×)
    with a new-joiner ramp-up (month 1 = 1×, month 2 = 2×, month 3+ = full).
    Consecutive non-performance months drive the escalation stage.
    """
    _name = 'mis.performance.line'
    _description = 'MIS Performance Management'
    _auto = False
    _rec_name = 'employee_name'
    _order = 'department_id, employee_name, period_date'

    # ── Identity ─────────────────────────────────────────────────────────
    employee_id      = fields.Many2one('hr.employee',   string='Employee',       readonly=True)
    employee_name    = fields.Char(string='Employee',                            readonly=True)
    user_id          = fields.Many2one('res.users',     string='User',           readonly=True)
    department_id    = fields.Many2one('hr.department', string='Department',      readonly=True)
    performance_team = fields.Char(string='Team',                                 readonly=True)
    office_location  = fields.Char(string='Office',                               readonly=True)

    # ── Period ───────────────────────────────────────────────────────────
    period_date      = fields.Date(string='Month',                               readonly=True)
    period_label     = fields.Char(string='Period',                              readonly=True)

    # ── CTC / obligation / target ────────────────────────────────────────
    monthly_ctc         = fields.Float(string='Monthly CTC',        readonly=True)
    annual_ctc          = fields.Float(string='Annual CTC',         readonly=True)
    monthly_obligation  = fields.Float(string='Monthly Obligation', readonly=True)
    annual_target       = fields.Float(string='Annual Target',      readonly=True)

    # ── Revenue ──────────────────────────────────────────────────────────
    sales_revenue    = fields.Float(string='Sales Revenue',     readonly=True)
    delivery_revenue = fields.Float(string='Delivery Revenue',  readonly=True)
    total_revenue    = fields.Float(string='Total Revenue',     readonly=True)
    achievement_pct  = fields.Float(string='Achievement %',     readonly=True)

    # ── Status / escalation ──────────────────────────────────────────────
    is_met               = fields.Boolean(string='Met Obligation',      readonly=True)
    consecutive_non_perf = fields.Integer(string='Consec. Non-Perf Months', readonly=True)
    escalation_stage     = fields.Char(string='Escalation Stage',        readonly=True)

    currency_id     = fields.Many2one('res.currency', string='Currency', readonly=True)
    ctc_currency_id = fields.Many2one('res.currency', string='CTC Currency', readonly=True)

    # ─────────────────────────────────────────────────────────────────────
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH emp AS (
                    SELECT
                        he.id            AS employee_id,
                        he.user_id       AS user_id,
                        he.department_id AS department_id,
                        he.company_id    AS company_id,
                        ct.company_id    AS ctc_company_id,
                        he.name          AS employee_name,
                        he.mis_performance_team AS performance_team,
                        /* office from res.users.country (leave mgmt);
                           'india' → india, anything else (e.g. 'dubai') → uae;
                           fall back to the stored field when country is blank */
                        CASE
                            WHEN lower(u.country) = 'india' THEN 'india'
                            WHEN u.country IS NOT NULL AND u.country <> '' THEN 'uae'
                            ELSE COALESCE(he.mis_office_location, 'uae')
                        END AS office_location,
                        /* CTC & targets shown in AED for everyone: UAE wages are
                           already AED; INR wages are converted using the latest
                           INR→AED rate from res_currency_rate (Odoo currency
                           rates). Manual mis_annual_ctc overrides are assumed AED. */
                        COALESCE(
                            NULLIF(he.mis_annual_ctc, 0),
                            ct.wage * 12 * (
                                CASE WHEN ccur.name = 'INR'
                                     THEN COALESCE(
                                        (SELECT 1.0 / r.rate
                                         FROM res_currency_rate r
                                         JOIN res_currency c ON c.id = r.currency_id
                                         WHERE c.name = 'INR'
                                         ORDER BY r.name DESC LIMIT 1), 0.0385)
                                     ELSE 1 END
                            ),
                            0
                        ) AS annual_ctc,
                        (SELECT id FROM res_currency WHERE name = 'AED' ORDER BY id LIMIT 1) AS ctc_currency_id,
                        u.create_date            AS user_created,
                        he.mis_ramp_start_date  AS ramp_start
                    FROM hr_employee he
                    LEFT JOIN LATERAL (
                        SELECT c.wage, c.company_id
                        FROM   hr_contract c
                        WHERE  c.employee_id = he.id
                          AND  c.state = 'open'
                        ORDER  BY c.date_start DESC
                        LIMIT  1
                    ) ct ON TRUE
                    LEFT JOIN res_company  cco  ON cco.id  = ct.company_id
                    LEFT JOIN res_currency ccur ON ccur.id = cco.currency_id
                    LEFT JOIN res_users u ON u.id = he.user_id
                    WHERE he.active = TRUE
                      AND he.mis_performance_applicable = TRUE
                ),
                inv_agg AS (
                    /* posted invoiced (ex-VAT) amount per SO line — same
                       revenue basis as the Project Wise / Outstanding menus */
                    SELECT solr.order_line_id AS sol_id,
                           SUM(CASE WHEN am.state = 'posted'
                                    THEN aml.price_subtotal ELSE 0 END) AS invoiced_ex_vat
                    FROM   sale_order_line_invoice_rel solr
                    JOIN   account_move_line aml ON aml.id = solr.invoice_line_id
                    JOIN   account_move      am  ON am.id  = aml.move_id
                    WHERE  am.move_type = 'out_invoice'
                    GROUP  BY solr.order_line_id
                ),
                task_weight AS (
                    /* per task: recognised value = invoiced ex-VAT (like Project
                       Wise) and total weighted hours (z) */
                    SELECT
                        pt.id AS task_id,
                        COALESCE(ia.invoiced_ex_vat, 0) AS task_value,
                        SUM(aal.unit_amount * COALESCE(mrr.multiplier, 1)) AS total_weighted
                    FROM project_task pt
                    JOIN sale_order_line sol ON sol.id = pt.sale_line_id
                    LEFT JOIN inv_agg ia ON ia.sol_id = sol.id
                    JOIN account_analytic_line aal ON aal.task_id = pt.id AND aal.unit_amount > 0
                    LEFT JOIN hr_employee he2 ON he2.user_id = aal.user_id AND he2.active = TRUE
                    LEFT JOIN mis_revenue_role mrr ON mrr.id = he2.mis_revenue_role_id
                    GROUP BY pt.id, ia.invoiced_ex_vat
                ),
                delivery AS (
                    /* weighted-timesheet revenue per (user, month) */
                    SELECT
                        aal.user_id,
                        date_trunc('month', aal.date)::date AS period_date,
                        SUM(
                            aal.unit_amount * COALESCE(mrr.multiplier, 1)
                            * CASE WHEN tw.total_weighted > 0
                                   THEN tw.task_value / tw.total_weighted
                                   ELSE 0 END
                        ) AS revenue
                    FROM account_analytic_line aal
                    JOIN task_weight tw ON tw.task_id = aal.task_id
                    LEFT JOIN hr_employee he3 ON he3.user_id = aal.user_id AND he3.active = TRUE
                    LEFT JOIN mis_revenue_role mrr ON mrr.id = he3.mis_revenue_role_id
                    WHERE aal.task_id IS NOT NULL
                      AND aal.unit_amount > 0
                      AND aal.date IS NOT NULL
                    GROUP BY aal.user_id, date_trunc('month', aal.date)
                ),
                sales AS (
                    /* confirmed-SO gross (untaxed, AED) revenue matched to the
                       employee by salesperson user OR by matching name */
                    SELECT
                        e.employee_id,
                        date_trunc('month', so.date_order)::date AS period_date,
                        SUM(so.amount_untaxed) AS revenue
                    FROM sale_order so
                    JOIN res_users   su ON su.id = so.user_id
                    JOIN res_partner sp ON sp.id = su.partner_id
                    JOIN emp e ON ( e.user_id = so.user_id
                                    OR lower(btrim(e.employee_name)) = lower(btrim(sp.name)) )
                    WHERE so.state IN ('sale', 'done')
                    GROUP BY e.employee_id, date_trunc('month', so.date_order)
                ),
                base AS (
                    SELECT
                        e.employee_id, e.user_id, e.department_id, e.company_id,
                        e.ctc_company_id, e.ctc_currency_id,
                        e.employee_name, e.performance_team, e.office_location,
                        e.annual_ctc, e.ramp_start,
                        gs.period_date::date AS period_date,
                        (e.annual_ctc / 12.0) AS monthly_ctc,
                        CASE WHEN e.ramp_start IS NULL THEN 999
                             ELSE (
                                (EXTRACT(YEAR FROM gs.period_date) * 12 + EXTRACT(MONTH FROM gs.period_date))
                              - (EXTRACT(YEAR  FROM e.ramp_start) * 12 + EXTRACT(MONTH FROM e.ramp_start))
                              + 1
                             )::int
                        END AS months_employed,
                        COALESCE(d.revenue, 0) AS delivery_revenue,
                        COALESCE(s.revenue, 0) AS sales_revenue
                    FROM emp e
                    /* per-employee month series: from the later of the rolling
                       12-month floor and the user's creation month, up to now */
                    CROSS JOIN LATERAL generate_series(
                        GREATEST(
                            date_trunc('month', CURRENT_DATE) - INTERVAL '11 months',
                            date_trunc('month', COALESCE(e.user_created, CURRENT_DATE))
                        ),
                        date_trunc('month', CURRENT_DATE),
                        INTERVAL '1 month'
                    ) AS gs(period_date)
                    LEFT JOIN delivery d ON d.user_id = e.user_id AND d.period_date = gs.period_date::date
                    LEFT JOIN sales    s ON s.employee_id = e.employee_id AND s.period_date = gs.period_date::date
                ),
                calc AS (
                    SELECT b.*,
                        (b.delivery_revenue + b.sales_revenue) AS total_revenue,
                        CASE b.office_location WHEN 'uae' THEN 3 WHEN 'india' THEN 5 ELSE 3 END AS base_monthly_mult,
                        CASE b.office_location WHEN 'uae' THEN 5 WHEN 'india' THEN 10 ELSE 5 END AS annual_mult
                    FROM base b
                    WHERE b.months_employed >= 1
                ),
                fin AS (
                    SELECT c.*,
                        /* obligation & target in AED (CTC already converted) */
                        (c.monthly_ctc * CASE
                            WHEN c.months_employed = 1 THEN 1
                            WHEN c.months_employed = 2 THEN 2
                            ELSE c.base_monthly_mult END) AS monthly_obligation,
                        (c.annual_ctc * c.annual_mult) AS annual_target,
                        CASE
                            WHEN (c.monthly_ctc * CASE
                                WHEN c.months_employed = 1 THEN 1
                                WHEN c.months_employed = 2 THEN 2
                                ELSE c.base_monthly_mult END) > 0
                            THEN (c.total_revenue >= (c.monthly_ctc * CASE
                                WHEN c.months_employed = 1 THEN 1
                                WHEN c.months_employed = 2 THEN 2
                                ELSE c.base_monthly_mult END))
                            ELSE TRUE
                        END AS is_met
                    FROM calc c
                ),
                streak1 AS (
                    SELECT f.*,
                        SUM(CASE WHEN f.is_met THEN 1 ELSE 0 END)
                            OVER (PARTITION BY f.employee_id ORDER BY f.period_date
                                  ROWS UNBOUNDED PRECEDING) AS island
                    FROM fin f
                ),
                streak2 AS (
                    SELECT s1.*,
                        ROW_NUMBER() OVER (PARTITION BY s1.employee_id, s1.island
                                           ORDER BY s1.period_date) AS pos
                    FROM streak1 s1
                )
                SELECT
                    ROW_NUMBER() OVER (ORDER BY department_id, employee_name, period_date) AS id,
                    employee_id,
                    user_id,
                    department_id,
                    employee_name,
                    performance_team,
                    CASE office_location
                        WHEN 'uae'   THEN 'UAE'
                        WHEN 'india' THEN 'India'
                        ELSE COALESCE(office_location, '—')
                    END AS office_location,
                    period_date,
                    TO_CHAR(period_date, 'Mon YYYY') AS period_label,
                    monthly_ctc,
                    annual_ctc,
                    monthly_obligation,
                    annual_target,
                    sales_revenue,
                    delivery_revenue,
                    total_revenue,
                    CASE WHEN monthly_obligation > 0
                         THEN total_revenue / monthly_obligation * 100
                         ELSE 0 END AS achievement_pct,
                    is_met,
                    CASE WHEN is_met THEN 0
                         WHEN island = 0 THEN pos
                         ELSE pos - 1 END AS consecutive_non_perf,
                    CASE
                        WHEN is_met THEN 'On Track'
                        WHEN (CASE WHEN island = 0 THEN pos ELSE pos - 1 END) = 1
                            THEN '1st Month — Verbal Flag'
                        WHEN (CASE WHEN island = 0 THEN pos ELSE pos - 1 END) = 2
                            THEN '2nd Month — Written Advisory'
                        ELSE '3rd+ Month — Warning + PIP'
                    END AS escalation_stage,
                    (SELECT id FROM res_currency WHERE name = 'AED' ORDER BY id LIMIT 1) AS currency_id,
                    ctc_currency_id
                FROM streak2
            )
        """ % self._table)

    # ── Revenue breakdown (for the OWL wizard) ───────────────────────────
    @api.model
    def get_revenue_breakdown(self, employee_id, user_id, period_date):
        """Return the individual sale orders (sales) and tasks (delivery) that
        make up an employee's revenue for the given month. `period_date` is any
        date within the month ('YYYY-MM-DD')."""
        emp = self.env['hr.employee'].browse(employee_id)
        emp_name = emp.name or ''
        uid = user_id or 0
        cr = self.env.cr

        # ── Sales: confirmed SOs matched by salesperson user OR name ──────
        cr.execute("""
            SELECT so.name,
                   so.date_order::date,
                   COALESCE(rp.complete_name, rp.name, '') AS customer,
                   so.amount_untaxed
            FROM   sale_order so
            LEFT JOIN res_partner rp ON rp.id = so.partner_id
            LEFT JOIN res_users   su ON su.id = so.user_id
            LEFT JOIN res_partner sp ON sp.id = su.partner_id
            WHERE  so.state IN ('sale', 'done')
              AND  date_trunc('month', so.date_order) = date_trunc('month', %s::date)
              AND  ( so.user_id = %s
                     OR lower(btrim(sp.name)) = lower(btrim(%s)) )
            ORDER  BY so.amount_untaxed DESC
        """, (period_date, uid, emp_name))
        sales = [{
            'ref': r[0] or '',
            'date': str(r[1] or ''),
            'customer': r[2] or '',
            'amount': r[3] or 0.0,
        } for r in cr.fetchall()]

        # ── Delivery: weighted-timesheet revenue per task (invoiced basis) ─
        cr.execute("""
            WITH inv_agg AS (
                SELECT solr.order_line_id AS sol_id,
                       SUM(CASE WHEN am.state = 'posted' THEN aml.price_subtotal ELSE 0 END) AS invoiced_ex_vat
                FROM   sale_order_line_invoice_rel solr
                JOIN   account_move_line aml ON aml.id = solr.invoice_line_id
                JOIN   account_move      am  ON am.id  = aml.move_id
                WHERE  am.move_type = 'out_invoice'
                GROUP  BY solr.order_line_id
            ),
            task_weight AS (
                SELECT pt.id AS task_id,
                       COALESCE(ia.invoiced_ex_vat, 0) AS task_value,
                       SUM(aal.unit_amount * COALESCE(mrr.multiplier, 1)) AS total_weighted
                FROM   project_task pt
                JOIN   sale_order_line sol ON sol.id = pt.sale_line_id
                LEFT JOIN inv_agg ia ON ia.sol_id = sol.id
                JOIN   account_analytic_line aal ON aal.task_id = pt.id AND aal.unit_amount > 0
                LEFT JOIN hr_employee he2 ON he2.user_id = aal.user_id AND he2.active = TRUE
                LEFT JOIN mis_revenue_role mrr ON mrr.id = he2.mis_revenue_role_id
                GROUP  BY pt.id, ia.invoiced_ex_vat
            )
            SELECT
                CASE WHEN LEFT(pt.name::text, 1) = '{'
                     THEN (pt.name::jsonb)->>'en_US' ELSE pt.name::text END AS task_name,
                SUM(aal.unit_amount) AS hours,
                SUM(aal.unit_amount * COALESCE(mrr.multiplier, 1)) AS weighted,
                SUM(aal.unit_amount * COALESCE(mrr.multiplier, 1)
                    * CASE WHEN tw.total_weighted > 0
                           THEN tw.task_value / tw.total_weighted ELSE 0 END) AS revenue
            FROM   account_analytic_line aal
            JOIN   task_weight tw ON tw.task_id = aal.task_id
            JOIN   project_task pt ON pt.id = aal.task_id
            LEFT JOIN hr_employee he3 ON he3.user_id = aal.user_id AND he3.active = TRUE
            LEFT JOIN mis_revenue_role mrr ON mrr.id = he3.mis_revenue_role_id
            WHERE  aal.user_id = %s
              AND  aal.task_id IS NOT NULL
              AND  aal.unit_amount > 0
              AND  date_trunc('month', aal.date) = date_trunc('month', %s::date)
            GROUP  BY pt.id, pt.name
            ORDER  BY revenue DESC
        """, (uid, period_date))
        delivery = [{
            'task': r[0] or '',
            'hours': round(r[1] or 0.0, 2),
            'weighted': round(r[2] or 0.0, 2),
            'amount': r[3] or 0.0,
        } for r in cr.fetchall()]

        return {
            'sales': sales,
            'delivery': delivery,
            'sales_total': sum(s['amount'] for s in sales),
            'delivery_total': sum(d['amount'] for d in delivery),
        }
