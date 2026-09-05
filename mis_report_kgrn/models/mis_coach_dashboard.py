from odoo import models, fields, api, tools


class MisCoachDashboard(models.Model):
    """One row per (coachee employee × project they logged hours on).

    Built from three existing SQL views rather than re-deriving anything:
    mis.project.revenue.line/mis.project.revenue supply the "which projects
    has this employee worked on" link (most coachees are neither Project
    Manager nor Salesperson, so the project-manager-centric reports can't
    place them), and mis.project.wise supplies the project's revenue and
    outstanding.
    """
    _name = 'mis.coach.dashboard'
    _description = 'MIS Coach Dashboard'
    _auto = False
    _rec_name = 'project_name'
    _order = 'employee_id, project_name'

    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    employee_user_id = fields.Many2one('res.users', string='Employee User', readonly=True)
    coach_employee_id = fields.Many2one('hr.employee', string='Coach', readonly=True)
    coach_user_id = fields.Many2one('res.users', string='Coach User', readonly=True)

    project_id = fields.Many2one('project.project', string='Project', readonly=True)
    project_name = fields.Char(string='Project', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    project_manager_id = fields.Many2one('res.users', string='Project Manager', readonly=True)
    salesperson_id = fields.Many2one('res.users', string='Salesperson', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    project_revenue_ex_vat = fields.Float(string='Project Revenue (Ex VAT)', readonly=True)
    project_revenue_inc_vat = fields.Float(string='Project Revenue (Inc VAT)', readonly=True)
    outstanding_ex_vat = fields.Float(string='Outstanding (Ex VAT)', readonly=True)
    outstanding_inc_vat = fields.Float(string='Outstanding (Inc VAT)', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY he.id, pw.project_id) AS id,
                    he.id                  AS employee_id,
                    he.user_id             AS employee_user_id,
                    coach_he.id            AS coach_employee_id,
                    coach_he.user_id       AS coach_user_id,
                    pw.project_id          AS project_id,
                    pw.project_name        AS project_name,
                    pw.department_id       AS department_id,
                    pw.company_id          AS company_id,
                    pw.project_manager_id  AS project_manager_id,
                    pw.salesperson_id      AS salesperson_id,
                    pw.currency_id         AS currency_id,
                    pw.so_total_ex_vat     AS project_revenue_ex_vat,
                    pw.so_total_inc_vat    AS project_revenue_inc_vat,
                    pw.outstanding_ex_vat  AS outstanding_ex_vat,
                    pw.outstanding_inc_vat AS outstanding_inc_vat
                FROM (
                    SELECT DISTINCT mprl.user_id, mpr.project_id
                    FROM   mis_project_revenue_line mprl
                    JOIN   mis_project_revenue mpr ON mpr.id = mprl.task_revenue_id
                ) ep
                JOIN hr_employee he       ON he.user_id = ep.user_id AND he.active = TRUE
                JOIN hr_employee coach_he ON coach_he.id = he.coach_id
                JOIN mis_project_wise pw  ON pw.project_id = ep.project_id
                WHERE he.coach_id IS NOT NULL
            )
        """ % self._table)

    # ── Role-based access (mirrors mis_project_wise.py / mis_outstanding.py /
    #    mis_project_revenue.py, but keyed on coach_id, not the PM/salesperson
    #    hierarchy — a coach and a "manager" are independent concepts here) ──
    @api.model
    def _get_access_domain(self):
        user = self.env.user
        if user.has_group('mis_report_kgrn.group_mis_admin'):
            return []
        return [('coach_user_id', '=', user.id)]

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
