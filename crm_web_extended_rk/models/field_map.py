from odoo import fields, models

TARGET_FIELDS = [
    ('name', 'Name'),
    ('contact_number', 'Contact Number'),
    ('email', 'Email'),
    ('body', 'Message / Body'),
    ('service', 'Service'),
]


class WebLeadFieldMap(models.Model):
    _name = 'crm.web.lead.field.map'
    _description = 'Web Lead Field Mapping'
    _order = 'source_type, sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    source_type = fields.Selection([
        ('any', 'Custom / Any (flat JSON)'),
        ('elementor', 'Elementor Pro'),
    ], string='Source', required=True, default='any')

    # For custom/any: the top-level JSON key (e.g. "phone")
    # For elementor:  the field id or title string (e.g. "your-phone")
    source_key = fields.Char(
        string='Source Key / Field ID',
        required=True,
        help='Custom: top-level JSON key.\nElementor: field id or field title (see match_by).',
    )

    match_by = fields.Selection([
        ('id', 'Field ID'),
        ('title', 'Field Title / Label'),
    ], string='Match By', default='id',
       help='Elementor only: match against the field id or the field title.')

    target_field = fields.Selection(
        TARGET_FIELDS,
        string='Maps To',
        required=True,
    )
