from odoo import models, fields, api

class AssetLocation(models.Model):
    _name = 'assets.location.rk'
    _description = 'IT Asset Location'

    name = fields.Char(string='Location Name', required=True)
    code = fields.Char(string='Location Code', required=True, copy=False)

class AssetsDevice(models.Model):
    _name = 'assets.device.rk'
    _description = 'IT Asset Device'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Device Name', required=True, tracking=True)
    asset_type = fields.Selection([
        ('laptop', 'Laptop'),
        ('desktop', 'Desktop'),
        ('keyboard', 'Keyboard'),
        ('mouse', 'Mouse'),
        ('printer', 'Printer'),
        ('mobile', 'Mobile'),
        ('other', 'Other'),
    ], string='Asset Type', required=True, tracking=True)
    serial_number = fields.Char(string='Serial Number', required=True, unique=True, tracking=True)
    location_id = fields.Many2one('assets.location.rk', string='Location', required=True, tracking=True)
    assigned_to = fields.Many2one('res.users', string='Assigned To')
    purchase_date = fields.Date("Purchase Date")
    warranty_until = fields.Date("Warranty Until")
    active = fields.Boolean("Active", default=True)
    notes = fields.Text("Notes")


    @api.model
    def create(self, vals):
        record = super().create(vals)
        record.message_post(body=f"Asset {record.name} created.")
        return record

    def write(self, vals):
        result = super().write(vals)
        for rec in self:
            rec.message_post(body=f"Asset {rec.name} updated.")
        return result

class NetworkDeviceType(models.Model):
    _name = 'network.device.type.rk'
    _description = 'Network Device Type'

    name = fields.Char(string='Type Name', required=True)
    description = fields.Text(string='Description')


class NetworkDevice(models.Model):
    _name = 'network.device.rk'
    _description = 'Network Device'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Device Name', required=True, tracking=True)
    device_type_id = fields.Many2one('network.device.type.rk', string='Device Type', required=True, tracking=True)
    ip_address = fields.Char(string='IP Address')
    serial_number = fields.Char(string='Serial Number', tracking=True)
    location_id = fields.Many2one('assets.location.rk', string='Location', tracking=True)
    purchase_date = fields.Date(string='Purchase Date')
    warranty_until = fields.Date(string='Warranty Until')
    notes = fields.Text(string='Notes')
    active = fields.Boolean("Active", default=True)