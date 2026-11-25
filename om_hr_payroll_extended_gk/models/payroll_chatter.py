from odoo import _, api, models
from odoo.exceptions import UserError

# Payroll chatter: no emails and no attachments (user's decision 2026-11-25). The
# notification / payslip emails are sent without being posted on the record, the chatter's
# "Send message" and attach buttons are hidden (static/src/payroll_chatter.scss) and refused
# here; "Log note" (internal, never emailed) stays.
NO_MAIL_MODELS = ('payroll.country.batch', 'payroll.country.line')


class PayrollNoMailChatter(models.AbstractModel):
    _name = 'payroll.no.mail.chatter'
    _description = 'Payroll chatter without emails or attachments'

    def message_post(self, **kwargs):
        if kwargs.get('message_type', 'notification') == 'comment':
            if kwargs.get('attachment_ids') or kwargs.get('attachments'):
                raise UserError(_("Files cannot be attached in the payroll chatter."))
            subtype = kwargs.get('subtype_xmlid')
            if not subtype and kwargs.get('subtype_id'):
                subtype = self.env['mail.message.subtype'].browse(kwargs['subtype_id']).get_external_id().get(
                    kwargs['subtype_id'])
            if subtype == 'mail.mt_comment':
                raise UserError(_("Emails cannot be sent from the payroll chatter: use Log note."))
        return super().message_post(**kwargs)


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('res_model') in NO_MAIL_MODELS for vals in vals_list):
            raise UserError(_("Files cannot be attached in the payroll chatter."))
        return super().create(vals_list)
