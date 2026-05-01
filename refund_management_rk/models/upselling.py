from odoo import models, fields, api
from odoo.exceptions import UserError
from markupsafe import Markup

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

    # Payment details
    payment_received_datetime = fields.Datetime(string='Payment Received Date/Time', tracking=True)
    payment_reference = fields.Char(string='Payment Reference', tracking=True)

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
        if vals.get('sequence', 'New') == 'New':
            vals['sequence'] = self.env['ir.sequence'].next_by_code('upselling.sequence') or 'New'
        if vals.get('sale_order_id') and not vals.get('customer_id'):
            sale_order = self.env['sale.order'].browse(vals['sale_order_id'])
            vals['customer_id'] = sale_order.partner_id.id if sale_order.partner_id else False
        return super(Upselling, self).create(vals)

    def write(self, vals):
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
                invoices = rec.sale_order_id.invoice_ids.filtered(
                    lambda inv: inv.move_type == 'out_invoice'
                )
                rec.invoice_ids = invoices
                rec.invoice_count = len(invoices)
            else:
                rec.invoice_ids = False
                rec.invoice_count = 0

    # State transition buttons
    def action_submit_review(self):
        for rec in self:
            rec.state = 'review'
            # Notify all reviewers by email
            reviewer_group = self.env.ref(
                'refund_management_rk.group_reimbursement_reviewer', raise_if_not_found=False
            )
            if reviewer_group:
                partner_ids = reviewer_group.users.mapped('partner_id').ids
                if partner_ids:
                    rec.message_notify(
                        partner_ids=partner_ids,
                        subject=f'Upselling {rec.sequence} - Submitted for Review',
                        body=Markup(
                            'Dear Reviewer,<br/><br/>'
                            'Upselling request <b>{}</b> has been submitted for review by {}.<br/><br/>'
                            'Please review and take action.'
                        ).format(rec.sequence, rec.user_id.name),
                    )

    def action_submit_approval(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Submit for Approval',
            'res_model': 'upselling.approval.remark.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_upselling_id': self.id},
        }

    def action_approve(self):
        for rec in self:
            if not rec.is_approver:
                raise UserError("You are not authorized to approve this upselling request.")
            rec.state = 'approved'

    def action_resubmit(self):
        self.ensure_one()
        if not self.env.user.has_group('refund_management_rk.group_reimbursement_reviewer'):
            raise UserError("Only Reimbursement Reviewers can request a resubmission.")
        return {
            'type': 'ir.actions.act_window',
            'name': 'Request Resubmission',
            'res_model': 'upselling.resubmit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_upselling_id': self.id},
        }

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoices',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.invoice_ids.ids)],
        }
