# -*- coding: utf-8 -*-
"""'Assign To' popup: pick a salesperson, create the pipeline record."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CrmMailLeadAssignWizard(models.TransientModel):
    _name = 'crm.mail.lead.assign.wizard'
    _description = 'Assign Mail Lead to Salesperson'

    # Deliberately not readonly/required at field level: since Odoo 16 the web
    # client does not send readonly fields back on save, so a readonly+required
    # x2many would arrive empty. The inner list is locked down in the view
    # instead, and action_assign() re-checks the content.
    mail_lead_ids = fields.Many2many('crm.mail.lead', string='Mail Leads')
    mail_lead_count = fields.Integer(compute='_compute_mail_lead_count')

    # No domain on purpose: the firm wants every user selectable here, not only
    # holders of a CRM group.
    user_id = fields.Many2one(
        'res.users', string='Salesperson', required=True,
        help="The CRM pipeline record is created for this user.")

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        if 'mail_lead_ids' in fields_list and not result.get('mail_lead_ids'):
            context = self.env.context
            ids = context.get('default_mail_lead_ids')
            if not ids and context.get('active_model') == 'crm.mail.lead':
                ids = context.get('active_ids')
            if ids:
                result['mail_lead_ids'] = [fields.Command.set(list(ids))]
        return result

    @api.depends('mail_lead_ids')
    def _compute_mail_lead_count(self):
        for wizard in self:
            wizard.mail_lead_count = len(wizard.mail_lead_ids)

    def action_assign(self):
        self.ensure_one()
        if not self.mail_lead_ids:
            raise UserError(_("There is nothing to assign."))
        if not self.user_id:
            raise UserError(_("Please choose a salesperson."))
        self.mail_lead_ids.action_assign_to_user(self.user_id)

        if len(self.mail_lead_ids) == 1 and self.mail_lead_ids.lead_id:
            # Single mail: drop the user straight into the new pipeline record.
            return self.mail_lead_ids.action_view_lead()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Assigned"),
                'message': _(
                    "%(count)s pipeline record(s) created for %(user)s.",
                    count=len(self.mail_lead_ids), user=self.user_id.display_name),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
