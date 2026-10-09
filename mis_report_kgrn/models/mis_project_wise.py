from odoo import models, fields, api, tools


class MisProjectWise(models.Model):
    _name = 'mis.project.wise'
    _description = 'MIS Project Wise Report'
    _auto = False
    _rec_name = 'project_name'
    _order = 'company_id, department_id, project_manager_id, project_name'

    # ── Identifiers ──────────────────────────────────────────────────────
    project_id = fields.Many2one('project.project', string='Project', readonly=True)
    project_name = fields.Char(string='Project', readonly=True)
    project_manager_id = fields.Many2one('res.users', string='Project Manager', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True)
    so_number = fields.Char(string='SO Number', readonly=True)
    salesperson_id = fields.Many2one('res.users', string='Salesperson', readonly=True)
    sale_order_line_id = fields.Many2one('sale.order.line', string='SO Line', readonly=True)
    customer_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    # ── Qty ───────────────────────────────────────────────────────────────
    product_uom_qty = fields.Float(string='Ordered Qty', readonly=True, digits=(16, 2))
    qty_delivered = fields.Float(string='Delivered Qty', readonly=True, digits=(16, 2))

    # ── SO Line amounts ──────────────────────────────────────────────────
    sol_price_subtotal = fields.Float(string='Line Total (Ex VAT)', readonly=True)
    sol_price_total = fields.Float(string='Line Total (Inc VAT)', readonly=True)

    # ── Per-unit values ──────────────────────────────────────────────────
    unit_value_ex_vat = fields.Float(string='Unit Value (Ex VAT)', readonly=True)
    unit_value_inc_vat = fields.Float(string='Unit Value (Inc VAT)', readonly=True)

    # ── Delivered values ─────────────────────────────────────────────────
    delivered_value_ex_vat = fields.Float(string='Delivered Value (Ex VAT)', readonly=True)
    delivered_value_inc_vat = fields.Float(string='Delivered Value (Inc VAT)', readonly=True)

    # ── Work completed (task DONE + invoice raised + payment collected) ───
    work_completed_value_ex_vat = fields.Float(string='Work Completed Value (Ex VAT)', readonly=True)

    # ── SO totals ────────────────────────────────────────────────────────
    so_total_ex_vat = fields.Float(string='SO Total (Ex VAT)', readonly=True)
    so_total_inc_vat = fields.Float(string='SO Total (Inc VAT)', readonly=True)

    # ── Invoice / payment ────────────────────────────────────────────────
    invoiced_ex_vat = fields.Float(string='Invoiced (Ex VAT)', readonly=True)
    invoiced_inc_vat = fields.Float(string='Invoiced (Inc VAT)', readonly=True)
    paid_ex_vat = fields.Float(string='Paid (Ex VAT)', readonly=True)
    paid_inc_vat = fields.Float(string='Paid (Inc VAT)', readonly=True)
    outstanding_ex_vat = fields.Float(string='Outstanding (Ex VAT)', readonly=True)
    outstanding_inc_vat = fields.Float(string='Outstanding (Inc VAT)', readonly=True)

    # ── Advance ──────────────────────────────────────────────────────────
    advance_amount = fields.Float(string='Total Advance (SO)', readonly=True)
    advance_per_line = fields.Float(string='Advance (This Line)', readonly=True)

    # ── Deadline (uses project.project.date = planned end date) ──────────
    deadline = fields.Date(string='Planned End Date', readonly=True)
    days_overdue = fields.Integer(string='Days Overdue', readonly=True)

    # ── Invoice date ─────────────────────────────────────────────────────
    last_invoice_date = fields.Date(string='Last Invoice Date', readonly=True)
    invoice_days_ago = fields.Integer(string='Invoice Raised (Days Ago)', readonly=True)

    # ── Dates ────────────────────────────────────────────────────────────
    project_create_date = fields.Date(string='Created Date', readonly=True)

    # ── Completion status ────────────────────────────────────────────────
    is_completed = fields.Boolean(string='Completed', readonly=True)

    # ─────────────────────────────────────────────────────────────────────
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH so_line_count AS (
                    SELECT order_id, COUNT(*) AS cnt
                    FROM   sale_order_line
                    WHERE  project_id IS NOT NULL
                    GROUP  BY order_id
                ),
                inv_agg AS (
                    SELECT
                        solr.order_line_id,
                        /* Invoiced = posted customer invoices (incl. debit
                           notes, which are plain out_invoice + is_debit_note)
                           net of posted credit notes/refunds against the same
                           line. Refunds carry their own sale_line_ids row via
                           the credit-note wizard, so they join here directly. */
                        SUM(
                            CASE WHEN am.state = 'posted' AND am.move_type = 'out_invoice'
                                 THEN aml.price_subtotal
                                 WHEN am.state = 'posted' AND am.move_type = 'out_refund'
                                 THEN -aml.price_subtotal
                                 ELSE 0 END
                        )                                                   AS invoiced_ex_vat,
                        /* Inc-VAT invoiced uses the invoice line's own
                           price_total (real tax), not an SO-wide ratio. */
                        SUM(
                            CASE WHEN am.state = 'posted' AND am.move_type = 'out_invoice'
                                 THEN aml.price_total
                                 WHEN am.state = 'posted' AND am.move_type = 'out_refund'
                                 THEN -aml.price_total
                                 ELSE 0 END
                        )                                                   AS invoiced_inc_vat,
                        /* Outstanding = the Amount Due Odoo Accounting shows
                           on each posted invoice, apportioned to this SO line
                           by its share of the invoice; a refund's own open
                           balance is subtracted. A credit note reconciled
                           against an invoice already lowers that invoice's
                           Amount Due, so it must NOT also be counted as
                           money Paid (the old Paid = Total - Due did, and
                           with Invoiced already net of the refund the
                           credit was taken off twice). Ratio of two amounts
                           in the same currency, so no conversion needed. */
                        SUM(
                            CASE WHEN am.state = 'posted'
                                      AND COALESCE(am.amount_total, 0) <> 0
                                 THEN (CASE WHEN am.move_type = 'out_invoice'
                                            THEN aml.price_subtotal
                                            ELSE -aml.price_subtotal END)
                                      * COALESCE(am.amount_residual, 0)
                                      / am.amount_total
                                 ELSE 0 END
                        )                                                   AS outstanding_ex_vat,
                        SUM(
                            CASE WHEN am.state = 'posted'
                                      AND COALESCE(am.amount_total, 0) <> 0
                                 THEN (CASE WHEN am.move_type = 'out_invoice'
                                            THEN aml.price_total
                                            ELSE -aml.price_total END)
                                      * COALESCE(am.amount_residual, 0)
                                      / am.amount_total
                                 ELSE 0 END
                        )                                                   AS outstanding_inc_vat,
                        MAX(
                            CASE WHEN am.state = 'posted' AND am.move_type = 'out_invoice'
                                 THEN am.invoice_date ELSE NULL END
                        )                                                   AS last_invoice_date
                    FROM   sale_order_line_invoice_rel solr
                    JOIN   account_move_line aml ON aml.id = solr.invoice_line_id
                    JOIN   account_move      am  ON am.id  = aml.move_id
                    WHERE  am.move_type IN ('out_invoice', 'out_refund')
                    GROUP  BY solr.order_line_id
                ),
                /* Work Completed / Completed now use the project's whole
                   task list (not gated on a task carrying its own
                   sale_line_id — about a fifth of active tasks don't) so the ratio
                   matches "SO Total / Total Tasks x Completed Tasks" at
                   project grain, one row per project since project<->SO-line
                   is 1:1 in this DB. */
                task_agg AS (
                    SELECT pt.project_id,
                           COUNT(*)                                        AS tasks_total,
                           SUM(CASE WHEN (ptt.name->>'en_US') = 'Done'
                               THEN 1 ELSE 0 END)                          AS tasks_completed
                    FROM   project_task pt
                    LEFT JOIN project_task_type ptt ON ptt.id = pt.stage_id
                    WHERE  pt.active = TRUE
                    GROUP  BY pt.project_id
                ),
                /* Project-Manager reassignment: project.project.user_id and
                   stage_id are both tracked (mail_tracking_value), so we can
                   tell whether a PM change happened before or after the
                   project reached its 'Done' stage. Not-yet-completed
                   projects, and completed projects whose last PM change
                   predates completion, keep showing pp.user_id (today's
                   behaviour, already correct). Only a PM change that landed
                   *after* completion is suppressed, falling back to the PM
                   in effect at the moment of completion. */
                pm_changes AS (
                    SELECT mm.res_id                AS project_id,
                           mm.date,
                           mtv.old_value_integer     AS old_pm,
                           mtv.new_value_integer     AS new_pm
                    FROM   mail_tracking_value mtv
                    JOIN   mail_message      mm ON mm.id = mtv.mail_message_id
                    JOIN   ir_model_fields   f  ON f.id  = mtv.field_id
                    WHERE  f.model = 'project.project' AND f.name = 'user_id'
                ),
                stage_done_at AS (
                    SELECT mm.res_id AS project_id, MIN(mm.date) AS done_at
                    FROM   mail_tracking_value mtv
                    JOIN   mail_message        mm  ON mm.id  = mtv.mail_message_id
                    JOIN   ir_model_fields     f   ON f.id   = mtv.field_id
                    JOIN   project_project_stage pps ON pps.id = mtv.new_value_integer
                    WHERE  f.model = 'project.project' AND f.name = 'stage_id'
                    AND    (pps.name->>'en_US') = 'Done'
                    GROUP  BY mm.res_id
                ),
                last_pm_change AS (
                    SELECT DISTINCT ON (project_id) project_id, date AS last_change_date
                    FROM   pm_changes
                    ORDER  BY project_id, date DESC
                ),
                pm_before_or_at AS (
                    SELECT DISTINCT ON (pc.project_id) pc.project_id, pc.new_pm AS pm_value
                    FROM   pm_changes pc
                    JOIN   stage_done_at sda ON sda.project_id = pc.project_id
                    WHERE  pc.date <= sda.done_at
                    ORDER  BY pc.project_id, pc.date DESC
                ),
                pm_first_change AS (
                    SELECT DISTINCT ON (project_id) project_id, old_pm AS pm_value
                    FROM   pm_changes
                    ORDER  BY project_id, date ASC
                )
                SELECT
                    sol.id                                                   AS id,
                    pp.id                                                    AS project_id,
                    COALESCE(
                        pp.name->>'en_US',
                        (SELECT value FROM jsonb_each_text(pp.name) LIMIT 1)
                    )                                                        AS project_name,
                    CASE
                        WHEN sda.done_at IS NULL THEN pp.user_id
                        WHEN lpc.last_change_date IS NULL
                             OR lpc.last_change_date <= sda.done_at THEN pp.user_id
                        ELSE COALESCE(pba.pm_value, pfc.pm_value, pp.user_id)
                    END                                                       AS project_manager_id,
                    pp.department_id                                         AS department_id,
                    pp.company_id                                            AS company_id,
                    so.id                                                    AS sale_order_id,
                    so.name                                                  AS so_number,
                    so.user_id                                               AS salesperson_id,
                    so.partner_id                                            AS customer_id,
                    sol.id                                                   AS sale_order_line_id,
                    sol.product_uom_qty,
                    sol.qty_delivered,
                    sol.price_subtotal                                       AS sol_price_subtotal,
                    sol.price_total                                          AS sol_price_total,

                    CASE WHEN sol.product_uom_qty > 0
                         THEN sol.price_subtotal / sol.product_uom_qty
                         ELSE 0 END                                         AS unit_value_ex_vat,
                    CASE WHEN sol.product_uom_qty > 0
                         THEN sol.price_total / sol.product_uom_qty
                         ELSE 0 END                                         AS unit_value_inc_vat,
                    CASE WHEN sol.product_uom_qty > 0
                         THEN (sol.price_subtotal / sol.product_uom_qty) * sol.qty_delivered
                         ELSE 0 END                                         AS delivered_value_ex_vat,
                    CASE WHEN sol.product_uom_qty > 0
                         THEN (sol.price_total / sol.product_uom_qty) * sol.qty_delivered
                         ELSE 0 END                                         AS delivered_value_inc_vat,

                    /* SO Total / Total Tasks x Completed Tasks, at project
                       grain (ta.tasks_total/tasks_completed cover every
                       active task in the project, not just ones carrying
                       their own sale_line_id). Uses this project's own SO
                       LINE subtotal, not the whole so.amount_untaxed — about
                       a third of sale orders here split across multiple projects
                       (1,750 distinct SOs for 2,580 projects), and unlike
                       so_total_ex_vat (which the UI dedupes via
                       aggDistinct: "sale_order_id"), this column is summed
                       as-is, so it must already be scoped to this project's
                       own share or a shared SO's value would be counted once
                       per sibling project. */
                    CASE WHEN COALESCE(ta.tasks_total, 0) > 0
                         THEN sol.price_subtotal / ta.tasks_total
                              * COALESCE(ta.tasks_completed, 0)
                         ELSE 0 END                                         AS work_completed_value_ex_vat,

                    so.amount_untaxed                                        AS so_total_ex_vat,
                    so.amount_total                                          AS so_total_inc_vat,

                    COALESCE(ia.invoiced_ex_vat, 0)                         AS invoiced_ex_vat,
                    COALESCE(ia.invoiced_inc_vat, 0)                        AS invoiced_inc_vat,
                    /* Paid = Invoiced - Outstanding, so the three always
                       reconcile to the invoices themselves. */
                    COALESCE(ia.invoiced_ex_vat, 0)
                        - COALESCE(ia.outstanding_ex_vat, 0)                AS paid_ex_vat,
                    COALESCE(ia.invoiced_inc_vat, 0)
                        - COALESCE(ia.outstanding_inc_vat, 0)               AS paid_inc_vat,
                    COALESCE(ia.outstanding_ex_vat, 0)                      AS outstanding_ex_vat,
                    COALESCE(ia.outstanding_inc_vat, 0)                     AS outstanding_inc_vat,

                    so.advance_amount                                        AS advance_amount,
                    CASE WHEN COALESCE(slc.cnt, 0) > 0
                         THEN so.advance_amount / slc.cnt
                         ELSE 0 END                                         AS advance_per_line,

                    pp.create_date::date                                     AS project_create_date,

                    /* use project.project.date (planned end) for deadline */
                    pp.date                                                  AS deadline,
                    CASE WHEN pp.date IS NOT NULL AND pp.date < CURRENT_DATE
                         THEN (CURRENT_DATE - pp.date)::integer
                         ELSE 0 END                                         AS days_overdue,

                    ia.last_invoice_date                                     AS last_invoice_date,
                    CASE WHEN ia.last_invoice_date IS NOT NULL
                         THEN (CURRENT_DATE - ia.last_invoice_date)::integer
                         ELSE NULL END                                      AS invoice_days_ago,

                    /* completed = every task in the project is Done AND the
                       project itself has reached its 'Done' stage */
                    COALESCE(
                        COALESCE(ta.tasks_total, 0) > 0
                        AND ta.tasks_total = COALESCE(ta.tasks_completed, 0)
                        AND (pps.name->>'en_US') = 'Done',
                        FALSE
                    )                                                       AS is_completed,

                    rc.currency_id                                           AS currency_id

                FROM  project_project  pp
                JOIN  sale_order_line  sol ON sol.project_id = pp.id
                JOIN  sale_order       so  ON so.id          = sol.order_id
                JOIN  res_company      rc  ON rc.id          = pp.company_id
                LEFT JOIN inv_agg      ia  ON ia.order_line_id = sol.id
                LEFT JOIN so_line_count slc ON slc.order_id   = so.id
                LEFT JOIN task_agg     ta  ON ta.project_id  = pp.id
                LEFT JOIN project_project_stage pps ON pps.id = pp.stage_id
                LEFT JOIN stage_done_at sda ON sda.project_id = pp.id
                LEFT JOIN last_pm_change lpc ON lpc.project_id = pp.id
                LEFT JOIN pm_before_or_at pba ON pba.project_id = pp.id
                LEFT JOIN pm_first_change pfc ON pfc.project_id = pp.id
                WHERE pp.active = TRUE
                AND   so.state <> 'cancel'
            )
        """ % self._table)

    # ── Role-based access ─────────────────────────────────────────────────
    @api.model
    def _get_access_domain(self):
        """Role scope for this report — see ResUsers._mis_access_domain,
        which is the single definition shared with security/ir_rules.xml."""
        return self.env.user._mis_access_domain('project_manager_id', salesperson_field='salesperson_id')

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

    # ── Period-scoped Invoiced / Paid / Outstanding ────────────────────────
    @api.model
    def get_period_amounts(self, ids, date_from, date_to):
        """Recompute Invoiced/Paid restricted to invoices/payments dated within
        [date_from, date_to], and Outstanding as the balance as of date_to.

        The lifetime columns on this view (invoiced_ex_vat, paid_ex_vat, ...)
        sum every posted invoice/payment ever linked to a SO line, regardless
        of date. That mismatches period-based ledgers (e.g. Tally) where a
        selected month should only show that month's movement. This method
        is the period-aware counterpart, called by the report UI when an
        Invoice Date range is applied.

        Either bound may be omitted (falsy) for an open-ended range — an
        unset bound is treated as -infinity/+infinity rather than requiring
        both to be filled in before anything is computed.

        Also returns has_activity_in_range: whether the SO line has ANY
        posted invoice/refund dated inside [date_from, date_to], which is
        what the "Invoice Date" filter uses to decide whether to include a
        project at all — a project can have several invoices, and one
        falling inside the selected range must be enough to include it, even
        if that project's *last* invoice (last_invoice_date) falls outside.

        Returns {sale_order_line_id: {invoiced_ex_vat, invoiced_inc_vat,
                                       paid_ex_vat, paid_inc_vat,
                                       outstanding_ex_vat, outstanding_inc_vat,
                                       has_activity_in_range}}
        """
        if not ids or not (date_from or date_to):
            return {}

        # Re-apply row-level access control server-side (defense in depth —
        # the client only ever passes ids it was allowed to load).
        allowed_ids = self.search([('id', 'in', ids)]).ids
        if not allowed_ids:
            return {}

        self.env.cr.execute("""
            WITH target_lines AS (
                SELECT solr.order_line_id AS sol_id, aml.id AS inv_line_id, aml.move_id
                FROM   sale_order_line_invoice_rel solr
                JOIN   account_move_line aml ON aml.id = solr.invoice_line_id
                WHERE  solr.order_line_id = ANY(%(ids)s)
            ),
            inv_moves AS (
                SELECT tl.sol_id, tl.move_id,
                       am.move_type, am.invoice_date, am.amount_total,
                       aml.price_subtotal, aml.price_total
                FROM   target_lines tl
                JOIN   account_move_line aml ON aml.id = tl.inv_line_id
                JOIN   account_move      am  ON am.id  = tl.move_id
                WHERE  am.state = 'posted'
                AND    am.move_type IN ('out_invoice', 'out_refund')
            ),
            recv_lines AS (
                /* the receivable (AR) line of each invoice — this is the line
                   that actually gets reconciled against payments */
                SELECT aml.id AS recv_line_id, aml.move_id
                FROM   account_move_line aml
                JOIN   account_account   aa ON aa.id = aml.account_id
                WHERE  aa.account_type = 'asset_receivable'
            ),
            recon AS (
                /* Cash movements only. An invoice's receivable line
                   reconciled against a payment counts as money in; a
                   credit note's receivable line reconciled against a payment
                   counts as money paid back out (negative, below). A credit
                   note reconciled directly against an invoice is neither -
                   it is already netted off Invoiced, so counting it here
                   would take it off twice. */
                SELECT
                    rl.move_id AS invoice_move_id,
                    pr.max_date,
                    (CASE WHEN pr.debit_move_id = rl.recv_line_id
                          THEN pr.debit_amount_currency
                          ELSE pr.credit_amount_currency END)
                    * (CASE WHEN rm.move_type = 'out_refund'
                            THEN -1 ELSE 1 END)             AS amount
                FROM   account_partial_reconcile pr
                JOIN   recv_lines rl
                       ON rl.recv_line_id = pr.debit_move_id
                       OR rl.recv_line_id = pr.credit_move_id
                JOIN   account_move rm ON rm.id = rl.move_id
                                      AND rm.move_type IN ('out_invoice', 'out_refund')
                JOIN   account_move_line cl
                       ON cl.id = CASE WHEN rl.recv_line_id = pr.debit_move_id
                                       THEN pr.credit_move_id
                                       ELSE pr.debit_move_id END
                JOIN   account_move cm ON cm.id = cl.move_id
                                      AND cm.move_type NOT IN ('out_invoice', 'out_refund')
            ),
            paid_period_by_move AS (
                SELECT invoice_move_id, SUM(amount) AS amount
                FROM   recon
                WHERE  max_date BETWEEN COALESCE(%(date_from)s, '-infinity'::date)
                                 AND    COALESCE(%(date_to)s,   'infinity'::date)
                GROUP  BY invoice_move_id
            ),
            paid_to_date_by_move AS (
                SELECT invoice_move_id, SUM(amount) AS amount
                FROM   recon
                WHERE  max_date <= COALESCE(%(date_to)s, 'infinity'::date)
                GROUP  BY invoice_move_id
            )
            SELECT
                im.sol_id,

                BOOL_OR(im.invoice_date BETWEEN COALESCE(%(date_from)s, '-infinity'::date)
                                         AND    COALESCE(%(date_to)s,   'infinity'::date)
                )                                                           AS has_activity_in_range,

                SUM(CASE WHEN im.invoice_date BETWEEN COALESCE(%(date_from)s, '-infinity'::date)
                                              AND    COALESCE(%(date_to)s,   'infinity'::date)
                         THEN (CASE WHEN im.move_type = 'out_invoice'
                                    THEN im.price_subtotal ELSE -im.price_subtotal END)
                         ELSE 0 END)                                        AS invoiced_ex_vat,
                SUM(CASE WHEN im.invoice_date BETWEEN COALESCE(%(date_from)s, '-infinity'::date)
                                              AND    COALESCE(%(date_to)s,   'infinity'::date)
                         THEN (CASE WHEN im.move_type = 'out_invoice'
                                    THEN im.price_total ELSE -im.price_total END)
                         ELSE 0 END)                                        AS invoiced_inc_vat,

                SUM(CASE WHEN im.invoice_date <= COALESCE(%(date_to)s, 'infinity'::date)
                         THEN (CASE WHEN im.move_type = 'out_invoice'
                                    THEN im.price_subtotal ELSE -im.price_subtotal END)
                         ELSE 0 END)                                        AS invoiced_ex_vat_to_date,
                SUM(CASE WHEN im.invoice_date <= COALESCE(%(date_to)s, 'infinity'::date)
                         THEN (CASE WHEN im.move_type = 'out_invoice'
                                    THEN im.price_total ELSE -im.price_total END)
                         ELSE 0 END)                                        AS invoiced_inc_vat_to_date,

                SUM(CASE WHEN COALESCE(im.amount_total, 0) <> 0
                         THEN im.price_subtotal * COALESCE(ppm.amount, 0) / im.amount_total
                         ELSE 0 END)                                        AS paid_ex_vat,
                SUM(CASE WHEN COALESCE(im.amount_total, 0) <> 0
                         THEN im.price_total * COALESCE(ppm.amount, 0) / im.amount_total
                         ELSE 0 END)                                        AS paid_inc_vat,

                SUM(CASE WHEN COALESCE(im.amount_total, 0) <> 0
                         THEN im.price_subtotal * COALESCE(ptm.amount, 0) / im.amount_total
                         ELSE 0 END)                                        AS paid_ex_vat_to_date,
                SUM(CASE WHEN COALESCE(im.amount_total, 0) <> 0
                         THEN im.price_total * COALESCE(ptm.amount, 0) / im.amount_total
                         ELSE 0 END)                                        AS paid_inc_vat_to_date

            FROM inv_moves im
            LEFT JOIN paid_period_by_move ppm ON ppm.invoice_move_id = im.move_id
            LEFT JOIN paid_to_date_by_move ptm ON ptm.invoice_move_id = im.move_id
            GROUP BY im.sol_id
        """, {
            'ids': allowed_ids,
            'date_from': date_from or None,
            'date_to': date_to or None,
        })

        result = {}
        for row in self.env.cr.dictfetchall():
            invoiced_ex_vat_to_date = row['invoiced_ex_vat_to_date'] or 0
            invoiced_inc_vat_to_date = row['invoiced_inc_vat_to_date'] or 0
            paid_ex_vat_to_date = row['paid_ex_vat_to_date'] or 0
            paid_inc_vat_to_date = row['paid_inc_vat_to_date'] or 0
            result[row['sol_id']] = {
                'invoiced_ex_vat': row['invoiced_ex_vat'] or 0,
                'invoiced_inc_vat': row['invoiced_inc_vat'] or 0,
                'paid_ex_vat': row['paid_ex_vat'] or 0,
                'paid_inc_vat': row['paid_inc_vat'] or 0,
                'outstanding_ex_vat': invoiced_ex_vat_to_date - paid_ex_vat_to_date,
                'outstanding_inc_vat': invoiced_inc_vat_to_date - paid_inc_vat_to_date,
                'has_activity_in_range': bool(row['has_activity_in_range']),
            }
        return result

    @api.model
    def get_dashboard_data(self):
        records = self.search_read(
            [],
            [
                'id', 'project_name', 'project_id', 'company_id',
                'project_manager_id', 'department_id',
                'so_number', 'salesperson_id',
                'product_uom_qty', 'qty_delivered',
                'unit_value_ex_vat', 'unit_value_inc_vat',
                'delivered_value_ex_vat', 'delivered_value_inc_vat',
                'sol_price_subtotal', 'sol_price_total',
                'so_total_ex_vat', 'so_total_inc_vat',
                'invoiced_ex_vat', 'invoiced_inc_vat',
                'paid_ex_vat', 'paid_inc_vat',
                'outstanding_ex_vat', 'outstanding_inc_vat',
                'advance_amount', 'advance_per_line',
                'deadline', 'days_overdue',
                'last_invoice_date', 'invoice_days_ago',
                'is_completed',
            ],
            limit=0,
        )

        # Work-completed value per PM — mis.outstanding.line aggregates this
        # at project/task-completion granularity (not captured by the SO-line
        # rows above), but shares the same _get_access_domain() PM scoping.
        completed_by_mgr = {}
        outstanding_recs = self.env['mis.outstanding.line'].search_read(
            [],
            ['project_manager_id', 'completed_tasks_value_ex_vat'],
            limit=0,
        )
        for r in outstanding_recs:
            mgr_id = r['project_manager_id'][0] if r['project_manager_id'] else 0
            completed_by_mgr[mgr_id] = (
                completed_by_mgr.get(mgr_id, 0.0) + r['completed_tasks_value_ex_vat']
            )

        companies = {}
        for r in records:
            comp_id = r['company_id'][0] if r.get('company_id') else 0
            comp_name = r['company_id'][1] if r.get('company_id') else 'KGRN'
            dept_id = r['department_id'][0] if r['department_id'] else 0
            dept_name = r['department_id'][1] if r['department_id'] else 'No Department'
            mgr_id = r['project_manager_id'][0] if r['project_manager_id'] else 0
            mgr_name = r['project_manager_id'][1] if r['project_manager_id'] else 'No Manager'

            comp = companies.setdefault(comp_id, {
                'id': comp_id, 'name': comp_name, 'departments': {}
            })
            dept = comp['departments'].setdefault(dept_id, {
                'id': dept_id, 'name': dept_name, 'managers': {}
            })
            mgr = dept['managers'].setdefault(mgr_id, {
                'id': mgr_id, 'name': mgr_name, 'projects': []
            })
            mgr['projects'].append(r)

        result = []
        for comp in companies.values():
            dept_list = []
            for dept in comp['departments'].values():
                mgr_list = []
                for mgr in dept['managers'].values():
                    projs = mgr['projects']
                    mgr['projects_count'] = len(projs)
                    mgr['total_so_ex_vat'] = sum(p['so_total_ex_vat'] for p in projs)
                    mgr['total_invoiced_ex_vat'] = sum(p['invoiced_ex_vat'] for p in projs)
                    mgr['total_paid_ex_vat'] = sum(p['paid_ex_vat'] for p in projs)
                    mgr['total_outstanding_ex_vat'] = sum(p['outstanding_ex_vat'] for p in projs)
                    mgr['total_outstanding_inc_vat'] = sum(p['outstanding_inc_vat'] for p in projs)
                    mgr['total_completed_value_ex_vat'] = completed_by_mgr.get(mgr['id'], 0.0)
                    mgr['collection_rate'] = (
                        round(mgr['total_paid_ex_vat'] / mgr['total_invoiced_ex_vat'] * 100, 1)
                        if mgr['total_invoiced_ex_vat'] else 0.0
                    )
                    mgr_list.append(mgr)
                dept['managers'] = mgr_list
                dept['projects_count'] = sum(m['projects_count'] for m in mgr_list)
                dept_list.append(dept)
            comp['departments'] = dept_list
            comp['projects_count'] = sum(d['projects_count'] for d in dept_list)
            result.append(comp)

        return result
