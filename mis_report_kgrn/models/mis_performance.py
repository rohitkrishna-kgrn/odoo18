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

    # ── Invoicing / collection (period-scoped, delivery-task basis) ───────
    invoices_raised_count     = fields.Integer(string='Invoices Raised (No.)',  readonly=True)
    invoices_raised_amount    = fields.Float(string='Invoices Raised (AED)',    readonly=True)
    payments_collected_amount = fields.Float(string='Payments Collected (AED)', readonly=True)

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
                inv_lines AS (
                    /* posted invoice lines, one row per (SO line, invoice) —
                       basis for period-scoped Invoices Raised / Payments
                       Collected, matched to tasks via their SO line */
                    SELECT
                        solr.order_line_id AS sol_id,
                        am.id              AS move_id,
                        am.invoice_date,
                        am.amount_total,
                        aml.price_subtotal
                    FROM   sale_order_line_invoice_rel solr
                    JOIN   account_move_line aml ON aml.id = solr.invoice_line_id
                    JOIN   account_move      am  ON am.id  = aml.move_id
                    WHERE  am.move_type = 'out_invoice'
                      AND  am.state = 'posted'
                      AND  am.invoice_date IS NOT NULL
                ),
                recv_lines AS (
                    SELECT aml.id AS recv_line_id, aml.move_id
                    FROM   account_move_line aml
                    JOIN   account_account   aa ON aa.id = aml.account_id
                    WHERE  aa.account_type = 'asset_receivable'
                ),
                recon AS (
                    SELECT
                        rl.move_id AS invoice_move_id,
                        pr.max_date,
                        CASE WHEN pr.debit_move_id = rl.recv_line_id
                             THEN pr.debit_amount_currency
                             ELSE pr.credit_amount_currency END AS amount
                    FROM   account_partial_reconcile pr
                    JOIN   recv_lines rl
                           ON rl.recv_line_id = pr.debit_move_id
                           OR rl.recv_line_id = pr.credit_move_id
                ),
                inv_period AS (
                    /* invoiced (ex-VAT) amount raised per SO line, bucketed by
                       the invoice's own month */
                    SELECT sol_id, date_trunc('month', invoice_date)::date AS period_date,
                           SUM(price_subtotal) AS invoiced_ex_vat
                    FROM   inv_lines
                    GROUP  BY sol_id, date_trunc('month', invoice_date)
                ),
                paid_period AS (
                    /* amount actually collected per SO line, bucketed by the
                       payment/reconciliation month (not the invoice month) */
                    SELECT il.sol_id, date_trunc('month', r.max_date)::date AS period_date,
                           SUM(il.price_subtotal * COALESCE(r.amount, 0)
                               / NULLIF(il.amount_total, 0)) AS paid_ex_vat
                    FROM   inv_lines il
                    JOIN   recon r ON r.invoice_move_id = il.move_id
                    GROUP  BY il.sol_id, date_trunc('month', r.max_date)
                ),
                task_sol AS (
                    SELECT pt.id AS task_id, sol.id AS sol_id
                    FROM   project_task pt
                    JOIN   sale_order_line sol ON sol.id = pt.sale_line_id
                ),
                task_invoices AS (
                    /* distinct (task, invoice) touches per month, for the
                       plain Invoices Raised (No.) count */
                    SELECT DISTINCT ts.task_id, il.move_id,
                           date_trunc('month', il.invoice_date)::date AS period_date
                    FROM   task_sol ts
                    JOIN   inv_lines il ON il.sol_id = ts.sol_id
                ),
                task_period AS (
                    SELECT ts.task_id, k.period_date,
                           COALESCE(ip.invoiced_ex_vat, 0) AS invoiced_ex_vat,
                           COALESCE(pp2.paid_ex_vat, 0)    AS paid_ex_vat
                    FROM   task_sol ts
                    JOIN   (
                        SELECT sol_id, period_date FROM inv_period
                        UNION
                        SELECT sol_id, period_date FROM paid_period
                    ) k ON k.sol_id = ts.sol_id
                    LEFT JOIN inv_period  ip  ON ip.sol_id  = ts.sol_id AND ip.period_date  = k.period_date
                    LEFT JOIN paid_period pp2 ON pp2.sol_id = ts.sol_id AND pp2.period_date = k.period_date
                ),
                inv_pay_alloc AS (
                    /* employee's weighted-hours share (this month's hours ÷
                       task's lifetime weighted hours — same allocation basis
                       as delivery_revenue) of invoices raised / paid for
                       tasks they logged time to, restricted to invoice /
                       payment activity dated within that same month */
                    SELECT
                        aal.user_id,
                        date_trunc('month', aal.date)::date AS period_date,
                        SUM(
                            aal.unit_amount * COALESCE(mrr.multiplier, 1)
                            * CASE WHEN tw.total_weighted > 0
                                   THEN COALESCE(tpm.invoiced_ex_vat, 0) / tw.total_weighted
                                   ELSE 0 END
                        ) AS invoices_raised_amount,
                        SUM(
                            aal.unit_amount * COALESCE(mrr.multiplier, 1)
                            * CASE WHEN tw.total_weighted > 0
                                   THEN COALESCE(tpm.paid_ex_vat, 0) / tw.total_weighted
                                   ELSE 0 END
                        ) AS payments_collected_amount
                    FROM   account_analytic_line aal
                    JOIN   task_weight tw ON tw.task_id = aal.task_id
                    LEFT JOIN task_period tpm
                           ON tpm.task_id = aal.task_id
                          AND tpm.period_date = date_trunc('month', aal.date)::date
                    LEFT JOIN hr_employee he5 ON he5.user_id = aal.user_id AND he5.active = TRUE
                    LEFT JOIN mis_revenue_role mrr ON mrr.id = he5.mis_revenue_role_id
                    WHERE  aal.task_id IS NOT NULL
                      AND  aal.unit_amount > 0
                      AND  aal.date IS NOT NULL
                    GROUP  BY aal.user_id, date_trunc('month', aal.date)
                ),
                invoice_count_alloc AS (
                    /* plain (non-fractional) count: distinct invoices raised
                       this month for any task this employee logged hours to
                       this month */
                    SELECT user_id, period_date, COUNT(*) AS invoices_raised_count
                    FROM (
                        SELECT DISTINCT aal.user_id,
                               ti.period_date,
                               ti.move_id
                        FROM   account_analytic_line aal
                        JOIN   task_invoices ti
                               ON ti.task_id = aal.task_id
                              AND ti.period_date = date_trunc('month', aal.date)::date
                        WHERE  aal.task_id IS NOT NULL
                          AND  aal.unit_amount > 0
                          AND  aal.date IS NOT NULL
                    ) x
                    GROUP BY user_id, period_date
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
                        COALESCE(s.revenue, 0) AS sales_revenue,
                        COALESCE(ipa.invoices_raised_amount, 0)    AS invoices_raised_amount,
                        COALESCE(ipa.payments_collected_amount, 0) AS payments_collected_amount,
                        COALESCE(ica.invoices_raised_count, 0)     AS invoices_raised_count
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
                    LEFT JOIN inv_pay_alloc ipa ON ipa.user_id = e.user_id AND ipa.period_date = gs.period_date::date
                    LEFT JOIN invoice_count_alloc ica ON ica.user_id = e.user_id AND ica.period_date = gs.period_date::date
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
                    invoices_raised_count,
                    invoices_raised_amount,
                    payments_collected_amount,
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
            ),
            task_invoice_rows AS (
                /* distinct posted invoices touching each task's SO line —
                   basis for Invoice Details / Payment Reference / Balance */
                SELECT DISTINCT
                    pt6.id AS task_id,
                    am6.id AS invoice_id,
                    am6.name AS invoice_name,
                    NULLIF(am6.payment_reference, '') AS payment_reference,
                    am6.amount_residual AS balance
                FROM   project_task pt6
                JOIN   sale_order_line sol6 ON sol6.id = pt6.sale_line_id
                JOIN   sale_order_line_invoice_rel solr6 ON solr6.order_line_id = sol6.id
                JOIN   account_move_line aml6 ON aml6.id = solr6.invoice_line_id
                JOIN   account_move      am6  ON am6.id  = aml6.move_id
                WHERE  am6.move_type = 'out_invoice' AND am6.state = 'posted'
            ),
            task_inv_agg AS (
                SELECT
                    task_id,
                    STRING_AGG(DISTINCT invoice_name, ', ') AS invoice_details,
                    STRING_AGG(DISTINCT payment_reference, ', ') AS payment_reference,
                    SUM(balance) AS balance
                FROM   task_invoice_rows
                GROUP  BY task_id
            )
            SELECT
                CASE WHEN LEFT(pp.name::text, 1) = '{'
                     THEN (pp.name::jsonb)->>'en_US' ELSE pp.name::text END AS project_name,
                CASE WHEN LEFT(pt.name::text, 1) = '{'
                     THEN (pt.name::jsonb)->>'en_US' ELSE pt.name::text END AS task_name,
                COALESCE(rp4.complete_name, rp4.name, '') AS customer,
                COALESCE(tia.invoice_details, '') AS invoice_details,
                COALESCE(tia.payment_reference, '') AS payment_reference,
                COALESCE(tia.balance, 0) AS balance,
                SUM(aal.unit_amount) AS hours,
                SUM(aal.unit_amount * COALESCE(mrr.multiplier, 1)) AS weighted,
                MAX(tw.task_value) AS revenue
            FROM   account_analytic_line aal
            JOIN   task_weight tw ON tw.task_id = aal.task_id
            JOIN   project_task pt ON pt.id = aal.task_id
            LEFT JOIN project_project pp ON pp.id = pt.project_id
            LEFT JOIN sale_order_line sol4 ON sol4.id = pt.sale_line_id
            LEFT JOIN sale_order      so4  ON so4.id  = sol4.order_id
            LEFT JOIN res_partner     rp4  ON rp4.id  = so4.partner_id
            LEFT JOIN task_inv_agg    tia  ON tia.task_id = pt.id
            LEFT JOIN hr_employee he3 ON he3.user_id = aal.user_id AND he3.active = TRUE
            LEFT JOIN mis_revenue_role mrr ON mrr.id = he3.mis_revenue_role_id
            WHERE  aal.user_id = %s
              AND  aal.task_id IS NOT NULL
              AND  aal.unit_amount > 0
              AND  date_trunc('month', aal.date) = date_trunc('month', %s::date)
            GROUP  BY pt.id, pt.name, pp.name, rp4.complete_name, rp4.name,
                      tia.invoice_details, tia.payment_reference, tia.balance
            ORDER  BY revenue DESC
        """, (uid, period_date))
        delivery = [{
            'project': r[0] or '',
            'task': r[1] or '',
            'customer': r[2] or '',
            'invoice_details': r[3] or '',
            'balance': r[5] or 0.0,
            'hours': round(r[6] or 0.0, 2),
            'amount': r[8] or 0.0,
        } for r in cr.fetchall()]

        return {
            'sales': sales,
            'delivery': delivery,
            'sales_total': sum(s['amount'] for s in sales),
            'delivery_total': sum(d['amount'] for d in delivery),
        }

    @api.model
    def get_revenue_breakdown_bulk(self, items):
        """Batch version of get_revenue_breakdown for the list-view's inline
        per-row detail dropdown / "task detail" export. `items` is a list of
        {key, employee_id, user_id, period_date}; returns {key: breakdown}."""
        result = {}
        for item in items:
            result[item['key']] = self.get_revenue_breakdown(
                item.get('employee_id'), item.get('user_id'), item.get('period_date')
            )
        return result
