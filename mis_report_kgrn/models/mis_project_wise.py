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
                        SUM(
                            CASE WHEN am.state = 'posted'
                                 THEN aml.price_subtotal ELSE 0 END
                        )                                                   AS invoiced_ex_vat,
                        SUM(
                            CASE WHEN am.state = 'posted'
                                      AND am.payment_state IN ('paid', 'in_payment')
                                 THEN aml.price_subtotal ELSE 0 END
                        )                                                   AS paid_ex_vat,
                        MAX(
                            CASE WHEN am.state = 'posted'
                                 THEN am.invoice_date ELSE NULL END
                        )                                                   AS last_invoice_date
                    FROM   sale_order_line_invoice_rel solr
                    JOIN   account_move_line aml ON aml.id = solr.invoice_line_id
                    JOIN   account_move      am  ON am.id  = aml.move_id
                    WHERE  am.move_type = 'out_invoice'
                    GROUP  BY solr.order_line_id
                )
                SELECT
                    sol.id                                                   AS id,
                    pp.id                                                    AS project_id,
                    COALESCE(
                        pp.name->>'en_US',
                        (SELECT value FROM jsonb_each_text(pp.name) LIMIT 1)
                    )                                                        AS project_name,
                    pp.user_id                                               AS project_manager_id,
                    pp.department_id                                         AS department_id,
                    pp.company_id                                            AS company_id,
                    so.id                                                    AS sale_order_id,
                    so.name                                                  AS so_number,
                    so.user_id                                               AS salesperson_id,
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

                    so.amount_untaxed                                        AS so_total_ex_vat,
                    so.amount_total                                          AS so_total_inc_vat,

                    COALESCE(ia.invoiced_ex_vat, 0)                         AS invoiced_ex_vat,
                    CASE WHEN so.amount_untaxed > 0
                         THEN COALESCE(ia.invoiced_ex_vat, 0)
                              * (so.amount_total / so.amount_untaxed)
                         ELSE COALESCE(ia.invoiced_ex_vat, 0) END           AS invoiced_inc_vat,
                    COALESCE(ia.paid_ex_vat, 0)                             AS paid_ex_vat,
                    CASE WHEN so.amount_untaxed > 0
                         THEN COALESCE(ia.paid_ex_vat, 0)
                              * (so.amount_total / so.amount_untaxed)
                         ELSE COALESCE(ia.paid_ex_vat, 0) END               AS paid_inc_vat,
                    COALESCE(ia.invoiced_ex_vat, 0)
                        - COALESCE(ia.paid_ex_vat, 0)                       AS outstanding_ex_vat,
                    CASE WHEN so.amount_untaxed > 0
                         THEN (COALESCE(ia.invoiced_ex_vat, 0)
                               - COALESCE(ia.paid_ex_vat, 0))
                              * (so.amount_total / so.amount_untaxed)
                         ELSE COALESCE(ia.invoiced_ex_vat, 0)
                              - COALESCE(ia.paid_ex_vat, 0) END             AS outstanding_inc_vat,

                    so.advance_amount                                        AS advance_amount,
                    CASE WHEN COALESCE(slc.cnt, 0) > 0
                         THEN so.advance_amount / slc.cnt
                         ELSE 0 END                                         AS advance_per_line,

                    /* use project.project.date (planned end) for deadline */
                    pp.date                                                  AS deadline,
                    CASE WHEN pp.date IS NOT NULL AND pp.date < CURRENT_DATE
                         THEN (CURRENT_DATE - pp.date)::integer
                         ELSE 0 END                                         AS days_overdue,

                    ia.last_invoice_date                                     AS last_invoice_date,
                    CASE WHEN ia.last_invoice_date IS NOT NULL
                         THEN (CURRENT_DATE - ia.last_invoice_date)::integer
                         ELSE NULL END                                      AS invoice_days_ago,

                    /* completed = fully delivered */
                    (sol.qty_delivered >= sol.product_uom_qty
                     AND sol.product_uom_qty > 0)                           AS is_completed,

                    rc.currency_id                                           AS currency_id

                FROM  project_project  pp
                JOIN  sale_order_line  sol ON sol.project_id = pp.id
                JOIN  sale_order       so  ON so.id          = sol.order_id
                JOIN  res_company      rc  ON rc.id          = pp.company_id
                LEFT JOIN inv_agg      ia  ON ia.order_line_id = sol.id
                LEFT JOIN so_line_count slc ON slc.order_id   = so.id
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
                    mgr_list.append(mgr)
                dept['managers'] = mgr_list
                dept['projects_count'] = sum(m['projects_count'] for m in mgr_list)
                dept_list.append(dept)
            comp['departments'] = dept_list
            comp['projects_count'] = sum(d['projects_count'] for d in dept_list)
            result.append(comp)

        return result
