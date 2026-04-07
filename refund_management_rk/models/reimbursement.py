import logging
from odoo import models, fields, api
import xlsxwriter
import base64
import io
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    approver_user_id = fields.Many2one(
        'res.users', string='Reimbursement / Upselling Approver',
        help='User authorized to approve reimbursement and upselling requests.'
    )


class Reimbursement(models.Model):
    _name = 'reimbursement'
    _description = 'Reimbursement Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Reference", required=True, copy=False, readonly=True, default='New')
    user_id = fields.Many2one('res.users', string="Employee", default=lambda self: self.env.user, readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('reviewed', 'Reviewed'),
        ('approved', 'Approved'),
    ], default='draft', tracking=True)

    line_ids = fields.One2many('reimbursement.line', 'reimbursement_id', string="Lines")
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    is_approver = fields.Boolean(compute='_compute_is_approver')
    total_amount = fields.Float(string='Total Amount', compute='_compute_total_amount', store=True)

    @api.depends('company_id')
    def _compute_is_approver(self):
        current_user = self.env.user
        for rec in self:
            company_approver = rec.company_id.approver_user_id
            rec.is_approver = bool(company_approver and company_approver.id == current_user.id)

    @api.depends('line_ids.bill_amount')
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped('bill_amount'))

    def action_submit(self):
        for rec in self:
            rec.state = 'submitted'

    def action_review(self):
        for rec in self:
            rec.state = 'reviewed'

    def action_approve(self):
        for rec in self:
            if not rec.is_approver:
                raise UserError("You are not authorized to approve this reimbursement request.")
            rec.state = 'approved'

    def action_reset_draft(self):
        for rec in self:
            rec.state = 'draft'

    def write(self, vals):
        user = self.env.user
        is_reviewer = user.has_group('refund_management_rk.group_reimbursement_reviewer')
        for rec in self:
            if not is_reviewer and rec.state != 'draft':
                raise UserError("You can only modify this record in Draft state.")
        return super().write(vals)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('reimbursement.seq') or 'New'
        return super().create(vals)

    def download_reference_excel(self):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("Reference")

        headers = ['S.No', 'Bill Date', 'Purpose', 'Type', 'Bill Submitted', 'Bill Amount']
        bold = workbook.add_format({'bold': True})
        for col_num, header in enumerate(headers):
            worksheet.write(0, col_num, header, bold)

        for row_num, line in enumerate(self.line_ids, start=1):
            worksheet.write(row_num, 0, row_num)
            worksheet.write(row_num, 1, str(line.bill_date) if line.bill_date else '')
            worksheet.write(row_num, 2, line.purpose or '')
            worksheet.write(row_num, 3, line.bill_type or '')
            worksheet.write(row_num, 4, 'Yes' if line.bill_submitted else 'No')
            worksheet.write(row_num, 5, line.bill_amount or 0.0)

        workbook.close()
        output.seek(0)
        data = output.read()

        attachment = self.env['ir.attachment'].create({
            'name': f'Reimbursement_{self.name}.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(data),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }


class ReimbursementLine(models.Model):
    _name = 'reimbursement.line'
    _description = 'Reimbursement Line'

    reimbursement_id = fields.Many2one('reimbursement', string="Reimbursement")
    bill_date = fields.Date(string="Bill Date")
    purpose = fields.Char(string="Purpose")
    bill_type = fields.Char(string="Type")
    bill_submitted = fields.Boolean(string="Bill Submitted")
    bill_amount = fields.Float(string="Bill Amount")
    attachment = fields.Binary(string="Attachment")
    attachment_filename = fields.Char(string="Attachment Filename")
