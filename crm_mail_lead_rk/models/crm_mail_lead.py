# -*- coding: utf-8 -*-
"""One incoming mail, waiting to be handed to a salesperson."""
import base64
import logging
from datetime import timedelta

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError
from odoo.osv import expression

_logger = logging.getLogger(__name__)

# New-lead alerts only go out for mail received within this window, so the
# 'Fetch Mails' backlog walk (which imports months-old history) stays silent.
NOTIFY_MAX_AGE = timedelta(days=3)


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

    email_from = fields.Char(
        string='From', readonly=True, index=True,
        help="The external client this mail is really from. When a colleague "
             "forwards an enquiry, this is the original sender read out of the "
             "forwarded mail — not the colleague, who is shown under "
             "'Forwarded By'. Empty means the mail came from an internal "
             "address and no external client could be identified in it — the "
             "mail is still imported in full, it simply has no client to "
             "show.")
    email_from_raw = fields.Char(string='From (raw)', readonly=True)
    contact_name = fields.Char(string='Contact Name', readonly=True)
    forwarded_by = fields.Char(
        string='Forwarded By', readonly=True, index=True,
        help="The internal colleague whose address was on the From header. "
             "Set whenever the mail came in from an @kgrnaudit.com address — "
             "forwarded or not — so the sender is never lost even though it "
             "is kept out of From (Client). Empty when the client wrote in "
             "directly.")
    sender_source = fields.Selection(
        [('header', 'From header'),
         ('forwarded', 'Forwarded header block'),
         ('headers', 'Forwarding headers'),
         ('body', 'Address in the message body'),
         ('unknown', 'Not identified'),
         ('internal', 'Internal mail, no client found')],
        string='Sender Identified From', readonly=True, default='header',
        help="How the From address above was worked out. Anything other "
             "than 'From header' means the mail arrived forwarded by internal "
             "staff and the client was read out of its content.")
    email_to = fields.Char(string='To', readonly=True)
    email_cc = fields.Char(string='Cc', readonly=True)
    date_received = fields.Datetime(string='Received On', readonly=True, index=True)
    body = fields.Html(string='Message', readonly=True, sanitize_style=True)
    message_id = fields.Char(string='Message-Id', readonly=True, index=True)

    keyword_match = fields.Boolean(
        string='Keyword Match', default=True, readonly=True, index=True,
        help="Set when the subject or message contains one of the mailbox's "
             "Keywords. Unmatched mail is still imported but is hidden from "
             "the default Mail Leads list and sends no admin alert. Mail "
             "imported before keywords existed counts as matched.")
    matched_keyword = fields.Char(
        string='Matched Keyword', readonly=True,
        help="The mailbox keyword found in this mail.")

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

    # ------------------------------------------------------------------
    # Unmatched mail is hidden from the list unless asked for
    # ------------------------------------------------------------------
    @api.model
    def _hide_unmatched_domain(self, domain):
        """Add ``keyword_match = True`` unless the domain already filters on
        ``keyword_match`` (the 'Not Matched' filter) - the same idea as
        Odoo's ``active`` field, but limited to what the list view loads, so
        the fetch dedup, the Assign wizard and counts still see every mail.
        """
        if self.env.context.get('crm_mail_lead_show_unmatched'):
            return domain

        def mentions(node):
            if isinstance(node, (list, tuple)):
                if len(node) == 3 and isinstance(node[0], str) \
                        and node[0].split('.')[0] == 'keyword_match':
                    return True
                return any(mentions(child) for child in node)
            return False

        if mentions(domain or []):
            return domain
        return expression.AND([domain or [], [('keyword_match', '=', True)]])

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None,
                        order=None, count_limit=None):
        return super().web_search_read(
            self._hide_unmatched_domain(domain), specification, offset=offset,
            limit=limit, order=order, count_limit=count_limit)

    @api.model
    def web_read_group(self, domain, fields, groupby, limit=None, offset=0,
                       orderby=False, lazy=True):
        return super().web_read_group(
            self._hide_unmatched_domain(domain), fields, groupby, limit=limit,
            offset=offset, orderby=orderby, lazy=lazy)

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
                    "%(date)s in the %(tag)s mailbox, from %(sender)s.%(forwarded)s "
                    "Assigned to %(user)s by %(actor)s.",
                    subject=record.name or '',
                    date=fields.Datetime.to_string(record.date_received) or '',
                    tag=record.tag_id.display_name or _("(untagged)"),
                    sender=record.email_from or _("an unidentified sender"),
                    forwarded=(
                        _(" Forwarded by %s.", record.forwarded_by)
                        if record.forwarded_by else ''),
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
        if assigned and not (
                self.env.user.has_group('sales_team.group_sale_manager')
                or self.env.user.has_group('crm_mail_lead_rk.group_crm_mail_lead_admin')):
            raise UserError(_(
                "Assigned mail leads keep the audit trail to the pipeline record "
                "and can only be deleted by a Sales Manager or a Mail Leads "
                "Administrator."))
        return super().unlink()

    # ------------------------------------------------------------------
    # New-lead alert to Mail Leads Administrators
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._notify_mail_lead_admins()
        return records

    def _notify_mail_lead_admins(self):
        """E-mail every Mail Leads Administrator who picked this lead's tag.

        Only mail that is genuinely new is announced: anything received more
        than NOTIFY_MAX_AGE ago (the 'Fetch Mails' backlog walk importing old
        history) is skipped, so a backlog import can never send a flood of
        alerts. A failure here is logged and swallowed - an alert must never
        stop a mail from being imported.
        """
        admin_group = self.env.ref(
            'crm_mail_lead_rk.group_crm_mail_lead_admin', raise_if_not_found=False)
        template = self.env.ref(
            'crm_mail_lead_rk.mail_template_new_mail_lead', raise_if_not_found=False)
        if not admin_group or not template:
            return
        admins = admin_group.sudo().users.filtered(
            lambda user: user.active and user.email
            and user.crm_mail_lead_notify_tag_ids)
        if not admins:
            return
        oldest = fields.Datetime.now() - NOTIFY_MAX_AGE
        for record in self:
            if not record.tag_id or not record.keyword_match:
                continue
            if record.date_received and record.date_received < oldest:
                continue
            recipients = admins.filtered(
                lambda user: record.tag_id in user.crm_mail_lead_notify_tag_ids)
            if not recipients:
                continue
            try:
                # Queued as an outgoing e-mail only (Settings > Technical >
                # Email > Emails), sent by the standard mail queue cron - no
                # chatter post, no Discuss notification. auto_delete is forced
                # off so every alert stays listed there with its Sent /
                # Exception status, whatever the template says.
                template.sudo().send_mail(
                    record.id,
                    email_values={
                        'recipient_ids': [
                            fields.Command.set(recipients.partner_id.ids)],
                        'auto_delete': False,
                    },
                )
            except Exception:  # noqa: BLE001 - never block the import
                _logger.warning(
                    "Mail Lead %s: could not queue the admin alert.",
                    record.id, exc_info=True)

    def _get_alert_snippet(self, limit=600):
        """First few hundred characters of the mail, as plain text."""
        self.ensure_one()
        text = tools.html2plaintext(self.body or '').strip()
        return text if len(text) <= limit else text[:limit].rstrip() + '...'

    def _get_alert_url(self):
        """Deep link to this Mail Lead for the alert e-mail."""
        self.ensure_one()
        return '%s/odoo/action-crm_mail_lead_rk.crm_mail_lead_action/%s' % (
            self.get_base_url(), self.id)
