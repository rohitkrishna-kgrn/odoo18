# -*- coding: utf-8 -*-
"""One incoming mail, waiting to be handed to a salesperson."""
import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CrmMailLead(models.Model):
    _name = 'crm.mail.lead'
    _description = 'CRM Mail Lead'
    _order = 'date_received desc, id desc'

    name = fields.Char(string='Subject', required=True, readonly=True)
    server_id = fields.Many2one(
        'crm.mail.server', string='Mailbox', required=True, readonly=True,
        ondelete='restrict', index=True)
    tag_id = fields.Many2one(
        'crm.tag', string='Tag', related='server_id.tag_id',
        store=True, readonly=True, index=True,
        help="Which inbox this mail arrived in.")

    email_from = fields.Char(string='From', readonly=True, index=True)
    email_from_raw = fields.Char(string='From (raw)', readonly=True)
    contact_name = fields.Char(string='Contact Name', readonly=True)
    email_to = fields.Char(string='To', readonly=True)
    email_cc = fields.Char(string='Cc', readonly=True)
    date_received = fields.Datetime(string='Received On', readonly=True, index=True)
    body = fields.Html(string='Message', readonly=True, sanitize_style=True)
    message_id = fields.Char(string='Message-Id', readonly=True, index=True)

    state = fields.Selection(
        [('new', 'New'), ('assigned', 'Assigned')],
        string='Status', default='new', required=True, readonly=True, index=True)
    user_id = fields.Many2one(
        'res.users', string='Assigned To', readonly=True, index=True,
        help="Salesperson the mail was handed to.")
    lead_id = fields.Many2one(
        'crm.lead', string='Pipeline Record', readonly=True, copy=False,
        ondelete='set null')
    assigned_by_id = fields.Many2one('res.users', string='Assigned By', readonly=True)
    assigned_date = fields.Datetime(string='Assigned On', readonly=True)

    attachment_ids = fields.Many2many(
        'ir.attachment', 'crm_mail_lead_attachment_rel',
        'mail_lead_id', 'attachment_id', string='Attachments', readonly=True)
    attachment_count = fields.Integer(compute='_compute_attachment_count')

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, readonly=True,
        default=lambda self: self.env.company)

    _sql_constraints = [
        ('message_uniq', 'unique(server_id, message_id)',
         'This mail has already been imported for this mailbox.'),
    ]

    @api.depends('attachment_ids')
    def _compute_attachment_count(self):
        for record in self:
            record.attachment_count = len(record.attachment_ids)

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------
    def _store_attachments(self, attachments):
        """Persist the ``_Attachment`` tuples handed back by ``message_parse``."""
        self.ensure_one()
        to_create = []
        for attachment in attachments:
            content = attachment.content
            if isinstance(content, str):
                content = content.encode()
            if not content:
                continue
            to_create.append({
                'name': attachment.fname or _('attachment'),
                'datas': base64.b64encode(content),
                'res_model': self._name,
                'res_id': self.id,
            })
        if to_create:
            created = self.env['ir.attachment'].sudo().create(to_create)
            self.sudo().write({'attachment_ids': [fields.Command.set(created.ids)]})
        return True

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------
    def action_fetch_mails(self):
        """'Fetch Mails' button in the Mail Leads list header.

        Arms a full import on every confirmed CRM mailbox — every message not
        yet a Mail Lead, read and unread, any age — pulls the first small
        batch synchronously so the list refreshes with results at once, then
        wakes the cron to drain the rest automatically in the background.
        ``self`` is an empty recordset (header button, no selection).
        """
        servers = self.env['crm.mail.server'].sudo().search([('state', '=', 'done')])
        return servers.action_fetch_mails()

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------
    def action_open_assign_wizard(self):
        """The 'Assign To' button, from the list row or the form header."""
        pending = self.filtered(lambda record: record.state == 'new')
        if not pending:
            raise UserError(_("The selected mail lead(s) are already assigned."))
        return {
            'name': _("Assign to Salesperson"),
            'type': 'ir.actions.act_window',
            'res_model': 'crm.mail.lead.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_mail_lead_ids': [fields.Command.set(pending.ids)],
                'active_model': 'crm.mail.lead',
                'active_ids': pending.ids,
            },
        }

    def action_view_lead(self):
        self.ensure_one()
        if not self.lead_id:
            raise UserError(_("This mail lead has no pipeline record yet."))
        return {
            'name': _("Pipeline"),
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'res_id': self.lead_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def _prepare_crm_lead_values(self, user):
        """Values for the CRM pipeline record created on assignment."""
        self.ensure_one()
        values = {
            'name': self.name or _("Mail Lead"),
            'type': 'opportunity',
            'user_id': user.id,
            'email_from': self.email_from or False,
            'contact_name': self.contact_name or False,
            'partner_name': self.contact_name or False,
            'description': self.body or False,
            'company_id': self.company_id.id,
        }
        if self.tag_id:
            values['tag_ids'] = [fields.Command.link(self.tag_id.id)]
        return values

    def action_assign_to_user(self, user):
        """Create the pipeline record(s) and close the mail lead(s)."""
        if not user:
            raise UserError(_("Please choose a salesperson."))
        already = self.filtered(lambda record: record.state == 'assigned')
        if already:
            raise UserError(_(
                "Already assigned: %s", ", ".join(already.mapped('name'))))

        # sudo: a salesperson only sees their own leads (crm.crm_rule_personal_lead),
        # so assigning a mail to a *colleague* would be refused on create. The
        # acting user is recorded on the mail lead and in the pipeline chatter.
        Lead = self.env['crm.lead'].sudo()
        for record in self:
            lead = Lead.create(record._prepare_crm_lead_values(user))
            if record.attachment_ids:
                record.attachment_ids.sudo().copy({
                    'res_model': 'crm.lead',
                    'res_id': lead.id,
                })
            lead.message_post(
                body=_(
                    "Created from the Mail Lead <b>%(subject)s</b> received on "
                    "%(date)s in the %(tag)s mailbox, from %(sender)s. "
                    "Assigned to %(user)s by %(actor)s.",
                    subject=record.name or '',
                    date=fields.Datetime.to_string(record.date_received) or '',
                    tag=record.tag_id.display_name or _("(untagged)"),
                    sender=record.email_from_raw or record.email_from or '',
                    user=user.display_name,
                    actor=self.env.user.display_name,
                ),
                subtype_xmlid='mail.mt_note',
            )
            record.sudo().write({
                'state': 'assigned',
                'user_id': user.id,
                'lead_id': lead.id,
                'assigned_by_id': self.env.user.id,
                'assigned_date': fields.Datetime.now(),
            })
        return True

    def unlink(self):
        assigned = self.filtered(lambda record: record.state == 'assigned')
        if assigned and not self.env.user.has_group('sales_team.group_sale_manager'):
            raise UserError(_(
                "Assigned mail leads keep the audit trail to the pipeline record "
                "and can only be deleted by a Sales Manager."))
        return super().unlink()
