from odoo import models, fields, api
from odoo.exceptions import UserError

class Upselling(models.Model):
    _name = 'upselling'
    _description = 'Upselling'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence desc, id desc'

    user_id = fields.Many2one(
        'res.users', string='Submitted By',
        default=lambda self: self.env.user, readonly=True
    )
    description = fields.Text(string='Description', tracking=True)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', tracking=True)
    customer_id = fields.Many2one('res.partner', string='Customer', readonly=True, tracking=True)
    proposal_file = fields.Binary(string='Proposal File')
    proposal_filename = fields.Char(string='Proposal Filename', tracking=True)
    engagement_file = fields.Binary(string='Signed Engagement File')
    engagement_filename = fields.Char(string='Engagement Filename', tracking=True)
    invoice_ids = fields.One2many(
        'account.move', compute='_compute_invoice_ids',
        string='Invoices',
    )

    invoice_count = fields.Integer(string='Invoice Count', compute='_compute_invoice_ids')
    sequence = fields.Char(
        string='Sequence Number', required=True,
        copy=False, readonly=True, default='New',
        tracking=True
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('review', 'Submitted for Review'),
        ('approval', 'Submitted for Approval'),
        ('approved', 'Approved')
    ], default='draft', string='Status', tracking=True)

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company
    )
    is_approver = fields.Boolean(compute='_compute_is_approver')

    @api.model
    def create(self, vals):
        # Generate sequence if needed
        if vals.get('sequence', 'New') == 'New':
            vals['sequence'] = self.env['ir.sequence'].next_by_code('upselling.sequence') or 'New'

        # Set customer_id from sale_order_id if not provided
        if vals.get('sale_order_id') and not vals.get('customer_id'):
            sale_order = self.env['sale.order'].browse(vals['sale_order_id'])
            vals['customer_id'] = sale_order.partner_id.id if sale_order.partner_id else False

        return super(Upselling, self).create(vals)

    def write(self, vals):
        # If sale_order_id is updated, update customer_id accordingly
        if 'sale_order_id' in vals:
            sale_order = self.env['sale.order'].browse(vals['sale_order_id'])
            vals['customer_id'] = sale_order.partner_id.id if sale_order.partner_id else False
        return super(Upselling, self).write(vals)

    @api.depends('company_id')
    def _compute_is_approver(self):
        current_user = self.env.user
        for rec in self:
            company_approver = rec.company_id.approver_user_id
            rec.is_approver = bool(company_approver and company_approver.id == current_user.id)

    @api.onchange('sale_order_id')
    def _onchange_sale_order_id(self):
        if self.sale_order_id and self.sale_order_id.partner_id:
            self.customer_id = self.sale_order_id.partner_id.id
        else:
            self.customer_id = False
    
    @api.depends('sale_order_id')
    def _compute_invoice_ids(self):
        for rec in self:
            if rec.sale_order_id:
                # Use sale order's linked invoices and filter for customer invoices
                rec.invoice_ids = rec.sale_order_id.invoice_ids.filtered(lambda inv: inv.move_type == 'out_invoice')
            else:
                rec.invoice_ids = False

    # State transition buttons
    def action_submit_review(self):
        for rec in self:
            rec.state = 'review'

    def action_submit_approval(self):
        for rec in self:
            # List required fields to check
            missing_fields = []
            
            if not rec.description:
                missing_fields.append('Description')
            if not rec.sale_order_id:
                missing_fields.append('Sale Order')
            if not rec.customer_id:
                missing_fields.append('Customer')
            if not rec.proposal_file:
                missing_fields.append('Proposal File')
            if not rec.engagement_file:
                missing_fields.append('Signed Engagement File')
            if not rec.payment_received_datetime:
                missing_fields.append('Payment Received DateTime')
            if not rec.payment_reference:
                missing_fields.append('Payment Reference')

            if missing_fields:
                raise UserError(f"Cannot submit for approval. Please fill in all required fields: {', '.join(missing_fields)}")

            rec.state = 'approval'

    def action_approve(self):
        for rec in self:
            if not rec.is_approver:
                raise UserError("You are not authorized to approve this reimbursement request.")
            rec.state = 'approved'
