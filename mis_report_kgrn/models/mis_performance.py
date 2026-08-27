from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, tools


# ── Timesheet-weighted revenue allocation (HR-PMS-001 §E1) ────────────────
# The single agreed rule for splitting one task's revenue between the several
# people who worked on it: each contributor's share is the hours THEY logged
# to that task divided by the total hours logged to it by everyone, so a
# cross-PM/cross-team engagement pays out in proportion to effort instead of
# being sliced evenly. Hours are scaled by the contributor's MIS Revenue Role
# multiplier (Partner 3x … Trainee 0.5x) when one is set on their employee
# record — no employee has one today, so the split is currently pure logged
# hours — which is the same weighted-hours formula the Task Revenue report
# (mis.project.revenue) already uses, so the two reports never disagree.
#
# Shares always sum to 1 per task, so no payment is ever duplicated or lost
# across employees. Hours are counted over the LIFE of the task, not per
# month: revenue is bucketed by the month it was COLLECTED, which is usually
# months after the work, and a month-scoped denominator would drop the
# revenue of anyone who logged nothing that month.
_TASK_WEIGHT_CTES = """
emp_role AS (
    /* one Revenue Role multiplier per user. DISTINCT ON guards against a
       user holding more than one active employee record — none do today,
       but a plain join would silently double that user's weight. */
    SELECT DISTINCT ON (he.user_id)
           he.user_id                     AS user_id,
           COALESCE(mrr.multiplier, 1.0)  AS multiplier
    FROM   hr_employee he
    LEFT   JOIN mis_revenue_role mrr ON mrr.id = he.mis_revenue_role_id
    WHERE  he.active = TRUE AND he.user_id IS NOT NULL
    ORDER  BY he.user_id, he.id
),
task_user_weight AS (
    /* per (task, contributor): hours logged to the task x the contributor's
       role multiplier — the numerator of that person's share */
    SELECT
        aal.task_id                                          AS task_id,
        aal.user_id                                          AS user_id,
        SUM(aal.unit_amount)                                 AS hours,
        SUM(aal.unit_amount) * COALESCE(er.multiplier, 1.0)  AS user_weighted
    FROM   account_analytic_line aal
    LEFT   JOIN emp_role er ON er.user_id = aal.user_id
    WHERE  aal.task_id   IS NOT NULL
      AND  aal.user_id   IS NOT NULL
      AND  aal.unit_amount > 0
    GROUP  BY aal.task_id, aal.user_id, er.multiplier
),
task_weight AS (
    /* per task: the sum of every contributor's weight — the denominator, so
       user_weighted / total_weighted is that person's fraction of the task
       and the fractions of any one payment add up to exactly 1 */
    SELECT task_id, SUM(user_weighted) AS total_weighted
    FROM   task_user_weight
    GROUP  BY task_id
)"""


def _task_weight_ctes(indent):
    """_TASK_WEIGHT_CTES re-indented to sit inside a WITH clause at `indent`
    spaces. Must be placed before any CTE that references task_user_weight /
    task_weight — Postgres only resolves backwards within a WITH."""
    pad = ' ' * indent
    return '\n'.join(pad + ln if ln else ln
                     for ln in _TASK_WEIGHT_CTES.strip('\n').split('\n'))


class MisPerformanceLine(models.Model):
    """
    KGRN Performance Management Framework (HR-PMS-001).

    One row per (applicable employee × month) from the policy effective
    date (2026-07-01) to the current month. Combines two revenue sources,
    both sourced from posted customer invoices that have actually been
    (at least partially) COLLECTED, bucketed by the month the payment/
    reconciliation happened (not invoice date, not order date, not
    timesheet date), and both split across a task's members in proportion
    to the TIME each of them logged to that task (see _TASK_WEIGHT_CTES —
    hours logged ÷ total hours logged by everyone, scaled by the employee's
    MIS Revenue Role multiplier where one is set) — the same
    non-duplicating split for both, differing only in WHEN the collection
    happened relative to the date the task's PROJECT reached the "Done"
    stage (see the project_done CTE; NULL for projects not yet Done):

      • sales_revenue — amount collected while the project was still
        open (payment date < the project's Done date, or the project has
        never been Done) — an advance against work in progress.

      • delivery_revenue — amount collected on or after the project's
        Done date — the final settlement once work is delivered.

    Shares of a given payment sum to exactly the collected amount, so the
    same payment is never duplicated across employees, projects, or the
    sales/delivery split — a cross-PM engagement pays each contributor for
    their measured effort, and the slices still add up to the whole. Partial payments count pro-rata (a 60%-paid
    invoice contributes 60% of its value) via the same reconciliation-based
    split used by the Payments Collected column.

    Obligation & target follow the office location (UAE 3×/5×, India 5×/10×)
    with a new-joiner ramp-up: a joiner's monthly obligation is 1× CTC in
    their first calendar month, 2× in their second and the full location
    multiplier from their third month on, anchored on the employee's
    Ramp-up Start Date or, when HR has not set one, their first contract
    start date. Months before that start date keep their row and are scored
    at the standard obligation, exactly as they were before the ramp-up
    existed — the report never drops history.
    Consecutive non-performance months drive the escalation stage.

    Status and Escalation Stage are a SEPARATE, independent pair scored on
    payments_collected_amount ("Payment Collected") — NOT on Achievement %,
    Delivered Value or Invoices Raised — but against the SAME ramped
    threshold, so a new joiner is never escalated toward a Warning Notice on
    a target that has not taken effect yet. Status is this
    month alone (Below Minimum < CTC, At Risk < CTC x mult, else On Track);
    Escalation Stage counts consecutive below-target months (Below Minimum
    OR At Risk — i.e. anything short of On Track) and is
    cleared and reset to zero by any On Track month, so escalation never
    carries across an On Track month.
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

    # ── New-joiner ramp-up (HR-PMS-001 §E1) ──────────────────────────────
    # Why this month's obligation is what it is. Sourced from the employee's
    # Ramp-up Start Date when HR has set one, otherwise their first contract
    # start date; blank for the handful of employees with neither, who are
    # scored at the full obligation.
    ramp_start_date  = fields.Date(string='Ramp-up Start',   readonly=True)
    months_employed  = fields.Integer(string='Month No.',    readonly=True)
    ramp_stage       = fields.Char(string='Ramp-up Stage',   readonly=True)

    # ── Revenue ──────────────────────────────────────────────────────────
    sales_revenue    = fields.Float(string='Sales Revenue',     readonly=True)
    delivery_revenue = fields.Float(string='Delivery Revenue',  readonly=True)
    total_revenue    = fields.Float(string='Total Revenue',     readonly=True)
    achievement_pct  = fields.Float(string='Achievement %',     readonly=True)

    # ── Invoicing / collection (period-scoped, delivery-task basis) ───────
    invoices_raised_count     = fields.Integer(string='Invoices Raised (No.)',  readonly=True)
    invoices_raised_amount    = fields.Float(string='Invoices Raised (AED)',    readonly=True)
    payments_collected_amount = fields.Float(string='Payments Collected (AED)', readonly=True)

    # ── Work delivered: the VALUE OF THE WORK COMPLETED in the month —
    #    each task's share of its sale-order line (contracted, ex-VAT),
    #    recognised in the month its PROJECT reached the "Done" stage and
    #    split among the task's members in proportion to the hours each
    #    logged to it. Independent of whether the client has paid: a job
    #    finished in January and settled in March is January's delivery.
    #    Follows the dashboard's date filter on the same completion-date
    #    basis (see get_period_revenue_amounts). ─────────────────────────────
    work_completed_value = fields.Float(string='Work Delivered (AED)', readonly=True)

    # ── Status / escalation ──────────────────────────────────────────────
    is_met               = fields.Boolean(string='Met Obligation',      readonly=True)
    consecutive_non_perf = fields.Integer(string='Consec. Non-Perf Months', readonly=True)
    escalation_stage     = fields.Char(string='Escalation Stage',        readonly=True)
    rag_status           = fields.Char(string='Status',                  readonly=True)

    # ── Payment-Collected status & escalation (HR-PMS-001 §Status) ───────
    # Independent of the is_met / consecutive_non_perf pair above: those
    # score total_revenue against monthly_obligation, whereas these score
    # payments_collected_amount ("Payment Collected"). Both are measured
    # against the same ramp-adjusted CTC x multiplier threshold, so
    # min_ctc_obligation and monthly_obligation now carry the same number
    # and differ only in which revenue figure is held up against them.
    min_ctc_obligation      = fields.Float(string='Min. CTC Obligation',   readonly=True)
    performance_status      = fields.Char(string='Status',                 readonly=True)
    consecutive_below_target = fields.Integer(
        string='Consec. Below-Target Months', readonly=True)

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
                        /* New-joiner ramp-up anchor. The manual MIS field wins
                           so HR can correct a re-hire or a mid-contract
                           transfer, but it is left blank for everyone in
                           practice, so the real source is hr.employee's
                           first_contract_date (stored, and verified equal to
                           MIN(hr_contract.date_start) for every applicable
                           employee). Without this fallback the whole ramp-up
                           is dead code: no employee has the manual date set,
                           so every month scored as 999 = full obligation. */
                        COALESCE(he.mis_ramp_start_date,
                                 he.first_contract_date) AS ramp_start
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
                sol_task_count AS (
                    /* tasks sharing a sale-order line — many KGRN engagements
                       (e.g. a monthly retainer) invoice a whole month's
                       deliverables on a single SO line, so that line's value
                       must be split equally across every task under it
                       instead of counted in full for each one */
                    SELECT sol.id AS sol_id, COUNT(DISTINCT pt.id) AS task_count
                    FROM   sale_order_line sol
                    JOIN   project_task pt ON pt.sale_line_id = sol.id
                    GROUP  BY sol.id
                ),
                project_done AS (
                    /* the date each project reached the "Done" stage — the
                       delivery boundary for Sales vs Delivery Revenue and the
                       month a task's value counts as Work Delivered.
                       project_project.completed_date is only stamped by the
                       "Mark as Done" / task-approval buttons and is empty for
                       every project in this database, so the authoritative
                       source is the chatter's tracked stage change into Done
                       (the most recent one, in case a project was reopened).
                       Projects not currently in the Done stage are excluded
                       altogether: their collections all count as Sales. */
                    SELECT
                        pp.id AS project_id,
                        COALESCE(
                            pp.completed_date,
                            (SELECT MAX(mm.date)
                             FROM   mail_tracking_value mtv
                             JOIN   mail_message mm ON mm.id = mtv.mail_message_id
                             JOIN   ir_model_fields imf ON imf.id = mtv.field_id
                             WHERE  mm.model  = 'project.project'
                               AND  mm.res_id = pp.id
                               AND  imf.model = 'project.project'
                               AND  imf.name  = 'stage_id'
                               AND  mtv.new_value_char = 'Done')
                        ) AS done_date
                    FROM   project_project pp
                    JOIN   project_project_stage pps ON pps.id = pp.stage_id
                    WHERE  (CASE WHEN LEFT(pps.name::text, 1) = '{'
                                 THEN (pps.name::jsonb) ->> 'en_US'
                                 ELSE pps.name::text END) = 'Done'
                ),
%(task_weights)s,
                task_sol AS (
                    SELECT pt.id AS task_id, sol.id AS sol_id
                    FROM   project_task pt
                    JOIN   sale_order_line sol ON sol.id = pt.sale_line_id
                ),
                inv_lines AS (
                    /* posted invoice lines, one row per (SO line, invoice) —
                       basis for Sales/Delivery Revenue and the period-scoped
                       Invoices Raised / Payments Collected columns */
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
                inv_period AS (
                    /* invoiced (ex-VAT) amount raised per SO line, bucketed by
                       the invoice's own month — basis for Sales/Delivery
                       Revenue */
                    SELECT sol_id, date_trunc('month', invoice_date)::date AS period_date,
                           SUM(price_subtotal) AS invoiced_ex_vat
                    FROM   inv_lines
                    GROUP  BY sol_id, date_trunc('month', invoice_date)
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
                paid_task_events AS (
                    /* each task's equal share of every reconciled payment
                       against its SO line (divided by the number of tasks
                       sharing that line, so a shared retainer line isn't
                       counted in full for every task), at full
                       (non-truncated) payment-date granularity, tagged
                       with the date its PROJECT reached the Done stage —
                       needed to tell which side of "done" each payment
                       falls on before bucketing by month below */
                    SELECT
                        ts.task_id,
                        r.max_date AS payment_date,
                        pd.done_date,
                        (il.price_subtotal * COALESCE(r.amount, 0)
                         / NULLIF(il.amount_total, 0))
                        / NULLIF(stc.task_count, 0) AS paid_ex_vat
                    FROM   task_sol ts
                    JOIN   inv_lines il ON il.sol_id = ts.sol_id
                    JOIN   recon r ON r.invoice_move_id = il.move_id
                    JOIN   project_task pt7 ON pt7.id = ts.task_id
                    LEFT JOIN project_done pd ON pd.project_id = pt7.project_id
                    JOIN   sol_task_count stc ON stc.sol_id = ts.sol_id
                ),
                task_paid_split AS (
                    /* per (task, payment month): collected amount split into
                       "sales" (paid while the project was still open, or the
                       project has never reached Done — an advance) vs
                       "delivery" (paid on/after the project's Done date —
                       the final settlement) */
                    SELECT
                        task_id,
                        date_trunc('month', payment_date)::date AS period_date,
                        SUM(CASE WHEN done_date IS NULL OR payment_date < done_date
                                 THEN paid_ex_vat ELSE 0 END) AS sales_paid,
                        SUM(CASE WHEN done_date IS NOT NULL AND payment_date >= done_date
                                 THEN paid_ex_vat ELSE 0 END) AS delivery_paid
                    FROM   paid_task_events
                    GROUP  BY task_id, date_trunc('month', payment_date)
                ),
                delivery AS (
                    /* final-settlement (post-completion) collected revenue
                       per (user, payment month): each task's delivery_paid
                       for the month is split among its members in proportion
                       to the hours each logged to the task —
                       shares sum to exactly the collected amount, so the
                       same payment is never duplicated across employees or
                       projects */
                    SELECT
                        tuw.user_id,
                        tps.period_date,
                        SUM(
                            CASE WHEN tw.total_weighted > 0
                                 THEN tuw.user_weighted / tw.total_weighted * tps.delivery_paid
                                 ELSE 0 END
                        ) AS revenue
                    FROM   task_user_weight tuw
                    JOIN   task_weight tw ON tw.task_id = tuw.task_id
                    JOIN   task_paid_split tps ON tps.task_id = tuw.task_id
                    GROUP  BY tuw.user_id, tps.period_date
                ),
                sales AS (
                    /* advance (pre-completion) collected revenue per (user,
                       payment month) — same contributor split as delivery,
                       applied to sales_paid instead */
                    SELECT
                        tuw.user_id,
                        tps.period_date,
                        SUM(
                            CASE WHEN tw.total_weighted > 0
                                 THEN tuw.user_weighted / tw.total_weighted * tps.sales_paid
                                 ELSE 0 END
                        ) AS revenue
                    FROM   task_user_weight tuw
                    JOIN   task_weight tw ON tw.task_id = tuw.task_id
                    JOIN   task_paid_split tps ON tps.task_id = tuw.task_id
                    GROUP  BY tuw.user_id, tps.period_date
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
                    /* invoiced/paid amounts are equally divided by the
                       number of tasks sharing the SO line (sol_task_count),
                       same reasoning as paid_task_events above */
                    SELECT ts.task_id, k.period_date,
                           COALESCE(ip.invoiced_ex_vat, 0)  / NULLIF(stc.task_count, 0) AS invoiced_ex_vat,
                           COALESCE(pp2.paid_ex_vat, 0)     / NULLIF(stc.task_count, 0) AS paid_ex_vat
                    FROM   task_sol ts
                    JOIN   sol_task_count stc ON stc.sol_id = ts.sol_id
                    JOIN   (
                        SELECT sol_id, period_date FROM inv_period
                        UNION
                        SELECT sol_id, period_date FROM paid_period
                    ) k ON k.sol_id = ts.sol_id
                    LEFT JOIN inv_period  ip  ON ip.sol_id  = ts.sol_id AND ip.period_date  = k.period_date
                    LEFT JOIN paid_period pp2 ON pp2.sol_id = ts.sol_id AND pp2.period_date = k.period_date
                ),
                inv_pay_alloc AS (
                    /* every task member's timesheet-weighted share
                       (user_weighted ÷ total_weighted) of invoices raised /
                       paid for that task, in whichever month the invoice/
                       payment activity fell — same weighted basis as
                       delivery_revenue/sales_revenue, just applied to the
                       Invoices Raised / Payments Collected columns instead */
                    SELECT
                        tuw.user_id,
                        tp.period_date,
                        SUM(
                            CASE WHEN tw.total_weighted > 0
                                 THEN tuw.user_weighted / tw.total_weighted
                                      * COALESCE(tp.invoiced_ex_vat, 0)
                                 ELSE 0 END
                        ) AS invoices_raised_amount,
                        SUM(
                            CASE WHEN tw.total_weighted > 0
                                 THEN tuw.user_weighted / tw.total_weighted
                                      * COALESCE(tp.paid_ex_vat, 0)
                                 ELSE 0 END
                        ) AS payments_collected_amount
                    FROM   task_user_weight tuw
                    JOIN   task_weight tw ON tw.task_id = tuw.task_id
                    JOIN   task_period tp ON tp.task_id = tuw.task_id
                    GROUP  BY tuw.user_id, tp.period_date
                ),
                task_delivered AS (
                    /* WORK DELIVERED — the value of work COMPLETED in the
                       month, which is a different question from any of the
                       cash columns above and must not be derived from them.

                       A task's delivered value is its share of its sale-order
                       line (the contracted, ex-VAT price, divided by the
                       number of tasks sharing that line — same
                       sol_task_count rule used everywhere else), and it is
                       recognised ONCE, in the month the task's PROJECT
                       reached the "Done" stage. Nothing here depends on
                       whether the client has paid: a job finished in January
                       and settled in March is January's delivery, which is
                       exactly what the earlier payment-date version got
                       wrong. Projects that have never reached Done deliver
                       nothing yet, so they simply do not appear. */
                    SELECT
                        ts.task_id,
                        date_trunc('month', pd.done_date)::date AS period_date,
                        sol.price_subtotal / NULLIF(stc.task_count, 0) AS delivered_value
                    FROM   task_sol ts
                    JOIN   sale_order_line sol ON sol.id = ts.sol_id
                    JOIN   sol_task_count stc  ON stc.sol_id = ts.sol_id
                    JOIN   project_task pt8    ON pt8.id = ts.task_id
                    JOIN   project_done pd     ON pd.project_id = pt8.project_id
                    WHERE  pd.done_date IS NOT NULL
                ),
                delivered_alloc AS (
                    /* per (user, completion month): each contributor's slice
                       of the tasks delivered that month, on the same
                       hours-logged split as every other allocated column, so
                       the shares of one task still sum to its whole value */
                    SELECT
                        tuw.user_id,
                        td.period_date,
                        SUM(
                            CASE WHEN tw.total_weighted > 0
                                 THEN tuw.user_weighted / tw.total_weighted * td.delivered_value
                                 ELSE 0 END
                        ) AS work_completed_value
                    FROM   task_user_weight tuw
                    JOIN   task_weight tw ON tw.task_id = tuw.task_id
                    JOIN   task_delivered td ON td.task_id = tuw.task_id
                    GROUP  BY tuw.user_id, td.period_date
                ),
                invoice_count_alloc AS (
                    /* plain (non-fractional) count: distinct invoices raised
                       this month for any task this employee is a member of
                       — every member counts, not just whoever logged hours
                       that specific month. Deliberately a plain count, NOT
                       weighted: a fractional invoice count is meaningless,
                       so an invoice counts once for everyone who worked the
                       task while its VALUE is split by hours above. */
                    SELECT tuw.user_id, ti.period_date, COUNT(DISTINCT ti.move_id) AS invoices_raised_count
                    FROM   task_user_weight tuw
                    JOIN   task_invoices ti ON ti.task_id = tuw.task_id
                    GROUP  BY tuw.user_id, ti.period_date
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
                        COALESCE(ica.invoices_raised_count, 0)     AS invoices_raised_count,
                        /* Work Delivered = the contracted value of the work
                           COMPLETED this month (see task_delivered), NOT a
                           cash figure and NOT a restatement of
                           delivery_revenue. */
                        COALESCE(da.work_completed_value, 0)       AS work_completed_value
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
                    LEFT JOIN sales    s ON s.user_id = e.user_id AND s.period_date = gs.period_date::date
                    LEFT JOIN inv_pay_alloc ipa ON ipa.user_id = e.user_id AND ipa.period_date = gs.period_date::date
                    LEFT JOIN invoice_count_alloc ica ON ica.user_id = e.user_id AND ica.period_date = gs.period_date::date
                    LEFT JOIN delivered_alloc da ON da.user_id = e.user_id AND da.period_date = gs.period_date::date
                ),
                calc AS (
                    SELECT b.*,
                        (b.delivery_revenue + b.sales_revenue) AS total_revenue,
                        CASE b.office_location WHEN 'uae' THEN 3 WHEN 'india' THEN 5 ELSE 3 END AS base_monthly_mult,
                        CASE b.office_location WHEN 'uae' THEN 5 WHEN 'india' THEN 10 ELSE 5 END AS annual_mult
                    FROM base b
                    /* NO row filter here on purpose. An earlier version
                       dropped months before the ramp start date, on the
                       reasoning that the person was not employed yet — but
                       that silently removed history from the report, so the
                       rows stay and pre-start months simply fall through to
                       the full obligation below, exactly as they scored
                       before the ramp-up existed. */
                ),
                ramp AS (
                    /* THE new-joiner ramp-up, resolved exactly once so every
                       threshold below is guaranteed to agree. A joiner's
                       target climbs 1x CTC in their first calendar month,
                       2x in their second, then the full location minimum
                       (UAE 3x, India 5x) from their third month on.
                       months_employed is 999 when no start date can be
                       resolved, and 0 or negative for months that fall
                       before the start date; both land on ELSE and are
                       scored at the full obligation. Only an exact 1 or 2
                       earns a reduced target. */
                    SELECT c.*,
                        CASE
                            WHEN c.months_employed = 1 THEN 1
                            WHEN c.months_employed = 2 THEN 2
                            ELSE c.base_monthly_mult
                        END AS effective_mult
                    FROM calc c
                ),
                fin AS (
                    SELECT r.*,
                        /* obligation & target in AED (CTC already converted) */
                        (r.monthly_ctc * r.effective_mult) AS monthly_obligation,
                        (r.annual_ctc * r.annual_mult) AS annual_target,
                        CASE
                            WHEN r.monthly_ctc * r.effective_mult > 0
                            THEN (r.total_revenue >= r.monthly_ctc * r.effective_mult)
                            ELSE TRUE
                        END AS is_met,
                        /* Minimum CTC obligation for the Status / Escalation
                           Stage columns. Ramped on the SAME basis as
                           monthly_obligation above, so the two are now the
                           same number: a new joiner cannot be marked below
                           target -- and cannot accrue a Warning Notice --
                           against an obligation that does not apply to them
                           yet. What still separates the two pairs is the
                           revenue they are scored against, not the
                           threshold: monthly_obligation is measured against
                           total_revenue (Achievement %% / RAG) while
                           min_ctc_obligation is measured against
                           payments_collected_amount (Status / Escalation). */
                        (r.monthly_ctc * r.effective_mult) AS min_ctc_obligation,
                        /* Is this an On Track month? i.e. did PAYMENT COLLECTED
                           reach the minimum? Everything short of that (both
                           'Below Minimum' and 'At Risk') is a below-target
                           month that advances the escalation cycle, and only
                           On Track resets it. Employees with no CTC on record
                           (no open contract) count as on track so they never
                           accrue an escalation off a zero threshold. */
                        CASE
                            WHEN r.monthly_ctc > 0
                            THEN (r.payments_collected_amount >= r.monthly_ctc * r.effective_mult)
                            ELSE TRUE
                        END AS status_on_track
                    FROM ramp r
                ),
                streak1 AS (
                    SELECT f.*,
                        SUM(CASE WHEN f.is_met THEN 1 ELSE 0 END)
                            OVER (PARTITION BY f.employee_id ORDER BY f.period_date
                                  ROWS UNBOUNDED PRECEDING) AS island,
                        /* second, independent gaps-and-islands pass on the
                           Payment-Collected basis — a new island starts on
                           every On Track month, which is exactly what resets
                           the escalation counter, so nothing before the most
                           recent On Track month can carry forward */
                        SUM(CASE WHEN f.status_on_track THEN 1 ELSE 0 END)
                            OVER (PARTITION BY f.employee_id ORDER BY f.period_date
                                  ROWS UNBOUNDED PRECEDING) AS esc_island
                    FROM fin f
                ),
                streak2 AS (
                    SELECT s1.*,
                        ROW_NUMBER() OVER (PARTITION BY s1.employee_id, s1.island
                                           ORDER BY s1.period_date) AS pos,
                        ROW_NUMBER() OVER (PARTITION BY s1.employee_id, s1.esc_island
                                           ORDER BY s1.period_date) AS esc_pos
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
                    /* ── New-joiner ramp-up, surfaced so a reduced target is
                       auditable instead of looking like a data error. 999 is
                       the "no start date on record" sentinel and is reported
                       as NULL rather than a nonsense tenure. */
                    ramp_start AS ramp_start_date,
                    CASE WHEN ramp_start IS NULL THEN NULL
                         ELSE months_employed END AS months_employed,
                    CASE
                        WHEN ramp_start IS NULL       THEN 'No Start Date'
                        WHEN months_employed = 1      THEN 'Month 1 — 1x CTC'
                        WHEN months_employed = 2      THEN 'Month 2 — 2x CTC'
                        WHEN months_employed < 1      THEN 'Before Start Date'
                        ELSE 'Full Obligation'
                    END AS ramp_stage,
                    sales_revenue,
                    delivery_revenue,
                    total_revenue,
                    invoices_raised_count,
                    invoices_raised_amount,
                    payments_collected_amount,
                    work_completed_value,
                    CASE WHEN monthly_obligation > 0
                         THEN total_revenue / monthly_obligation * 100
                         ELSE 0 END AS achievement_pct,
                    /* RAG status: Green = obligation met (>=100%%),
                       Amber = 75-99.99%%, Red = under 75%%. Rows with no
                       obligation on record (no open contract / zero CTC)
                       report 'N/A' rather than a misleading Green. */
                    CASE
                        WHEN monthly_obligation <= 0 THEN 'N/A'
                        WHEN total_revenue >= monthly_obligation THEN 'Green'
                        WHEN total_revenue >= monthly_obligation * 0.75 THEN 'Amber'
                        ELSE 'Red'
                    END AS rag_status,
                    is_met,
                    CASE WHEN is_met THEN 0
                         WHEN island = 0 THEN pos
                         ELSE pos - 1 END AS consecutive_non_perf,
                    /* ── Status (current month's Payment Collected only) ──
                       PAYMENT COLLECTED for the month scored against Monthly
                       CTC and the location minimum (CTC x 3 UAE / x 5 India).
                       Deliberately NOT Achievement %%, Delivered Value or
                       Invoices Raised:
                         PC <  CTC                   -> Below Minimum
                         CTC <= PC <  min_obligation -> At Risk
                         PC >= min_obligation        -> On Track
                       'Below Minimum' is the WORSE of the two failing bands:
                       the employee did not collect even 1x their own cost.
                       'At Risk' is the milder one: their own cost is covered
                       but the location minimum (3x UAE / 5x India) is not.
                       Both are still short of the minimum and both advance
                       the escalation counter identically — only the wording
                       differs, so no warning-notice streak changes.
                       Rows with no CTC on record report 'N/A' rather than a
                       misleading 'On Track' off a zero threshold. */
                    min_ctc_obligation,
                    CASE
                        WHEN monthly_ctc <= 0                                THEN 'N/A'
                        WHEN payments_collected_amount <  monthly_ctc        THEN 'Below Minimum'
                        WHEN payments_collected_amount <  min_ctc_obligation THEN 'At Risk'
                        ELSE 'On Track'
                    END AS performance_status,
                    /* ── Escalation Stage (Status history, not this month) ─
                       Count of CONSECUTIVE below-target months — a month
                       counts when its Status is Below Minimum OR At Risk
                       (both are simply PC < min_ctc_obligation) — up to and
                       including this row's month. An On Track month resets
                       the count to 0 and clears the stage, so no escalation
                       can be based on months preceding the most recent On
                       Track month. */
                    CASE WHEN status_on_track THEN 0
                         WHEN esc_island = 0 THEN esc_pos
                         ELSE esc_pos - 1 END AS consecutive_below_target,
                    CASE
                        WHEN status_on_track THEN NULL
                        WHEN (CASE WHEN esc_island = 0 THEN esc_pos ELSE esc_pos - 1 END) = 1
                            THEN '1st Month — Verbal Flag'
                        WHEN (CASE WHEN esc_island = 0 THEN esc_pos ELSE esc_pos - 1 END) = 2
                            THEN '2nd Month — Written Advisory'
                        ELSE '3rd+ Month — Warning + PIP'
                    END AS escalation_stage,
                    (SELECT id FROM res_currency WHERE name = 'AED' ORDER BY id LIMIT 1) AS currency_id,
                    ctc_currency_id
                FROM streak2
            )
        """.replace('%(task_weights)s', _task_weight_ctes(16))
                             % self._table)

    # ── Revenue breakdown (for the OWL wizard) ───────────────────────────
    @api.model
    def get_revenue_breakdown(self, employee_id, user_id, period_date):
        """Return the individual tasks that make up an employee's Sales
        (pre-completion / advance) and Delivery (post-completion / final
        settlement) revenue for the given month — same definition as
        init()/get_period_revenue_amounts: collected (payment/
        reconciliation-date) basis, split at the Done date of each
        task's project, both divided among the task's members in proportion
        to the hours each logged to it. Each row therefore also carries the
        employee's own hours, the task's total hours and the resulting
        share_pct, so the number on the scorecard can be traced back to the
        timesheets behind it. `period_date` is any date within the month
        ('YYYY-MM-DD')."""
        uid = user_id or 0
        cr = self.env.cr

        cr.execute("""
            WITH task_sol AS (
                SELECT pt.id AS task_id, sol.id AS sol_id
                FROM   project_task pt
                JOIN   sale_order_line sol ON sol.id = pt.sale_line_id
            ),
            sol_task_count AS (
                /* tasks sharing a sale-order line (e.g. a monthly retainer
                   covering many deliverables) must split that line's value
                   equally, not each get the full amount */
                SELECT sol_id, COUNT(DISTINCT task_id) AS task_count
                FROM   task_sol
                GROUP  BY sol_id
            ),
            inv_lines AS (
                SELECT solr.order_line_id AS sol_id, am.id AS move_id,
                       aml.price_subtotal, am.amount_total
                FROM   sale_order_line_invoice_rel solr
                JOIN   account_move_line aml ON aml.id = solr.invoice_line_id
                JOIN   account_move      am  ON am.id  = aml.move_id
                WHERE  am.move_type = 'out_invoice' AND am.state = 'posted'
            ),
            recv_lines AS (
                SELECT aml.id AS recv_line_id, aml.move_id
                FROM   account_move_line aml
                JOIN   account_account   aa ON aa.id = aml.account_id
                WHERE  aa.account_type = 'asset_receivable'
            ),
            project_done AS (
                /* date each project reached the "Done" stage — the delivery
                   boundary (same source as init(): the chatter's tracked
                   stage change, since completed_date is never stamped) */
                SELECT
                    pp.id AS project_id,
                    COALESCE(
                        pp.completed_date,
                        (SELECT MAX(mm.date)
                         FROM   mail_tracking_value mtv
                         JOIN   mail_message mm ON mm.id = mtv.mail_message_id
                         JOIN   ir_model_fields imf ON imf.id = mtv.field_id
                         WHERE  mm.model  = 'project.project'
                           AND  mm.res_id = pp.id
                           AND  imf.model = 'project.project'
                           AND  imf.name  = 'stage_id'
                           AND  mtv.new_value_char = 'Done')
                    ) AS done_date
                FROM   project_project pp
                JOIN   project_project_stage pps ON pps.id = pp.stage_id
                WHERE  (CASE WHEN LEFT(pps.name::text, 1) = '{'
                             THEN (pps.name::jsonb) ->> 'en_US'
                             ELSE pps.name::text END) = 'Done'
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
            task_paid_split AS (
                /* per task: this month's collected amount, split into
                   "sales" (paid while its project was still open, or the
                   project has never reached Done — an advance) vs
                   "delivery" (paid on/after the project's Done date — the
                   final settlement); divided equally by the number of tasks
                   sharing the SO line so a shared retainer line isn't
                   counted in full for every task */
                SELECT
                    ts.task_id,
                    SUM(CASE WHEN pd.done_date IS NULL OR r.max_date < pd.done_date
                             THEN il.price_subtotal * COALESCE(r.amount, 0) / NULLIF(il.amount_total, 0)
                             ELSE 0 END) / NULLIF(stc.task_count, 0) AS sales_paid,
                    SUM(CASE WHEN pd.done_date IS NOT NULL AND r.max_date >= pd.done_date
                             THEN il.price_subtotal * COALESCE(r.amount, 0) / NULLIF(il.amount_total, 0)
                             ELSE 0 END) / NULLIF(stc.task_count, 0) AS delivery_paid
                FROM   task_sol ts
                JOIN   inv_lines il ON il.sol_id = ts.sol_id
                JOIN   recon r ON r.invoice_move_id = il.move_id
                              AND date_trunc('month', r.max_date) = date_trunc('month', %s::date)
                JOIN   project_task pt5 ON pt5.id = ts.task_id
                LEFT JOIN project_done pd ON pd.project_id = pt5.project_id
                JOIN   sol_task_count stc ON stc.sol_id = ts.sol_id
                GROUP  BY ts.task_id, stc.task_count
            ),
%(task_weights)s,
            task_hours AS (
                /* total hours logged to each task by everyone — shown next to
                   the employee's own hours so the share is self-evident */
                SELECT task_id, SUM(hours) AS total_hours
                FROM   task_user_weight
                GROUP  BY task_id
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
                tuw.hours,
                tuw.user_weighted AS weighted,
                CASE WHEN tw.total_weighted > 0
                     THEN tuw.user_weighted / tw.total_weighted * tps.sales_paid
                     ELSE 0 END AS sales_amount,
                CASE WHEN tw.total_weighted > 0
                     THEN tuw.user_weighted / tw.total_weighted * tps.delivery_paid
                     ELSE 0 END AS delivery_amount,
                COALESCE(th.total_hours, 0) AS total_hours,
                CASE WHEN tw.total_weighted > 0
                     THEN tuw.user_weighted / tw.total_weighted * 100
                     ELSE 0 END AS share_pct
            FROM   task_user_weight tuw
            JOIN   task_weight tw ON tw.task_id = tuw.task_id
            JOIN   task_paid_split tps ON tps.task_id = tuw.task_id
            JOIN   project_task pt ON pt.id = tuw.task_id
            LEFT JOIN task_hours th ON th.task_id = tuw.task_id
            LEFT JOIN project_project pp ON pp.id = pt.project_id
            LEFT JOIN sale_order_line sol4 ON sol4.id = pt.sale_line_id
            LEFT JOIN sale_order      so4  ON so4.id  = sol4.order_id
            LEFT JOIN res_partner     rp4  ON rp4.id  = so4.partner_id
            LEFT JOIN task_inv_agg    tia  ON tia.task_id = pt.id
            WHERE  tuw.user_id = %s
            ORDER  BY (
                CASE WHEN tw.total_weighted > 0
                     THEN tuw.user_weighted / tw.total_weighted * (tps.sales_paid + tps.delivery_paid)
                     ELSE 0 END
            ) DESC
        """.replace('%(task_weights)s', _task_weight_ctes(12)),
           (period_date, uid))
        rows = [{
            'project': r[0] or '',
            'task': r[1] or '',
            'customer': r[2] or '',
            'invoice_details': r[3] or '',
            'balance': r[5] or 0.0,
            'hours': round(r[6] or 0.0, 2),
            'sales_amount': r[8] or 0.0,
            'delivery_amount': r[9] or 0.0,
            # the timesheet split itself, so the drill-down shows WHY the
            # employee got this slice of the task
            'total_hours': round(r[10] or 0.0, 2),
            'share_pct': round(r[11] or 0.0, 2),
        } for r in cr.fetchall()]

        sales = [dict(row, amount=row['sales_amount']) for row in rows if row['sales_amount']]
        delivery = [dict(row, amount=row['delivery_amount']) for row in rows if row['delivery_amount']]

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

    # ── Period-scoped Sales / Delivery / Total Revenue ────────────────────
    @api.model
    def get_period_revenue_amounts(self, ids, date_from, date_to):
        """Recompute Sales/Delivery/Total Revenue and Work Delivered from
        amounts actually COLLECTED (payment/reconciliation date) within
        exactly [date_from, date_to], instead of each row's full calendar
        month.

        Each row still represents one (employee, month); the window used is
        the overlap between that row's month and the selected range (zero
        when there is no overlap), and only payments reconciled within that
        window count, pro-rata — same paid-basis as init(). A payment is
        Sales revenue if it lands before the project's Done date (or the
        project was never completed — an advance), Delivery revenue if it
        lands on/after that Done date (the final settlement) — same rule as
        init(). Called by the dashboard whenever both bounds of the Date
        filter are set — the period-aware counterpart to the sales_revenue/
        delivery_revenue columns baked into the view, same convention as
        mis.project.wise's get_period_amounts.

        Work Delivered narrows on a DIFFERENT basis from the three cash
        figures: a task counts when its project reached Done inside the
        window, at its contracted share of the sale-order line — the same
        completion-date basis as init()'s delivered_alloc, so the column
        means the same thing whether or not a date filter is applied.

        Returns {row_id: {sales_revenue, delivery_revenue, total_revenue,
        work_completed_value}}.
        """
        if not ids or not date_from or not date_to:
            return {}

        # Re-apply row-level access control server-side (defense in depth).
        allowed_ids = self.search([('id', 'in', ids)]).ids
        if not allowed_ids:
            return {}

        d_from = fields.Date.to_date(date_from)
        d_to = fields.Date.to_date(date_to)

        rows = self.browse(allowed_ids).read(['user_id', 'period_date'])
        row_ids, user_ids, eff_froms, eff_tos = [], [], [], []
        for r in rows:
            period_date = r['period_date']
            month_end = period_date + relativedelta(day=31)
            row_ids.append(r['id'])
            user_ids.append(r['user_id'][0] if r['user_id'] else 0)
            eff_froms.append(max(d_from, period_date))
            eff_tos.append(min(d_to, month_end))

        self.env.cr.execute("""
            WITH targets AS (
                SELECT * FROM unnest(
                    %(row_ids)s::int[], %(user_ids)s::int[],
                    %(eff_froms)s::date[], %(eff_tos)s::date[]
                ) AS t(row_id, user_id, eff_from, eff_to)
            ),
            inv_lines AS (
                /* all posted invoice lines (any date) — needed to prorate
                   each reconciliation against the invoice's own total, same
                   as init()'s paid_period */
                SELECT
                    solr.order_line_id AS sol_id,
                    am.id              AS move_id,
                    aml.price_subtotal,
                    am.amount_total
                FROM account_move am
                JOIN account_move_line aml ON aml.move_id = am.id
                JOIN sale_order_line_invoice_rel solr ON solr.invoice_line_id = aml.id
                WHERE am.move_type = 'out_invoice' AND am.state = 'posted'
            ),
            recv_lines AS (
                SELECT aml.id AS recv_line_id, aml.move_id
                FROM   account_move_line aml
                JOIN   account_account   aa ON aa.id = aml.account_id
                WHERE  aa.account_type = 'asset_receivable'
            ),
            project_done AS (
                /* date each project reached the "Done" stage — the delivery
                   boundary (same source as init(): the chatter's tracked
                   stage change, since completed_date is never stamped) */
                SELECT
                    pp.id AS project_id,
                    COALESCE(
                        pp.completed_date,
                        (SELECT MAX(mm.date)
                         FROM   mail_tracking_value mtv
                         JOIN   mail_message mm ON mm.id = mtv.mail_message_id
                         JOIN   ir_model_fields imf ON imf.id = mtv.field_id
                         WHERE  mm.model  = 'project.project'
                           AND  mm.res_id = pp.id
                           AND  imf.model = 'project.project'
                           AND  imf.name  = 'stage_id'
                           AND  mtv.new_value_char = 'Done')
                    ) AS done_date
                FROM   project_project pp
                JOIN   project_project_stage pps ON pps.id = pp.stage_id
                WHERE  (CASE WHEN LEFT(pps.name::text, 1) = '{'
                             THEN (pps.name::jsonb) ->> 'en_US'
                             ELSE pps.name::text END) = 'Done'
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
            task_sol AS (
                SELECT pt.id AS task_id, sol.id AS sol_id
                FROM   project_task pt
                JOIN   sale_order_line sol ON sol.id = pt.sale_line_id
            ),
            sol_task_count AS (
                /* tasks sharing a sale-order line (e.g. a monthly retainer
                   covering many deliverables) must split that line's value
                   equally, not each get the full amount */
                SELECT sol_id, COUNT(DISTINCT task_id) AS task_count
                FROM   task_sol
                GROUP  BY sol_id
            ),
            paid_task_lines AS (
                /* each row's window-restricted collected amount per task, by
                   reconciliation/payment date, split into "sales" (paid
                   while its project was still open, or the project never
                   reached Done — an advance) vs "delivery" (paid on/after
                   the project's Done date — the final settlement) — same
                   rule as init(); divided equally by the number of tasks
                   sharing the SO line */
                SELECT
                    t.row_id,
                    ts.task_id,
                    SUM(CASE WHEN pd.done_date IS NULL OR r.max_date < pd.done_date
                             THEN il.price_subtotal * COALESCE(r.amount, 0) / NULLIF(il.amount_total, 0)
                             ELSE 0 END) / NULLIF(stc.task_count, 0) AS sales_paid,
                    SUM(CASE WHEN pd.done_date IS NOT NULL AND r.max_date >= pd.done_date
                             THEN il.price_subtotal * COALESCE(r.amount, 0) / NULLIF(il.amount_total, 0)
                             ELSE 0 END) / NULLIF(stc.task_count, 0) AS delivery_paid
                FROM targets t
                JOIN recon r ON r.max_date BETWEEN t.eff_from AND t.eff_to
                JOIN inv_lines il ON il.move_id = r.invoice_move_id
                JOIN task_sol ts ON ts.sol_id = il.sol_id
                JOIN project_task pt7 ON pt7.id = ts.task_id
                LEFT JOIN project_done pd ON pd.project_id = pt7.project_id
                JOIN sol_task_count stc ON stc.sol_id = ts.sol_id
                GROUP BY t.row_id, ts.task_id, stc.task_count
            ),
%(task_weights)s,
            delivery AS (
                /* each row's window-restricted, post-completion (final
                   settlement) collected amount for a task, split among that
                   task's members in proportion to the hours each logged —
                   same non-duplicating split as init() */
                SELECT
                    t.row_id,
                    SUM(
                        CASE WHEN tw.total_weighted > 0
                             THEN tuw.user_weighted / tw.total_weighted * ptl.delivery_paid
                             ELSE 0 END
                    ) AS revenue
                FROM targets t
                JOIN task_user_weight tuw ON tuw.user_id = t.user_id
                JOIN task_weight tw ON tw.task_id = tuw.task_id
                JOIN paid_task_lines ptl ON ptl.row_id = t.row_id AND ptl.task_id = tuw.task_id
                GROUP BY t.row_id
            ),
            sales AS (
                /* each row's window-restricted, pre-completion (advance)
                   collected amount for a task — same contributor split as
                   delivery, applied to sales_paid instead */
                SELECT
                    t.row_id,
                    SUM(
                        CASE WHEN tw.total_weighted > 0
                             THEN tuw.user_weighted / tw.total_weighted * ptl.sales_paid
                             ELSE 0 END
                    ) AS revenue
                FROM targets t
                JOIN task_user_weight tuw ON tuw.user_id = t.user_id
                JOIN task_weight tw ON tw.task_id = tuw.task_id
                JOIN paid_task_lines ptl ON ptl.row_id = t.row_id AND ptl.task_id = tuw.task_id
                GROUP BY t.row_id
            ),
            delivered AS (
                /* WORK DELIVERED, narrowed to the selected range on the
                   COMPLETION date — not the payment date, which is what the
                   two CTEs above use. A task counts here when its project
                   reached Done inside the window, at its contracted share of
                   the sale-order line, split across contributors on the same
                   hours-logged basis as init()'s delivered_alloc. */
                SELECT
                    t.row_id,
                    SUM(
                        CASE WHEN tw.total_weighted > 0
                             THEN tuw.user_weighted / tw.total_weighted
                                  * (sol.price_subtotal / NULLIF(stc.task_count, 0))
                             ELSE 0 END
                    ) AS value
                FROM targets t
                JOIN task_user_weight tuw ON tuw.user_id = t.user_id
                JOIN task_weight tw ON tw.task_id = tuw.task_id
                JOIN project_task pt9 ON pt9.id = tuw.task_id
                JOIN project_done pd ON pd.project_id = pt9.project_id
                                    AND pd.done_date BETWEEN t.eff_from AND t.eff_to
                JOIN sale_order_line sol ON sol.id = pt9.sale_line_id
                JOIN sol_task_count stc ON stc.sol_id = sol.id
                GROUP BY t.row_id
            )
            SELECT t.row_id,
                   COALESCE(d.revenue, 0) AS delivery_revenue,
                   COALESCE(s.revenue, 0) AS sales_revenue,
                   COALESCE(wd.value, 0)  AS work_completed_value
            FROM targets t
            LEFT JOIN delivery  d  ON d.row_id  = t.row_id
            LEFT JOIN sales     s  ON s.row_id  = t.row_id
            LEFT JOIN delivered wd ON wd.row_id = t.row_id
        """.replace('%(task_weights)s', _task_weight_ctes(12)), {
            'row_ids': row_ids,
            'user_ids': user_ids,
            'eff_froms': eff_froms,
            'eff_tos': eff_tos,
        })

        result = {}
        for row in self.env.cr.dictfetchall():
            sales_revenue = row['sales_revenue'] or 0
            delivery_revenue = row['delivery_revenue'] or 0
            result[row['row_id']] = {
                'sales_revenue': sales_revenue,
                'delivery_revenue': delivery_revenue,
                'total_revenue': sales_revenue + delivery_revenue,
                # Work Delivered is its own measure — the value of the work
                # COMPLETED inside the window (completion date), not the cash
                # collected in it.
                'work_completed_value': row['work_completed_value'] or 0,
            }
        return result

    # ── Overdue invoice aging (for the Performance Management Report's
    #    "Overdue Invoice Detail" tab) ─────────────────────────────────────
    @api.model
    def get_overdue_invoices(self):
        """Full aging list of unpaid, past-due customer invoices. Amounts
        are converted to AED using the latest available currency rate (same
        convention as the CTC INR→AED conversion in init())."""
        self.env.cr.execute("""
            SELECT
                am.name,
                COALESCE(rp.complete_name, rp.name, ''),
                CASE WHEN LEFT(hd.name::text, 1) = '{'
                     THEN (hd.name::jsonb)->>'en_US' ELSE hd.name::text END,
                COALESCE(pmp.name, ''),
                am.invoice_date,
                am.invoice_date_due,
                am.amount_residual * CASE WHEN cur.name = 'AED' THEN 1
                    ELSE COALESCE(
                        (SELECT 1.0 / r.rate FROM res_currency_rate r
                         WHERE r.currency_id = cur.id
                         ORDER BY r.name DESC LIMIT 1),
                        CASE WHEN cur.name = 'USD' THEN 3.6725 ELSE 1 END)
                    END,
                (CURRENT_DATE - am.invoice_date_due)::integer,
                COALESCE(arp.name, ''),
                am.last_followup_date
            FROM   account_move am
            LEFT JOIN res_partner rp   ON rp.id  = am.partner_id
            -- The Sale Order Line is the engagement link now; service_engagement_id
            -- is the project it resolves to and is still stamped on retainership
            -- invoices, which have no sale order line of their own.
            LEFT JOIN sale_order_line sol ON sol.id = am.sale_order_line_id
            LEFT JOIN project_project pp ON pp.id = COALESCE(am.service_engagement_id, sol.project_id)
            LEFT JOIN hr_department hd ON hd.id  = pp.department_id
            LEFT JOIN res_users pmu    ON pmu.id = pp.user_id
            LEFT JOIN res_partner pmp  ON pmp.id = pmu.partner_id
            LEFT JOIN res_users aru    ON aru.id = am.ar_responsible_id
            LEFT JOIN res_partner arp  ON arp.id = aru.partner_id
            LEFT JOIN res_currency cur ON cur.id = am.currency_id
            WHERE  am.move_type = 'out_invoice'
              AND  am.state = 'posted'
              AND  am.payment_state NOT IN ('paid', 'in_payment', 'reversed')
              AND  am.invoice_date_due IS NOT NULL
              AND  am.invoice_date_due < CURRENT_DATE
              AND  am.amount_residual > 0.01
            ORDER  BY 8 DESC
        """)
        cols = ['invoice_no', 'client', 'team', 'pm_responsible', 'invoice_date',
                'due_date', 'amount_aed', 'days_overdue', 'ar_responsible',
                'last_follow_up_date']
        return [
            {c: (v.isoformat() if hasattr(v, 'isoformat') else v)
             for c, v in zip(cols, row)}
            for row in self.env.cr.fetchall()
        ]
