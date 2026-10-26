from odoo import api, fields, models
from odoo.exceptions import ValidationError

PERMISSION_FIELDS = ('confidential', 'employee_can_view', 'employee_can_upload',
                     'employee_can_edit', 'employee_can_download', 'active')


class HrDmsCategory(models.Model):
    _name = 'hr.dms.category'
    _description = 'HR Document Category'
    _inherit = ['hr.dms.live.mixin']
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text()
    confidential = fields.Boolean(
        help="Confidential categories are never visible to the employee they belong to and are "
             "only accessible to users holding 'Confidential Records Access'.")
    employee_can_view = fields.Boolean(string='Employee can view', default=True)
    employee_can_upload = fields.Boolean(
        string='Employee can upload', default=True,
        help="Employee may add new documents and, while a document is in Draft, edit it and add or "
             "remove its files. After Submit only HR Managers and Administrators can change it.")
    employee_can_edit = fields.Boolean(
        string='Employee can update', default=True,
        help="Employee may edit the fields and files of own documents while they are in Draft, "
             "including ones HR added for them. After Submit only HR can change them.")
    employee_can_download = fields.Boolean(string='Employee can download', default=True)
    document_count = fields.Integer(compute='_compute_document_count')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The category code must be unique.'),
    ]

    def _compute_document_count(self):
        data = self.env['hr.dms.document'].sudo().with_context(active_test=False)._read_group(
            [('category_id', 'in', self.ids)], ['category_id'], ['__count'])
        counts = {cat.id: n for cat, n in data}
        for rec in self:
            rec.document_count = counts.get(rec.id, 0)

    @api.constrains('employee_can_view', 'employee_can_upload')
    def _check_upload_needs_view(self):
        for rec in self:
            if rec.employee_can_upload and not rec.employee_can_view:
                raise ValidationError(self.env._(
                    "Category '%s': employees need view permission to upload.", rec.name))

    @api.constrains('confidential', 'employee_can_view', 'employee_can_upload',
                    'employee_can_edit', 'employee_can_download')
    def _check_confidential_without_employee_access(self):
        for rec in self:
            if rec.confidential and (rec.employee_can_view or rec.employee_can_upload
                                     or rec.employee_can_edit or rec.employee_can_download):
                raise ValidationError(self.env._(
                    "Category '%s': a confidential category gives employees no access. Turn off "
                    "every employee permission to make it confidential, or untick Confidential "
                    "to give employees access.", rec.name))

    @api.onchange('employee_can_view')
    def _onchange_employee_can_view(self):
        if not self.employee_can_view:
            self.employee_can_upload = False

    @api.model
    def _clear_upload_without_view(self, vals):
        # the upload box goes read-only once view is unticked, so the client never sends the
        # onchange's upload=False; clear it here or the constraint above blocks the save
        if 'employee_can_view' in vals and not vals['employee_can_view']:
            vals['employee_can_upload'] = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._clear_upload_without_view(vals)
        records = super().create(vals_list)
        for rec in records:
            self.env['hr.dms.audit.log'].log(
                'access_change', self.env._("Category created: %s", rec._permission_summary()),
                category=rec, confidential=rec.confidential)
        return records

    def write(self, vals):
        self._clear_upload_without_view(vals)
        watched = set(vals) & set(PERMISSION_FIELDS + ('name',))
        before = {r.id: r._permission_summary() for r in self} if watched else {}
        res = super().write(vals)
        if 'active' in vals:
            self._cascade_active(vals['active'])
        for rec in self if watched else self.browse():
            self.env['hr.dms.audit.log'].log(
                'access_change',
                self.env._("Category permissions changed.\nBefore: %(b)s\nAfter: %(a)s",
                           b=before[rec.id], a=rec._permission_summary()),
                category=rec, confidential=rec.confidential)
        return res

    def _cascade_active(self, active):
        """An archived category is archived for everyone: its documents go with it, and come
        back with it."""
        Doc = self.env['hr.dms.document'].sudo().with_context(active_test=False)
        if active:
            docs = Doc.search([('category_id', 'in', self.ids), ('active', '=', False),
                               ('archived_by_category', '=', True)])
            docs.write({'active': True, 'archived_by_category': False})
        else:
            docs = Doc.search([('category_id', 'in', self.ids), ('active', '=', True)])
            docs.write({'active': False, 'archived_by_category': True})

    def unlink(self):
        for rec in self:
            self.env['hr.dms.audit.log'].log(
                'access_change', self.env._("Category deleted: %s", rec._permission_summary()),
                category=rec, confidential=rec.confidential)
        return super().unlink()

    def _permission_summary(self):
        self.ensure_one()
        return (f"{self.name} | confidential={self.confidential} | view={self.employee_can_view} | "
                f"upload={self.employee_can_upload} | update={self.employee_can_edit} | "
                f"download={self.employee_can_download} | "
                f"active={self.active}")

    def _hr_dms_live_users(self):
        # a category change (permissions, archive) can change what every employee sees
        group = self.env.ref('hr_dms.group_hr_dms_employee', raise_if_not_found=False)
        return group.sudo().users if group else super()._hr_dms_live_users()
