# -*- coding: utf-8 -*-
import json
import secrets

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .discovery_schema import form_selection, get_label, get_sections


class CrmLeadDiscoveryForm(models.Model):
    """One record per discovery form sent to a client for a given opportunity.

    An opportunity can have several of these over time (e.g. an eInvoicing
    form followed later by a Corporate Tax form, or a resend of the same
    type) — each keeps its own access token, status and submitted answers.
    """
    _name = 'crm.lead.discovery.form'
    _description = 'Client Discovery Form Submission'
    _order = 'create_date desc'
    _rec_name = 'form_label'

    lead_id = fields.Many2one('crm.lead', string='Opportunity', required=True,
                               ondelete='cascade', index=True)
    form_type = fields.Selection(selection='_selection_discovery_form_type',
                                  string='Discovery Form', required=True)
    form_label = fields.Char(string='Form', compute='_compute_form_label', store=True)
    token = fields.Char(string='Access Token', copy=False, index=True, readonly=True)
    state = fields.Selection(
        [('sent', 'Sent'), ('submitted', 'Submitted')],
        string='Status', default='sent', copy=False)
    sent_date = fields.Datetime(string='Sent On', copy=False, readonly=True)
    submitted_date = fields.Datetime(string='Submitted On', copy=False, readonly=True)
    # Raw submitted answers (JSON) kept for programmatic use / re-rendering.
    data = fields.Text(string='Discovery Data (JSON)', copy=False, readonly=True)
    # Human-readable rendering shown in the preview / PDF.
    summary = fields.Html(string='Client Response', copy=False, readonly=True, sanitize=False)
    signature = fields.Binary(string='Signature', copy=False, attachment=True)
    signature_attachment = fields.Binary(string='Signed Document', copy=False, attachment=True)
    signature_attachment_filename = fields.Char(string='Signed Document Filename', copy=False)
    # Copied from the opportunity at send time and kept on the submission, so a
    # resend keeps going to the same kind of recipient and the history shows
    # which forms the client actually received.
    on_behalf = fields.Boolean(
        string='On Behalf of', readonly=True, copy=False,
        help="This form was sent to the salesperson, to be filled in on the "
             "client's behalf. The client was not emailed.")

    def _selection_discovery_form_type(self):
        return form_selection()

    @api.depends('form_type')
    def _compute_form_label(self):
        for rec in self:
            rec.form_label = get_label(rec.form_type)

    # ------------------------------------------------------------------
    # Token / URL
    # ------------------------------------------------------------------
    def _get_url(self):
        self.ensure_one()
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return '%s/discovery-form/%s' % (base.rstrip('/'), self.token)

    # ------------------------------------------------------------------
    # Send / resend
    # ------------------------------------------------------------------
    def _recipient(self):
        """(email, name) this submission's link is emailed to - the salesperson
        when it is filled in on the client's behalf, the client otherwise."""
        self.ensure_one()
        return self.lead_id._discovery_recipient(self.on_behalf)

    def action_send(self):
        """(Re)send the email carrying this submission's unique link, to the
        client or - when filled in on their behalf - to the salesperson."""
        for sub in self:
            lead = sub.lead_id
            email, name = sub._recipient()
            is_resend = bool(sub.token)
            if not sub.token:
                sub.token = secrets.token_urlsafe(24)
            url = sub._get_url()
            if sub.state != 'submitted':
                sub.write({'state': 'sent', 'sent_date': fields.Datetime.now()})
            sub._send_email(url, email, name)

            verb = _("resent") if is_resend else _("sent")
            if sub.on_behalf:
                note = _("Sent to %s (salesperson, on the client's behalf)") % email
                body = Markup(
                    '<p>📋 <strong>%s</strong> discovery form <strong>%s</strong> to '
                    '<a href="mailto:%s">%s</a> to be filled in '
                    '<strong>on the client\'s behalf</strong> - the client was not '
                    'emailed.</p>'
                    '<p>Unique link: <a href="%s" target="_blank">%s</a></p>'
                ) % (sub.form_label, verb, email, email, url, url)
            else:
                note = _("Sent to %s") % email
                body = Markup(
                    '<p>📋 <strong>%s</strong> discovery form <strong>%s</strong> to '
                    '<a href="mailto:%s">%s</a>.</p>'
                    '<p>Unique link: <a href="%s" target="_blank">%s</a></p>'
                ) % (sub.form_label, verb, email, email, url, url)

            lead._log_journey_event(
                'discovery_sent',
                _("%(form)s discovery form %(verb)s") % {
                    'form': sub.form_label, 'verb': verb},
                note=note,
                discovery_form_id=sub.id)
            lead._journey_on_discovery_sent()
            lead.message_post(
                body=body,
                subject=_("Discovery Form %s") % verb.capitalize(),
            )

    def action_resend(self):
        """Row-level action: resending creates a brand new submission (its own
        fresh link/token) rather than mutating this one, so the Discovery
        Forms list keeps a full history of every send/resend as its own line."""
        new_subs = self.env['crm.lead.discovery.form']
        for sub in self:
            new_subs |= self.env['crm.lead.discovery.form'].create({
                'lead_id': sub.lead_id.id,
                'form_type': sub.form_type,
                'on_behalf': sub.on_behalf,
            })
        new_subs.action_send()

    def _send_email(self, url, email=None, name=None):
        """Email a branded message carrying the unique form link, to the client
        or - when the form is filled in on their behalf - to the salesperson."""
        self.ensure_one()
        lead = self.lead_id
        if email is None:
            email, name = self._recipient()
        company = lead.company_id or self.env.company
        client = lead.partner_name or lead.contact_name or (
            lead.partner_id.name if lead.partner_id else '') or _("the client")
        if self.on_behalf:
            self._send_on_behalf_email(url, email, name or _("there"), company, client)
            return
        contact = name or _("there")
        body = Markup(
            '<div style="font-family:Segoe UI,Arial,sans-serif;color:#1f2937;'
            'max-width:560px;margin:auto;border:1px solid #e5e9ef;border-radius:12px;'
            'overflow:hidden;">'
            '<div style="background:linear-gradient(135deg,#0d2b45,#1a4f72);'
            'padding:22px 26px;color:#fff;">'
            '<div style="font-size:18px;font-weight:700;">%(company)s</div>'
            '<div style="font-size:12px;letter-spacing:1.5px;text-transform:uppercase;'
            'opacity:.75;">%(form)s Discovery Form</div>'
            '</div>'
            '<div style="padding:26px;">'
            '<p>Dear %(contact)s,</p>'
            '<p>To help us understand your requirements, please complete our short '
            'discovery form. It only takes a few minutes and is organised into simple '
            'sections.</p>'
            '<p style="text-align:center;margin:28px 0;">'
            '<a href="%(url)s" style="background:linear-gradient(135deg,#0d2b45,#1a4f72);'
            'color:#fff;text-decoration:none;padding:13px 30px;border-radius:9px;'
            'font-weight:600;display:inline-block;">Open Discovery Form</a>'
            '</p>'
            '<p style="font-size:13px;color:#6b7280;">Or copy this link into your browser:'
            '<br/><a href="%(url)s">%(url)s</a></p>'
            '<p style="font-size:13px;color:#6b7280;">This link is unique to you. '
            'Please do not share it.</p>'
            '</div>'
            '<div style="background:#f5f7fa;padding:14px 26px;font-size:12px;color:#9ca3af;">'
            '© %(company)s. This message and the linked form are confidential.'
            '</div></div>'
        ) % {'company': company.name, 'contact': contact, 'url': url, 'form': self.form_label}

        mail = self.env['mail.mail'].sudo().create({
            'subject': _("%s — %s Discovery Form") % (company.name, self.form_label),
            'email_from': (company.email or self.env.user.email_formatted),
            'email_to': email,
            'body_html': body,
            'model': 'crm.lead',
            'res_id': lead.id,
            'auto_delete': False,
        })
        mail.send()

    def _send_on_behalf_email(self, url, email, name, company, client):
        """Same link, addressed to the salesperson who is completing the form
        for the client - so nothing in it reads as if the client received it."""
        self.ensure_one()
        lead = self.lead_id
        body = Markup(
            '<div style="font-family:Segoe UI,Arial,sans-serif;color:#1f2937;'
            'max-width:560px;margin:auto;border:1px solid #e5e9ef;border-radius:12px;'
            'overflow:hidden;">'
            '<div style="background:linear-gradient(135deg,#0d2b45,#1a4f72);'
            'padding:22px 26px;color:#fff;">'
            '<div style="font-size:18px;font-weight:700;">%(company)s</div>'
            '<div style="font-size:12px;letter-spacing:1.5px;text-transform:uppercase;'
            'opacity:.75;">%(form)s Discovery Form · On Behalf Of</div>'
            '</div>'
            '<div style="padding:26px;">'
            '<p>Hello %(user)s,</p>'
            '<p>This %(form)s discovery form is for you to complete on behalf of '
            '<strong>%(client)s</strong> (opportunity <strong>%(lead)s</strong>). '
            'The client has <strong>not</strong> been emailed.</p>'
            '<p style="text-align:center;margin:28px 0;">'
            '<a href="%(url)s" style="background:linear-gradient(135deg,#0d2b45,#1a4f72);'
            'color:#fff;text-decoration:none;padding:13px 30px;border-radius:9px;'
            'font-weight:600;display:inline-block;">Open Discovery Form</a>'
            '</p>'
            '<p style="font-size:13px;color:#6b7280;">Or copy this link into your browser:'
            '<br/><a href="%(url)s">%(url)s</a></p>'
            '<p style="font-size:13px;color:#6b7280;">This link is unique to this '
            'submission. Once you submit it, the answers appear on the opportunity.</p>'
            '</div>'
            '<div style="background:#f5f7fa;padding:14px 26px;font-size:12px;color:#9ca3af;">'
            '© %(company)s. This message and the linked form are confidential.'
            '</div></div>'
        ) % {'company': company.name, 'user': name, 'client': client,
             'lead': lead.name or '', 'url': url, 'form': self.form_label}

        self.env['mail.mail'].sudo().create({
            'subject': _("%(company)s — %(form)s Discovery Form (on behalf of %(client)s)") % {
                'company': company.name, 'form': self.form_label, 'client': client},
            'email_from': (company.email or self.env.user.email_formatted),
            'email_to': email,
            'body_html': body,
            'model': 'crm.lead',
            'res_id': lead.id,
            'auto_delete': False,
        }).send()

    # ------------------------------------------------------------------
    # Submission (called from the public controller, sudo)
    # ------------------------------------------------------------------
    def _apply_submission(self, payload):
        """Store a validated submission payload coming from the public form."""
        self.ensure_one()
        signature_b64 = None
        raw_sig = payload.get('signatureData')
        if isinstance(raw_sig, str) and ',' in raw_sig:
            # data:image/png;base64,XXXX -> keep only the base64 part for a Binary field
            signature_b64 = raw_sig.split(',', 1)[1]

        attach_b64 = None
        attach_name = None
        raw_attach = payload.get('signatureAttachment')
        if isinstance(raw_attach, dict):
            data_url = raw_attach.get('data')
            if isinstance(data_url, str) and ',' in data_url:
                attach_b64 = data_url.split(',', 1)[1]
                attach_name = raw_attach.get('name') or 'signed-document'

        vals = {
            'data': json.dumps(payload, ensure_ascii=False),
            'summary': self._build_summary(payload, attachment_name=attach_name),
            'state': 'submitted',
            'submitted_date': fields.Datetime.now(),
        }
        if signature_b64:
            vals['signature'] = signature_b64
        if attach_b64:
            vals['signature_attachment'] = attach_b64
            vals['signature_attachment_filename'] = attach_name
        self.write(vals)

        if self.on_behalf:
            event_name = _("%s discovery form completed on the client's behalf") % self.form_label
            chatter = Markup(
                '<p>✅ <strong>%s discovery form submitted</strong> on the client\'s '
                'behalf.</p>'
                '<p>See the Discovery Forms list for the full response.</p>'
            ) % self.form_label
        else:
            event_name = _("%s discovery form received back from client") % self.form_label
            chatter = Markup(
                '<p>✅ <strong>%s discovery form submitted</strong> by the client.</p>'
                '<p>See the Discovery Forms list for the full response.</p>'
            ) % self.form_label

        self.lead_id._log_journey_event(
            'discovery_received', event_name, discovery_form_id=self.id)
        self.lead_id._journey_on_discovery_received()
        self.lead_id.message_post(
            body=chatter,
            subject=_("Discovery Form Submitted"),
        )
        self._notify_salesperson()

    def _notify_salesperson(self):
        """Email the assigned salesperson that the client completed the form."""
        self.ensure_one()
        lead = self.lead_id
        user = lead.user_id
        if not user or not user.email:
            return
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url').rstrip('/')
        lead_url = '%s/odoo/crm/%s' % (base, lead.id)
        company = lead.company_id or self.env.company
        body = Markup(
            '<div style="font-family:Segoe UI,Arial,sans-serif;color:#1f2937;'
            'max-width:560px;margin:auto;border:1px solid #e5e9ef;border-radius:12px;'
            'overflow:hidden;">'
            '<div style="background:linear-gradient(135deg,#0d2b45,#1a4f72);'
            'padding:20px 26px;color:#fff;font-size:16px;font-weight:700;">'
            '%(form)s Discovery Form Submitted</div>'
            '<div style="padding:24px 26px;">'
            '<p>Hello %(user)s,</p>'
            '<p>The %(form)s discovery form for the opportunity <strong>%(lead)s</strong> '
            'has just been submitted %(who)s.</p>'
            '<p style="text-align:center;margin:26px 0;">'
            '<a href="%(url)s" style="background:linear-gradient(135deg,#0d2b45,#1a4f72);'
            'color:#fff;text-decoration:none;padding:12px 26px;border-radius:9px;'
            'font-weight:600;display:inline-block;">Open the opportunity</a></p>'
            '<p style="font-size:13px;color:#6b7280;">Open the Discovery Forms list '
            'to review the responses or download the PDF.</p>'
            '</div></div>'
        ) % {'user': user.name, 'lead': lead.name, 'url': lead_url,
             'form': self.form_label,
             'who': (_("on the client's behalf") if self.on_behalf else _("by the client"))}
        self.env['mail.mail'].sudo().create({
            'subject': _("Discovery form submitted — %s") % lead.name,
            'email_from': (company.email or self.env.user.email_formatted),
            'email_to': user.email,
            'body_html': body,
            'model': 'crm.lead',
            'res_id': lead.id,
            'auto_delete': False,
        }).send()

    # ------------------------------------------------------------------
    # PDF export / preview
    # ------------------------------------------------------------------
    def action_download_pdf(self):
        self.ensure_one()
        if self.state != 'submitted':
            raise UserError(_(
                "The client hasn't submitted this discovery form yet, so there's "
                "nothing to download."))
        return self.env.ref(
            'crm_extended_rk.action_report_discovery_form').report_action(self)

    def action_preview(self):
        self.ensure_one()
        return {
            'name': self.form_label,
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead.discovery.form',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [[self.env.ref('crm_extended_rk.crm_lead_discovery_form_view_form').id, 'form']],
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Summary rendering
    # ------------------------------------------------------------------
    @staticmethod
    def _option_label(field, value):
        for o in field.get('options') or []:
            if isinstance(o, dict) and o.get('value') == value:
                return o.get('label')
        return value

    def _format_answer(self, field, value):
        """Return an HTML fragment for a single answer value."""
        if value in (None, '', [], {}):
            return Markup('<span class="disc-empty">—</span>')
        if field['type'] == 'checkbox' and isinstance(value, list):
            labels = [self._option_label(field, v) for v in value]
            items = Markup('').join(Markup('<li>%s</li>') % l for l in labels)
            return Markup('<ul class="disc-list">%s</ul>') % items
        if field['type'] in ('select', 'radio'):
            return Markup('%s') % self._option_label(field, value)
        if field['type'] == 'checkbox_single':
            return Markup('Confirmed') if value else Markup('Not confirmed')
        return Markup('%s') % value

    def _build_summary(self, payload, attachment_name=None):
        self.ensure_one()
        rows = Markup('')
        for section in get_sections(self.form_type):
            body = Markup('')
            for field in section['fields']:
                if field['type'] == 'signature':
                    continue
                answer = self._format_answer(field, payload.get(field['key']))
                body += Markup(
                    '<tr><td class="disc-q">%s</td><td class="disc-a">%s</td></tr>'
                ) % (field['label'], answer)

            # Per-entity sub-form
            if section.get('entities'):
                entities = payload.get('entities') or []
                for idx, ent in enumerate(entities, start=1):
                    ent_rows = Markup('')
                    for ef in section['entities']['fields']:
                        answer = self._format_answer(ef, ent.get(ef['key']))
                        ent_rows += Markup(
                            '<tr><td class="disc-q">%s</td><td class="disc-a">%s</td></tr>'
                        ) % (ef['label'], answer)
                    body += Markup(
                        '<tr><td colspan="2" class="disc-subhead">Entity %s</td></tr>%s'
                    ) % (idx, ent_rows)

            rows += Markup(
                '<tr><td colspan="2" class="disc-section">%s &nbsp;·&nbsp; %s</td></tr>%s'
            ) % (section['id'], section['title'], body)

        sig = payload.get('signatureData')
        sig_block = Markup('')
        if isinstance(sig, str) and sig.startswith('data:image'):
            sig_block = Markup(
                '<tr><td colspan="2" class="disc-section">Signature</td></tr>'
                '<tr><td colspan="2"><img src="%s" '
                'style="max-height:120px;border:1px solid #d1d5db;border-radius:6px;'
                'padding:6px;background:#fff;"/></td></tr>'
            ) % sig

        if attachment_name:
            sig_block += Markup(
                '<tr><td colspan="2">Attached document: '
                '<a href="/web/content/crm.lead.discovery.form/%s/signature_attachment/%s'
                '?download=true" target="_blank">%s</a></td></tr>'
            ) % (self.id, attachment_name, attachment_name)

        return Markup(
            '<div class="disc-summary">'
            '<table class="table table-sm disc-table">%s%s</table>'
            '</div>'
        ) % (rows, sig_block)
