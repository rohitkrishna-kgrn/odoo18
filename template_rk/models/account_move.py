from odoo import models, fields, api
from num2words import num2words

class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_invoice_send(self):
        """Override to send email with custom template and attach report."""
        self.ensure_one()
        template = self.env.ref('template_rk.email_template_invoice_rk', raise_if_not_found=False)
        if template:
            # Post message with template (attaches the report defined in template)
            self.message_post_with_template(template.id, composition_mode='comment')
        return super(AccountMove, self).action_invoice_send()

    def amount_to_words(self, amount):
        # Convert amount to words using the num2words library
        if amount:
            return num2words(amount, lang='en')  # adjust lang if needed
        return ''

    def _get_report_base_filename(self):
        return "Invoice"

    def _get_report_values(self, docids, data=None):
        docs = self.env['account.move'].browse(docids)
        bank_accounts = docs.company_id.bank_ids  # or whatever field you use to get banks
        return {
            'doc_ids': docids,
            'doc_model': 'account.move',
            'docs': docs,
            'bank_accounts': bank_accounts,
        }