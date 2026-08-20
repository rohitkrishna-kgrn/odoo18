from odoo import models, fields
from odoo.exceptions import UserError
from markupsafe import Markup


class UpsellingApprovalRemarkWizard(models.TransientModel):
    _name = 'upselling.approval.remark.wizard'
    _description = 'Upselling Submit for Approval Remark'

    upselling_id = fields.Many2one('upselling', string='Upselling', required=True)
    remark = fields.Text(string='Remark', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group('refund_management_rk.group_reimbursement_reviewer'):
            raise UserError("Only Reimbursement Reviewers can submit for approval.")
        rec = self.upselling_id
        if rec.state == 'rejected':
            raise UserError(
                "Upselling request %s has been rejected and can no longer be submitted "
                "for approval." % rec.sequence
            )
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
            missing_fields.append('Engagement Letter')
        if not rec.receipt_voucher_file:
            missing_fields.append('Receipt Voucher')
        if not rec.payment_received_datetime:
            missing_fields.append('Payment Received Date/Time')
        if not rec.payment_reference:
            missing_fields.append('Payment Reference')
        if missing_fields:
            raise UserError(
                f"Cannot submit for approval. Please fill in all required fields: {', '.join(missing_fields)}"
            )
        rec._check_documents_complete()
        rec.state = 'approval'
        rec.message_post(
            body=Markup('<span style="color:#1a73e8;">Remark :</span> <span style="color:#000000;">{}</span>').format(self.remark),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        # Notify approver by email
        approver = rec.company_id.approver_user_id
        if approver and approver.partner_id:
            rec.message_notify(
                partner_ids=[approver.partner_id.id],
                subject=f'Upselling {rec.sequence} - Submitted for Approval',
                body=Markup(
                    'Dear {},<br/><br/>'
                    'Upselling request <b>{}</b> has been submitted for your approval.<br/><br/>'
                    'Please review and take action.'
                ).format(approver.name, rec.sequence),
            )
        return {'type': 'ir.actions.act_window_close'}
