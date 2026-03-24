import logging
from odoo import models, fields, api
import xlsxwriter
import base64
import io
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class Reimbursement(models.Model):
    _name = 'reimbursement'
    _description = 'Reimbursement Request'
    _inherit = ['mail.thread']

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

    @api.depends('company_id')
    def _compute_is_approver(self):
        current_user = self.env.user
        for rec in self:
            company_approver = rec.company_id.approver_user_id
            rec.is_approver = company_approver and company_approver.id == current_user.id

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

        headers = ['S.No', 'Bill Date', 'Purpose', 'Type', 'Bill submitted', 'Bill Amount']
        for col_num, header in enumerate(headers):
            worksheet.write(0, col_num, header)


        workbook.close()
        output.seek(0)
        data = output.read()

        attachment = self.env['ir.attachment'].create({
            'name': 'Reimbursement_Reference.xlsx',
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