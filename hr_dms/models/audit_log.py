from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.http import request


class HrDmsAuditLog(models.Model):
    _name = 'hr.dms.audit.log'
    _description = 'HR Document Audit Trail'
    _order = 'id desc'

    action = fields.Selection([
        ('upload', 'Upload'),
        ('submit', 'Submission'),
        ('draft', 'Moved to Draft'),
        ('modify', 'Modification'),
        ('archive', 'Archive / Restore'),
        ('delete', 'Deletion'),
        ('download', 'Download'),
        ('approve', 'Approval'),
        ('reject', 'Rejection'),
        ('details', 'Personal Details'),
        ('access_change', 'Access Permission Change'),
        ('export', 'Excel Export'),
    ], required=True, readonly=True, index=True)
    user_id = fields.Many2one('res.users', string='Performed By', readonly=True, index=True)
    date = fields.Datetime(string='Date', default=fields.Datetime.now, readonly=True, index=True)
    document_id = fields.Many2one('hr.dms.document', string='Document', readonly=True, ondelete='set null')
    document_name = fields.Char(readonly=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True, ondelete='set null')
    employee_name = fields.Char(readonly=True)
    category_name = fields.Char(readonly=True)
    is_confidential = fields.Boolean(readonly=True, index=True)
    details = fields.Text(readonly=True)
    ip_address = fields.Char(readonly=True)

    @api.model
    def log(self, action, details='', document=None, employee=None, category=None,
            confidential=False, document_name=None):
        """Append an entry. Always written as superuser so that the actor needs
        no create right on the log, but ``user_id`` stays the real actor."""
        ip = False
        try:
            if request and request.httprequest:
                ip = request.httprequest.remote_addr
        except RuntimeError:
            pass
        vals = {
            'action': action,
            'user_id': self.env.uid,
            'details': details,
            'ip_address': ip,
            'is_confidential': bool(confidential),
        }
        document = document and document.sudo()
        employee = employee and employee.sudo()
        category = category and category.sudo()
        if document:
            vals.update(document_id=document.id, document_name=document_name or document.name)
        elif document_name:
            vals['document_name'] = document_name
        if employee:
            vals.update(employee_id=employee.id, employee_name=employee.name)
        if category:
            vals['category_name'] = category.name
        return self.sudo().create(vals)

    def write(self, vals):
        raise UserError(self.env._('The audit trail is read-only.'))

    def unlink(self):
        raise UserError(self.env._('The audit trail cannot be deleted.'))
