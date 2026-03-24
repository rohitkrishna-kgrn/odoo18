from odoo import models, fields, api
from odoo.exceptions import ValidationError

class ResPartner(models.Model):
    _inherit = 'res.partner'

    emirates_id = fields.Char(string="Emirates ID")
    passport_number = fields.Char(string="Passport Number")
    company_license_no = fields.Char(string="Company License Number")

    @api.model
    def create(self, vals):
        # Skip validation for system admin users
        if not self.env.user.has_group('base.group_system'):
            required_fields = ['phone', 'email', 'street', 'city', 'country_id', 'zip']
            for field in required_fields:
                if not vals.get(field):
                    raise ValidationError(f"The field '{field}' is mandatory and cannot be empty.")
        return super(ResPartner, self).create(vals)

    def write(self, vals):
        # Skip validation for system admin users
        if not self.env.user.has_group('base.group_system'):
            required_fields = ['phone', 'email', 'street', 'city', 'country_id', 'zip']
            for field in required_fields:
                if field in vals and not vals.get(field):
                    raise ValidationError(f"The field '{field}' is mandatory and cannot be empty.")
        return super(ResPartner, self).write(vals)