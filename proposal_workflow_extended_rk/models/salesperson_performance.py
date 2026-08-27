# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools


class SalespersonPerformance(models.Model):
    """One row per salesperson per day, with every step of their funnel.

    Built per-day rather than per-period so the same rows answer weekly,
    monthly and yearly questions - the reader groups by the period they
    want instead of the report hard-coding one.

    Each source is aggregated on its own before being combined, because a
    plain UNION would lose the DISTINCT needed for settlements: one invoice
    paid by one bank entry can produce several reconciliation lines.
    """
    _name = 'crm.salesperson.performance'
    _description = 'Salesperson Performance'
    _auto = False
    _order = 'date desc, user_id'

    user_id = fields.Many2one('res.users', string='Salesperson', readonly=True)
    date = fields.Date(string='Date', readonly=True)

    leads_count = fields.Integer(string='Leads Received', readonly=True)
    discovery_sent = fields.Integer(string='Discovery Forms Sent', readonly=True)
    discovery_received = fields.Integer(string='Discovery Forms Received', readonly=True)
    proposals_sent = fields.Integer(
        string='Proposals Sent', readonly=True,
        help="Quotations raised. This is what going out with a proposal looks "
             "like in the data - the formal proposal document is counted "
             "separately.")
    proposal_docs = fields.Integer(
        string='Proposal Documents', readonly=True,
        help="Proposal documents generated through the proposal workflow. "
             "That workflow started in August 2026, so earlier periods are "
             "empty by definition.")
    proposals_signed = fields.Integer(string='Proposals Signed / Closed', readonly=True)
    invoices_raised = fields.Integer(string='Invoices Raised', readonly=True)
    invoiced_amount = fields.Monetary(
        string='Invoiced Amount', readonly=True, currency_field='currency_id')
    payments_count = fields.Integer(
        string='Payments Received', readonly=True,
        help="Number of settlements matched against this salesperson's "
             "invoices. Payments arrive here as bank journal entries rather "
             "than payment records, so this counts the settling entry.")
    amount_collected = fields.Monetary(
        string='Amount Collected', readonly=True, currency_field='currency_id')
    outstanding_amount = fields.Monetary(
        string='Outstanding', readonly=True, currency_field='currency_id',
        help="Still unpaid on the invoices raised on this date - not a "
             "running balance, so a period total reads as 'still owed from "
             "what was invoiced in that period'.")

    currency_id = fields.Many2one(
        'res.currency', string='Currency', readonly=True,
        compute='_compute_currency_id')

    def _compute_currency_id(self):
        currency = self.env.company.currency_id
        for record in self:
            record.currency_id = currency

    @api.model
    def _query(self):
        return """
            WITH leads AS (
                SELECT l.user_id, l.create_date::date AS date, COUNT(*) AS n
                  FROM crm_lead l
                 WHERE l.user_id IS NOT NULL
              GROUP BY 1, 2
            ),
            disc_sent AS (
                SELECT l.user_id, f.sent_date::date AS date, COUNT(*) AS n
                  FROM crm_lead_discovery_form f
                  JOIN crm_lead l ON l.id = f.lead_id
                 WHERE f.sent_date IS NOT NULL AND l.user_id IS NOT NULL
              GROUP BY 1, 2
            ),
            disc_back AS (
                SELECT l.user_id, f.submitted_date::date AS date, COUNT(*) AS n
                  FROM crm_lead_discovery_form f
                  JOIN crm_lead l ON l.id = f.lead_id
                 WHERE f.submitted_date IS NOT NULL AND l.user_id IS NOT NULL
              GROUP BY 1, 2
            ),
            prop_sent AS (
                -- A proposal going out means a quotation was raised. NOT
                -- proposal_generated_on: that belongs to the new proposal
                -- document workflow and has only existed since Aug 2026, so
                -- using it would report zero for the whole team's history.
                -- It gets its own column below instead.
                SELECT so.user_id, so.create_date::date AS date, COUNT(*) AS n
                  FROM sale_order so
                 WHERE so.user_id IS NOT NULL
              GROUP BY 1, 2
            ),
            prop_docs AS (
                SELECT so.user_id, so.proposal_generated_on::date AS date, COUNT(*) AS n
                  FROM sale_order so
                 WHERE so.proposal_generated_on IS NOT NULL AND so.user_id IS NOT NULL
              GROUP BY 1, 2
            ),
            prop_signed AS (
                SELECT so.user_id, so.date_order::date AS date, COUNT(*) AS n
                  FROM sale_order so
                 WHERE so.state IN ('sale', 'done') AND so.user_id IS NOT NULL
              GROUP BY 1, 2
            ),
            invoiced AS (
                SELECT am.invoice_user_id AS user_id, am.invoice_date AS date,
                       COUNT(*) AS n,
                       SUM(COALESCE(am.amount_total_signed, 0)) AS total,
                       SUM(COALESCE(am.amount_residual_signed, 0)) AS residual
                  FROM account_move am
                 WHERE am.move_type = 'out_invoice'
                   AND am.state = 'posted'
                   AND am.invoice_user_id IS NOT NULL
                   AND am.invoice_date IS NOT NULL
              GROUP BY 1, 2
            ),
            collected AS (
                -- COUNT(DISTINCT credit.move_id): one bank entry settling one
                -- invoice can generate several reconciliation lines, and
                -- counting those would inflate the payment count.
                SELECT inv.invoice_user_id AS user_id, pr.max_date AS date,
                       COUNT(DISTINCT credit.move_id) AS n,
                       SUM(COALESCE(pr.amount, 0)) AS amount
                  FROM account_partial_reconcile pr
                  JOIN account_move_line debit  ON debit.id = pr.debit_move_id
                  JOIN account_move_line credit ON credit.id = pr.credit_move_id
                  JOIN account_move inv ON inv.id = debit.move_id
                                       AND inv.move_type = 'out_invoice'
                 WHERE inv.invoice_user_id IS NOT NULL AND pr.max_date IS NOT NULL
              GROUP BY 1, 2
            ),
            keys AS (
                SELECT user_id, date FROM leads
                UNION SELECT user_id, date FROM disc_sent
                UNION SELECT user_id, date FROM disc_back
                UNION SELECT user_id, date FROM prop_sent
                UNION SELECT user_id, date FROM prop_docs
                UNION SELECT user_id, date FROM prop_signed
                UNION SELECT user_id, date FROM invoiced
                UNION SELECT user_id, date FROM collected
            )
            SELECT ROW_NUMBER() OVER (ORDER BY k.user_id, k.date) AS id,
                   k.user_id                          AS user_id,
                   k.date                             AS date,
                   COALESCE(l.n,  0)                  AS leads_count,
                   COALESCE(ds.n, 0)                  AS discovery_sent,
                   COALESCE(db.n, 0)                  AS discovery_received,
                   COALESCE(ps.n, 0)                  AS proposals_sent,
                   COALESCE(pd.n, 0)                  AS proposal_docs,
                   COALESCE(pg.n, 0)                  AS proposals_signed,
                   COALESCE(iv.n, 0)                  AS invoices_raised,
                   COALESCE(iv.total, 0)              AS invoiced_amount,
                   COALESCE(co.n, 0)                  AS payments_count,
                   COALESCE(co.amount, 0)             AS amount_collected,
                   COALESCE(iv.residual, 0)           AS outstanding_amount
              FROM keys k
              LEFT JOIN leads       l  ON l.user_id  = k.user_id AND l.date  = k.date
              LEFT JOIN disc_sent   ds ON ds.user_id = k.user_id AND ds.date = k.date
              LEFT JOIN disc_back   db ON db.user_id = k.user_id AND db.date = k.date
              LEFT JOIN prop_sent   ps ON ps.user_id = k.user_id AND ps.date = k.date
              LEFT JOIN prop_docs   pd ON pd.user_id = k.user_id AND pd.date = k.date
              LEFT JOIN prop_signed pg ON pg.user_id = k.user_id AND pg.date = k.date
              LEFT JOIN invoiced    iv ON iv.user_id = k.user_id AND iv.date = k.date
              LEFT JOIN collected   co ON co.user_id = k.user_id AND co.date = k.date
        """

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            "CREATE OR REPLACE VIEW %s AS (%s)" % (self._table, self._query()))
