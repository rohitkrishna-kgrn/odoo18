import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class AttachBillsWizard(models.TransientModel):
    _name = 'attach.bills.wizard'
    _description = 'Attach Bills to Reimbursement Lines'

    line_ids = fields.One2many('attach.bills.line.wizard', 'wizard_id', string="Bill Lines")

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        lines = []
        for line in self.env.context.get('parsed_lines', []):
            lines.append((0, 0, {
                'bill_date': line['bill_date'],
                'purpose': line['purpose'],
                'bill_type': line['bill_type'],
                'bill_submitted': line['bill_submitted'],
                'bill_amount': line['bill_amount'],
            }))
        res['line_ids'] = lines
        return res

    def action_submit(self):
        lines_data = []
        for l in self.line_ids:
            _logger.info("Line to submit: date=%s, purpose=%s, type=%s, amount=%s, attachment=%s",
                         l.bill_date, l.purpose, l.bill_type, l.bill_amount, l.attachment_filename)
            lines_data.append((0, 0, {
                'bill_date': l.bill_date,
                'purpose': l.purpose,
                'bill_type': l.bill_type,
                'bill_submitted': l.bill_submitted,
                'bill_amount': l.bill_amount,
                'attachment': l.attachment,
                'attachment_filename': l.attachment_filename,
            }))

        reimbursement_id = self.env.context.get('reimbursement_id')
        reimbursement_model = self.env['reimbursement']

        if reimbursement_id:
            reimbursement = reimbursement_model.browse(reimbursement_id)
            if reimbursement.exists():
                # Add new lines to existing reimbursement record
                reimbursement.write({
                    'line_ids': lines_data,
                })
                _logger.info("Added lines to existing reimbursement ID: %s", reimbursement.id)
            else:
                # Fallback to creating new if ID invalid
                reimbursement = reimbursement_model.create({
                    'line_ids': lines_data,
                })
                _logger.info("Reimbursement created with ID: %s and name: %s", reimbursement.id, reimbursement.name)
        else:
            # Create new reimbursement if no ID provided
            reimbursement = reimbursement_model.create({
                'line_ids': lines_data,
            })
            _logger.info("Reimbursement created with ID: %s and name: %s", reimbursement.id, reimbursement.name)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'reimbursement',
            'res_id': reimbursement.id,
            'view_mode': 'form',
            'target': 'current',
        }


class AttachBillsLineWizard(models.TransientModel):
    _name = 'attach.bills.line.wizard'
    _description = 'Attach Bill Lines Wizard'

    wizard_id = fields.Many2one('attach.bills.wizard', string="Wizard")
    bill_date = fields.Date(string="Bill Date")
    purpose = fields.Char(string="Purpose")
    bill_type = fields.Char(string="Type")
    bill_submitted = fields.Boolean(string="Bill Submitted")
    bill_amount = fields.Float(string="Bill Amount")
    attachment = fields.Binary(string="Attachment")
    attachment_filename = fields.Char(string="Attachment Filename")