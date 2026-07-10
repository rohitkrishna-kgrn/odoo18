# -*- coding: utf-8 -*-
import json
import secrets

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .discovery_schema import DISCOVERY_SECTIONS


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    einvoicing_service = fields.Boolean(
        string='eInvoicing Service', tracking=True,
        help="Enable when this opportunity concerns the eInvoicing service. "
             "The client discovery form can only be sent for such opportunities.")
    sale_order_id = fields.Many2one(
        'sale.order', string='Sale Order', copy=False, readonly=True,
        help="Quotation / sale order created from this pipeline.")

    # Stage flags used to show/hide the manual stage buttons in the header.
    is_stage_new = fields.Boolean(compute='_compute_stage_flags')
    is_stage_lost = fields.Boolean(compute='_compute_stage_flags')

    @api.depends('stage_id')
    def _compute_stage_flags(self):
        new_stage = self.env.ref('crm.stage_lead1', raise_if_not_found=False)
        lost_stage = self.env.ref('crm_extended_rk.stage_lost', raise_if_not_found=False)
        for lead in self:
            lead.is_stage_new = bool(new_stage and lead.stage_id == new_stage)
            lead.is_stage_lost = bool(lost_stage and lead.stage_id == lost_stage)
    discovery_token = fields.Char(
        string='Discovery Access Token', copy=False, index=True, readonly=True)
    discovery_form_state = fields.Selection(
        selection=[
            ('not_sent', 'Not Sent'),
            ('sent', 'Sent'),
            ('submitted', 'Submitted'),
        ],
        string='Discovery Form Status', default='not_sent', copy=False, tracking=True)
    discovery_sent_date = fields.Datetime(string='Discovery Sent On', copy=False, readonly=True)
    discovery_submitted_date = fields.Datetime(
        string='Discovery Submitted On', copy=False, readonly=True)
    # Raw submitted answers (JSON) kept for programmatic use / re-rendering.
    discovery_data = fields.Text(string='Discovery Data (JSON)', copy=False, readonly=True)
    # Human-readable rendering shown in the notebook page.
    discovery_summary = fields.Html(
        string='Discovery Form Submission', copy=False, readonly=True, sanitize=False)
    discovery_signature = fields.Binary(string='Discovery Signature', copy=False, attachment=True)

    # ==================================================================
    # Pipeline stage automation
    #   Draft quotation created ----> Proposition   (see sale_order.py)
    #   Approved / Confirmed / Cancelled ------------> SE / Won / Lost
    #   Lost button ----------------> Lost stage
    #   Manual buttons: New -> Qualified, Lost -> New
    # ==================================================================
    def _move_stage(self, stage_xmlid):
        stage = self.env.ref(stage_xmlid, raise_if_not_found=False)
        if stage:
            self.write({'stage_id': stage.id, 'active': True})

    def action_move_to_qualified(self):
        """Header button shown while in the New stage."""
        self._move_stage('crm.stage_lead2')

    def action_move_to_new(self):
        """Header button shown while in the Lost stage."""
        self._move_stage('crm.stage_lead1')

    def action_set_lost(self, **additional_values):
        # The standard "Lost" button archives the lead; in addition we drop it
        # into the dedicated "Lost" pipeline column and keep it visible there.
        res = super().action_set_lost(**additional_values)
        lost_stage = self.env.ref('crm_extended_rk.stage_lost', raise_if_not_found=False)
        if lost_stage:
            self.write({'stage_id': lost_stage.id, 'active': True})
        return res

    # ------------------------------------------------------------------
    # Token / URL helpers
    # ------------------------------------------------------------------
    def _get_discovery_url(self):
        self.ensure_one()
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return '%s/discovery-form/%s' % (base.rstrip('/'), self.discovery_token)

    def _discovery_prefill(self):
        """Values pushed into the public form so the client doesn't retype them."""
        self.ensure_one()
        company = self.partner_name or (self.partner_id.name if self.partner_id else '')
        return {
            'company_name': company or '',
            'contact_name': self.contact_name or (self.partner_id.name if self.partner_id else ''),
            'email': self.email_from or '',
            'phone': self.phone or self.mobile or '',
        }

    # ------------------------------------------------------------------
    # Send / resend
    # ------------------------------------------------------------------
    def action_send_discovery_form(self):
        self.ensure_one()
        if not self.einvoicing_service:
            raise UserError(_(
                "The discovery form is only available for eInvoicing Service "
                "opportunities. Enable 'eInvoicing Service' first."))
        if not self.email_from:
            raise UserError(_(
                "Please set the email address on this pipeline before sending the "
                "discovery form."))

        is_resend = bool(self.discovery_token)
        if not self.discovery_token:
            self.discovery_token = secrets.token_urlsafe(24)

        url = self._get_discovery_url()
        self.write({
            'discovery_form_state': 'sent',
            'discovery_sent_date': fields.Datetime.now(),
        })

        # Email the client the unique link.
        self._send_discovery_email(url)

        # Log to chatter.
        verb = _("resent") if is_resend else _("sent")
        self.message_post(
            body=Markup(
                '<p>📋 Discovery form <strong>%s</strong> to '
                '<a href="mailto:%s">%s</a>.</p>'
                '<p>Unique link: <a href="%s" target="_blank">%s</a></p>'
            ) % (verb, self.email_from, self.email_from, url, url),
            subject=_("Discovery Form %s") % verb.capitalize(),
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Discovery Form %s") % verb.capitalize(),
                'message': _("The discovery form link has been %s to %s.") % (verb, self.email_from),
                # Reload the record so the button flips to "Resend" and the
                # status badge updates.
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'crm.lead',
                    'res_id': self.id,
                    'views': [[False, 'form']],
                    'target': 'current',
                },
            },
        }

    def _send_discovery_email(self, url):
        """Email the client a branded message carrying the unique form link."""
        self.ensure_one()
        company = self.company_id or self.env.company
        contact = self.contact_name or self.partner_name or _("there")
        body = Markup(
            '<div style="font-family:Segoe UI,Arial,sans-serif;color:#1f2937;'
            'max-width:560px;margin:auto;border:1px solid #e5e9ef;border-radius:12px;'
            'overflow:hidden;">'
            '<div style="background:linear-gradient(135deg,#0d2b45,#1a4f72);'
            'padding:22px 26px;color:#fff;">'
            '<div style="font-size:18px;font-weight:700;">%(company)s</div>'
            '<div style="font-size:12px;letter-spacing:1.5px;text-transform:uppercase;'
            'opacity:.75;">Client Discovery Form</div>'
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
        ) % {'company': company.name, 'contact': contact, 'url': url}

        mail = self.env['mail.mail'].sudo().create({
            'subject': _("%s — Client Discovery Form") % company.name,
            'email_from': (company.email or self.env.user.email_formatted),
            'email_to': self.email_from,
            'body_html': body,
            'model': 'crm.lead',
            'res_id': self.id,
            'auto_delete': False,
        })
        mail.send()

    # ------------------------------------------------------------------
    # Submission (called from the public controller, sudo)
    # ------------------------------------------------------------------
    def _apply_discovery_submission(self, payload):
        """Store a validated submission payload coming from the public form."""
        self.ensure_one()
        signature_b64 = None
        raw_sig = payload.get('signatureData')
        if isinstance(raw_sig, str) and ',' in raw_sig:
            # data:image/png;base64,XXXX -> keep only the base64 part for a Binary field
            signature_b64 = raw_sig.split(',', 1)[1]

        vals = {
            'discovery_data': json.dumps(payload, ensure_ascii=False),
            'discovery_summary': self._build_discovery_summary(payload),
            'discovery_form_state': 'submitted',
            'discovery_submitted_date': fields.Datetime.now(),
        }
        if signature_b64:
            vals['discovery_signature'] = signature_b64
        self.write(vals)

        self.message_post(
            body=Markup(
                '<p>✅ <strong>Discovery form submitted</strong> by the client.</p>'
                '<p>See the <em>Discovery Form</em> tab for the full response.</p>'),
            subject=_("Discovery Form Submitted"),
        )
        self._notify_salesperson_submission()

    def _notify_salesperson_submission(self):
        """Email the assigned salesperson that the client completed the form."""
        self.ensure_one()
        user = self.user_id
        if not user or not user.email:
            return
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url').rstrip('/')
        lead_url = '%s/odoo/crm/%s' % (base, self.id)
        company = self.company_id or self.env.company
        body = Markup(
            '<div style="font-family:Segoe UI,Arial,sans-serif;color:#1f2937;'
            'max-width:560px;margin:auto;border:1px solid #e5e9ef;border-radius:12px;'
            'overflow:hidden;">'
            '<div style="background:linear-gradient(135deg,#0d2b45,#1a4f72);'
            'padding:20px 26px;color:#fff;font-size:16px;font-weight:700;">'
            'Discovery Form Submitted</div>'
            '<div style="padding:24px 26px;">'
            '<p>Hello %(user)s,</p>'
            '<p>The client has just submitted the discovery form for the opportunity '
            '<strong>%(lead)s</strong>.</p>'
            '<p style="text-align:center;margin:26px 0;">'
            '<a href="%(url)s" style="background:linear-gradient(135deg,#0d2b45,#1a4f72);'
            'color:#fff;text-decoration:none;padding:12px 26px;border-radius:9px;'
            'font-weight:600;display:inline-block;">Open the opportunity</a></p>'
            '<p style="font-size:13px;color:#6b7280;">Open the <em>Discovery Form</em> tab '
            'to review the responses or download the PDF.</p>'
            '</div></div>'
        ) % {'user': user.name, 'lead': self.name, 'url': lead_url}
        self.env['mail.mail'].sudo().create({
            'subject': _("Discovery form submitted — %s") % self.name,
            'email_from': (company.email or self.env.user.email_formatted),
            'email_to': user.email,
            'body_html': body,
            'model': 'crm.lead',
            'res_id': self.id,
            'auto_delete': False,
        }).send()

    # ------------------------------------------------------------------
    # PDF export (shown as a button in the notebook after submission)
    # ------------------------------------------------------------------
    def action_download_discovery_pdf(self):
        self.ensure_one()
        return self.env.ref(
            'crm_extended_rk.action_report_discovery_form').report_action(self)

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

    def _build_discovery_summary(self, payload):
        self.ensure_one()
        rows = Markup('')
        for section in DISCOVERY_SECTIONS:
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

        return Markup(
            '<div class="disc-summary">'
            '<table class="table table-sm disc-table">%s%s</table>'
            '</div>'
        ) % (rows, sig_block)
