from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class AssetLocation(models.Model):
    _name = 'assets.location.rk'
    _description = 'IT Asset Location'
    _order = 'name'

    name = fields.Char(string='Location Name', required=True)
    code = fields.Char(string='Location Code', required=True, copy=False)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   help="Currency used for monetary fields (e.g. Repair Cost) "
                                        "of assets at this location.")
    device_ids = fields.One2many('assets.device.rk', 'location_id', string='Device List')
    device_count = fields.Integer(string='Devices', compute='_compute_device_count')
    network_device_ids = fields.One2many('network.device.rk', 'location_id', string='Network Device List')
    network_device_count = fields.Integer(string='Network Devices', compute='_compute_device_count')

    @api.depends('device_ids.active', 'network_device_ids.active')
    def _compute_device_count(self):
        device_counts = dict(self.env['assets.device.rk']._read_group(
            [('location_id', 'in', self.ids)], groupby=['location_id'], aggregates=['__count'],
        ))
        network_counts = dict(self.env['network.device.rk']._read_group(
            [('location_id', 'in', self.ids)], groupby=['location_id'], aggregates=['__count'],
        ))
        for location in self:
            location.device_count = device_counts.get(location, 0)
            location.network_device_count = network_counts.get(location, 0)

    def action_view_devices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Devices - {self.name}',
            'res_model': 'assets.device.rk',
            'view_mode': 'kanban,list,form',
            'domain': [('location_id', '=', self.id)],
            'context': {'default_location_id': self.id},
        }

    def action_view_network_devices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Network Devices - {self.name}',
            'res_model': 'network.device.rk',
            'view_mode': 'kanban,list,form',
            'domain': [('location_id', '=', self.id)],
            'context': {'default_location_id': self.id},
        }


class AssetsDevice(models.Model):
    _name = 'assets.device.rk'
    _description = 'IT Asset Device'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Device Name', required=True, tracking=True)
    asset_type = fields.Selection([
        ('laptop', 'Laptop'),
        ('desktop', 'Desktop'),
        ('keyboard', 'Keyboard'),
        ('mouse', 'Mouse'),
        ('printer', 'Printer'),
        ('mobile', 'Mobile'),
        ('headphone', 'Headphone'),
        ('other', 'Other'),
    ], string='Asset Type', required=True, tracking=True, index=True)
    serial_number = fields.Char(string='Serial Number', required=True, tracking=True)
    location_id = fields.Many2one('assets.location.rk', string='Location', required=True,
                                   tracking=True, index=True)
    assigned_to = fields.Many2one('res.users', string='Assigned To', index=True)
    purchase_date = fields.Date("Purchase Date")
    warranty_until = fields.Date("Warranty Until", tracking=True)
    warranty_status = fields.Selection([
        ('valid', 'Under Warranty'),
        ('expiring', 'Expiring Soon'),
        ('expired', 'Expired'),
        ('none', 'Not Set'),
    ], string='Warranty Status', compute='_compute_warranty_status', store=True)
    active = fields.Boolean("Active", default=True)
    notes = fields.Text("Notes")
    archive_reason = fields.Selection([
        ('damaged', 'Device damaged'),
        ('replaced', 'Device replaced'),
        ('disposed', 'Device disposed'),
        ('lost_stolen', 'Lost/Stolen'),
        ('end_of_life', 'End of life'),
        ('other', 'Other'),
    ], string='Archive Reason', copy=False, tracking=True)
    archive_reason_note = fields.Text(string='Archive Remarks', copy=False)
    repair_ids = fields.One2many('assets.device.repair.rk', 'device_id', string='Repairs')

    @api.depends('warranty_until')
    def _compute_warranty_status(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.warranty_until:
                rec.warranty_status = 'none'
            elif rec.warranty_until < today:
                rec.warranty_status = 'expired'
            elif rec.warranty_until <= today + timedelta(days=30):
                rec.warranty_status = 'expiring'
            else:
                rec.warranty_status = 'valid'

    @api.constrains('purchase_date', 'warranty_until')
    def _check_warranty_after_purchase(self):
        for rec in self:
            if rec.purchase_date and rec.warranty_until and rec.warranty_until < rec.purchase_date:
                raise ValidationError(_("Warranty Expiry Date cannot be earlier than the Purchase Date."))

    @api.constrains('active', 'archive_reason', 'archive_reason_note')
    def _check_archive_reason(self):
        for rec in self:
            if not rec.active and not rec.archive_reason:
                raise ValidationError(_("Please provide a reason for marking the asset as Inactive/Archived."))
            if rec.archive_reason == 'other' and not rec.archive_reason_note:
                raise ValidationError(_("Please provide remarks when selecting 'Other' as the reason."))

    def action_archive(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Archive Device'),
            'res_model': 'assets.device.archive.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_device_ids': self.ids},
        }

    @api.model
    def create(self, vals):
        record = super().create(vals)
        record.message_post(body=f"Asset {record.name} created.")
        return record

    def write(self, vals):
        if vals.get('active'):
            vals.setdefault('archive_reason', False)
            vals.setdefault('archive_reason_note', False)
        result = super().write(vals)
        for rec in self:
            rec.message_post(body=f"Asset {rec.name} updated.")
        return result


class AssetsDeviceArchiveWizard(models.TransientModel):
    _name = 'assets.device.archive.wizard'
    _description = 'Archive IT Asset Device'

    device_ids = fields.Many2many('assets.device.rk', string='Devices', required=True)
    reason = fields.Selection([
        ('damaged', 'Device damaged'),
        ('replaced', 'Device replaced'),
        ('disposed', 'Device disposed'),
        ('lost_stolen', 'Lost/Stolen'),
        ('end_of_life', 'End of life'),
        ('other', 'Other'),
    ], string='Reason', required=True)
    note = fields.Text(string='Remarks')

    @api.constrains('reason', 'note')
    def _check_note_required_for_other(self):
        for wizard in self:
            if wizard.reason == 'other' and not wizard.note:
                raise ValidationError(_("Please provide remarks when selecting 'Other' as the reason."))

    def action_confirm(self):
        self.ensure_one()
        self.device_ids.write({
            'active': False,
            'archive_reason': self.reason,
            'archive_reason_note': self.note,
        })
        return {'type': 'ir.actions.act_window_close'}


class AssetsDeviceRepair(models.Model):
    _name = 'assets.device.repair.rk'
    _description = 'IT Asset Repair Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'reported_date desc, id desc'

    name = fields.Char(string='Repair Number', required=True, copy=False,
                        readonly=True, default=lambda self: _('New'))
    device_id = fields.Many2one('assets.device.rk', string='Asset', required=True,
                                 ondelete='cascade', index=True, readonly=True)
    asset_code = fields.Char(related='device_id.serial_number', string='Asset Code / Asset Tag', readonly=True)
    status = fields.Selection([
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('beyond_repair', 'Beyond Repair'),
    ], string='Status', required=True, default='pending', tracking=True)

    issue_title = fields.Char(string='Issue Title', required=True)
    issue_description = fields.Text(string='Issue Description', required=True)
    category = fields.Selection([
        ('hardware', 'Hardware'),
        ('software', 'Software'),
        ('network', 'Network'),
        ('peripheral', 'Peripheral'),
        ('other', 'Other'),
    ], string='Category', required=True)

    reported_date = fields.Date(string='Reported Date', required=True, default=fields.Date.context_today)
    sent_for_repair_date = fields.Date(string='Sent for Repair')
    return_date = fields.Date(string='Return Date')
    completed_date = fields.Date(string='Completed Date')

    service_provider = fields.Char(string='Service Provider')
    warranty_covered = fields.Boolean(string='Warranty Covered')
    currency_id = fields.Many2one('res.currency', string='Currency', compute='_compute_currency_id',
                                   store=True, readonly=True)
    repair_cost = fields.Monetary(string='Repair Cost', currency_field='currency_id', default=0.0)

    part_ids = fields.One2many('assets.device.repair.part.rk', 'repair_id', string='Parts Replaced')

    root_cause = fields.Text(string='Root Cause')
    resolution = fields.Text(string='Resolution / Repair Performed')
    remarks = fields.Text(string='Remarks')

    attachment_ids = fields.Many2many('ir.attachment', 'assets_device_repair_attachment_rel',
                                       'repair_id', 'attachment_id', string='Attachments')

    @api.depends('device_id.location_id.currency_id')
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = rec.device_id.location_id.currency_id or rec.env.company.currency_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('assets.device.repair.rk') or _('New')
        return super().create(vals_list)

    def unlink(self):
        if any(rec.status == 'completed' for rec in self):
            raise UserError(_("Completed repair records cannot be deleted."))
        return super().unlink()

    @api.constrains('reported_date', 'sent_for_repair_date')
    def _check_sent_for_repair_date(self):
        for rec in self:
            if rec.reported_date and rec.sent_for_repair_date and rec.sent_for_repair_date < rec.reported_date:
                raise ValidationError(_("Sent for Repair Date cannot be earlier than the Reported Date."))

    @api.constrains('sent_for_repair_date', 'return_date')
    def _check_return_date(self):
        for rec in self:
            if rec.sent_for_repair_date and rec.return_date and rec.return_date < rec.sent_for_repair_date:
                raise ValidationError(_("Return Date cannot be earlier than the Sent for Repair Date."))

    @api.constrains('return_date', 'completed_date')
    def _check_completed_date_order(self):
        for rec in self:
            if rec.return_date and rec.completed_date and rec.completed_date < rec.return_date:
                raise ValidationError(_("Completed Date cannot be earlier than the Return Date."))

    @api.constrains('status', 'completed_date', 'resolution')
    def _check_completed_requirements(self):
        for rec in self:
            if rec.status == 'completed':
                if not rec.completed_date:
                    raise ValidationError(_("Completed Date is mandatory when Status is Completed."))
                if not rec.resolution:
                    raise ValidationError(_("Resolution / Repair Performed is mandatory when Status is Completed."))

    @api.constrains('repair_cost')
    def _check_repair_cost(self):
        for rec in self:
            if rec.repair_cost < 0:
                raise ValidationError(_("Repair Cost cannot be less than zero."))

    @api.onchange('sent_for_repair_date', 'return_date')
    def _onchange_return_date_warning(self):
        if self.sent_for_repair_date and self.return_date and self.return_date < self.sent_for_repair_date:
            return {'warning': {
                'title': _("Invalid Return Date"),
                'message': _("Return Date cannot be earlier than the Sent for Repair Date."),
            }}

    @api.onchange('repair_cost')
    def _onchange_repair_cost_warning(self):
        if self.repair_cost < 0:
            return {'warning': {
                'title': _("Invalid Repair Cost"),
                'message': _("Repair Cost cannot be less than zero."),
            }}


class AssetsDeviceRepairPart(models.Model):
    _name = 'assets.device.repair.part.rk'
    _description = 'IT Asset Repair Replaced Part'
    _order = 'id'

    repair_id = fields.Many2one('assets.device.repair.rk', string='Repair', required=True, ondelete='cascade')
    part_name = fields.Char(string='Part Name', required=True)
    quantity = fields.Integer(string='Quantity', default=1)
    currency_id = fields.Many2one(related='repair_id.currency_id', string='Currency')
    cost = fields.Monetary(string='Cost', currency_field='currency_id')


class NetworkDeviceType(models.Model):
    _name = 'network.device.type.rk'
    _description = 'Network Device Type'
    _order = 'name'

    name = fields.Char(string='Type Name', required=True)
    description = fields.Text(string='Description')
    device_count = fields.Integer(string='Devices', compute='_compute_device_count')

    @api.depends()
    def _compute_device_count(self):
        counts = dict(self.env['network.device.rk']._read_group(
            [('device_type_id', 'in', self.ids)], groupby=['device_type_id'], aggregates=['__count'],
        ))
        for rec in self:
            rec.device_count = counts.get(rec, 0)


class NetworkDevice(models.Model):
    _name = 'network.device.rk'
    _description = 'Network Device'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Device Name', required=True, tracking=True)
    device_type_id = fields.Many2one('network.device.type.rk', string='Device Type',
                                      required=True, tracking=True, index=True)
    ip_address = fields.Char(string='IP Address')
    serial_number = fields.Char(string='Serial Number', tracking=True)
    location_id = fields.Many2one('assets.location.rk', string='Location', tracking=True, index=True)
    purchase_date = fields.Date(string='Purchase Date')
    warranty_until = fields.Date(string='Warranty Until', tracking=True)
    warranty_status = fields.Selection([
        ('valid', 'Under Warranty'),
        ('expiring', 'Expiring Soon'),
        ('expired', 'Expired'),
        ('none', 'Not Set'),
    ], string='Warranty Status', compute='_compute_warranty_status', store=True)
    notes = fields.Text(string='Notes')
    active = fields.Boolean("Active", default=True)

    @api.depends('warranty_until')
    def _compute_warranty_status(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.warranty_until:
                rec.warranty_status = 'none'
            elif rec.warranty_until < today:
                rec.warranty_status = 'expired'
            elif rec.warranty_until <= today + timedelta(days=30):
                rec.warranty_status = 'expiring'
            else:
                rec.warranty_status = 'valid'
