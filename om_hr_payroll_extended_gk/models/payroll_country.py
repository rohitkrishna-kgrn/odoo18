from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

MODULE = 'om_hr_payroll_extended_gk'


class PayrollCountry(models.Model):
    """One row per payroll country. Each row owns its own Payroll menu
    ("Dubai Payroll", "India Payroll"...), so a new country needs no code:
    add a row and the menu, action and record rules follow."""
    _name = 'payroll.country'
    _description = 'Payroll Country'
    _order = 'sequence, id'

    name = fields.Char(string='Menu Name', required=True, translate=True)
    country_id = fields.Many2one('res.country', string='Country', required=True,
                                 help="Companies whose registered address is in this country are payrolled here.")
    country_code = fields.Char(related='country_id.code', store=True)
    reference_code = fields.Char(
        string='Reference Code', compute='_compute_reference_code', store=True, readonly=False,
        help="Country part of the payroll reference PAYROLL/<code>/<year>/<month>, e.g. UAE.")
    leave_location = fields.Selection(
        selection='_selection_leave_location', string='Leave Location',
        help="The Leave Management location (Country For Leave Model on the user) whose "
             "employees belong to this payroll. The Payroll salary rules use the same value.")
    sequence = fields.Integer(default=11)
    active = fields.Boolean(default=True)
    # PF / ESI: the Salary Administration (salary_processing_gk) formula, or typed only
    pf_esi_mode = fields.Selection([
        ('formula', 'Salary Administration formula'),
        ('manual', 'Manual entry only'),
    ], string='Default PF / ESI', default='manual', required=True,
        help="Default for newly fetched employees (each employee can be switched to Formula or Manual on the Salary Components tab). Formula: PF applies when the contract has an EPF amount, ESI when it has an ESI amount and "
             "the monthly wage is within the ESI limit. PF = PF % of min(PF wage % of the salary after LOP, "
             "PF wage cap); ESI = ESI % of the gross earnings after LOP, rounded up. A value typed on the "
             "payroll line always wins. Manual: 0 until typed.")
    pf_wage_ratio = fields.Float(string='PF Wage % of Salary after LOP', default=70.0)
    pf_wage_cap = fields.Float(string='PF Wage Cap', default=25000.0)
    pf_employee_rate = fields.Float(string='PF Employee %', default=12.0)
    pf_employer_rate = fields.Float(string='PF Employer %', default=12.0)
    esi_wage_threshold = fields.Float(string='ESI Wage Limit', default=21000.0,
                                      help="ESI applies only when the monthly wage is at or below this amount.")
    esi_employee_rate = fields.Float(string='ESI Employee %', default=0.75)
    esi_employer_rate = fields.Float(string='ESI Employer %', default=3.25)
    wfh_rate = fields.Float(string='Work From Home Deduction %', default=4.0,
                            help="India: Work From Home Deduction = Gross / 30 x this % x 30 (fixed 30-day basis, "
                                 "whatever the days in the month).")
    menu_id = fields.Many2one('ir.ui.menu', string='Menu', readonly=True, ondelete='set null')
    action_id = fields.Many2one('ir.actions.act_window', string='Action', readonly=True, ondelete='set null')
    company_ids = fields.Many2many('res.company', compute='_compute_company_ids', string='Companies')
    officer_ids = fields.Many2many('res.users', compute='_compute_officer_ids', string='Payroll Officers')

    _sql_constraints = [
        ('country_unique', 'unique(country_id)', 'Each country can only have one payroll configuration.'),
    ]

    REFERENCE_CODES = {'AE': 'UAE', 'IN': 'IND'}

    @api.depends('country_id.code')
    def _compute_reference_code(self):
        for cfg in self:
            if not cfg.reference_code:
                code = (cfg.country_id.code or '').upper()
                cfg.reference_code = self.REFERENCE_CODES.get(code, code) or False

    @api.model
    def _selection_leave_location(self):
        return list(self.env['res.users']._fields['country'].selection)

    def _compute_company_ids(self):
        for rec in self:
            rec.company_ids = self.env['res.company'].sudo().search([('partner_id.country_id', '=', rec.country_id.id)])

    def _compute_officer_ids(self):
        for rec in self:
            rec.officer_ids = rec._country_officers()

    def _country_officers(self):
        """Active Payroll Officers of this payroll: Payroll access Officer (or above) whose
        own Leave Location is this payroll's (approval / rejection notifications)."""
        self.ensure_one()
        if not self.leave_location:
            return self.env['res.users']
        group = self.env.ref('om_hr_payroll.group_hr_payroll_user')
        return self.env['res.users'].sudo().search([
            ('groups_id', 'in', group.id),
            ('country', '=', self.leave_location),
            ('share', '=', False),
        ])

    @api.model
    def _payroll_managers(self):
        """Active Payroll Managers (and Admins, who are Managers too)."""
        group = self.env.ref('om_hr_payroll.group_hr_payroll_manager')
        return self.env['res.users'].sudo().search([('groups_id', 'in', group.id), ('share', '=', False)])

    def _country_companies(self, date_from=None, date_to=None):
        """Companies on the running / expired contracts of the employees whose
        user has this Leave Location (Country For Leave Model), restricted to
        companies registered in this payroll's country. With a period, only
        contracts overlapping it count. Most users are archived on this DB, so
        archived users must be included (active_test=False) - contracts are
        filtered on active explicitly."""
        self.ensure_one()
        if not self.leave_location:
            return self.env['res.company']
        domain = [
            ('active', '=', True),
            ('employee_id.active', '=', True),          # archived employees never count
            ('employee_id.user_id.active', '=', True),  # nor employees whose user is archived
            ('state', 'in', ('open', 'close')),
            ('employee_id.user_id.country', '=', self.leave_location),
            ('company_id.partner_id.country_id', '=', self.country_id.id),
        ]
        if date_from and date_to:
            domain += [('date_start', '<=', date_to),
                       '|', ('date_end', '=', False), ('date_end', '>=', date_from)]
        contracts = self.env['hr.contract'].sudo().with_context(active_test=False).search(domain)
        return contracts.company_id.sorted('name')

    # ------------------------------------------------------------------ menus
    def _sync_menu(self):
        parent = self.env.ref('om_hr_payroll.menu_hr_payroll_root')
        groups = self.env.ref('om_hr_payroll.group_hr_payroll_user')     # Managers / Admins imply it
        list_view = self.env.ref(MODULE + '.view_payroll_country_batch_list')
        search_view = self.env.ref(MODULE + '.view_payroll_country_batch_search')
        form_view = self.env.ref(MODULE + '.view_payroll_country_batch_form')
        IMD = self.env['ir.model.data'].sudo()
        for rec in self.sudo():
            action_vals = {
                'name': rec.name,
                'res_model': 'payroll.country.batch',
                'view_mode': 'list,form',
                'search_view_id': search_view.id,
                'domain': repr([('payroll_country_id', '=', rec.id)]),
                'context': repr({'default_payroll_country_id': rec.id,
                                 'search_default_active_batches': 1}),
                'view_ids': [(5, 0, 0),
                             (0, 0, {'view_mode': 'list', 'view_id': list_view.id, 'sequence': 1}),
                             (0, 0, {'view_mode': 'form', 'view_id': form_view.id, 'sequence': 2})],
                'help': _('<p class="o_view_nocontent_smiling_face">Create the %s batch for a month</p>'
                          '<p>Pick the month, keep the companies, then Fetch Employees.</p>') % rec.name,
            }
            if rec.action_id:
                rec.action_id.write(action_vals)
            else:
                rec.action_id = self.env['ir.actions.act_window'].create(action_vals)
                IMD.create({'module': MODULE, 'name': 'action_payroll_country_%s' % rec.id,
                            'model': 'ir.actions.act_window', 'res_id': rec.action_id.id, 'noupdate': True})
            menu_vals = {
                'name': rec.name,
                'parent_id': parent.id,
                'sequence': rec.sequence,
                'action': 'ir.actions.act_window,%s' % rec.action_id.id,
                'groups_id': [(6, 0, groups.ids)],
                'active': rec.active,
            }
            if rec.menu_id:
                rec.menu_id.write(menu_vals)
            else:
                rec.menu_id = self.env['ir.ui.menu'].create(menu_vals)
                IMD.create({'module': MODULE, 'name': 'menu_payroll_country_%s' % rec.id,
                            'model': 'ir.ui.menu', 'res_id': rec.menu_id.id, 'noupdate': True})
        self.env.registry.clear_cache()

    @api.model
    def _sync_all_menus(self):
        """Run on every module upgrade (views/menus.xml): the generated country menus get
        the current access groups."""
        self.sudo().with_context(active_test=False).search([])._sync_menu()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_menu()
        return records

    def write(self, vals):
        res = super().write(vals)
        if {'name', 'sequence', 'active'} & set(vals):
            self._sync_menu()
        return res

    def unlink(self):
        if self.env['payroll.country.batch'].sudo().search_count([('payroll_country_id', 'in', self.ids)]):
            raise ValidationError(_("This country already has payroll batches - archive it instead."))
        menus = self.menu_id
        actions = self.action_id
        res = super().unlink()
        menus.sudo().unlink()
        actions.sudo().unlink()
        self.env.registry.clear_cache()
        return res
