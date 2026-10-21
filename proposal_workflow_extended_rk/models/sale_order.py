# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

SE_STAGE_XMLID = 'crm_extended_rk.stage_service_engagement'


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ── CRM pipeline link ─────────────────────────────────────────────────
    crm_pipeline_id = fields.Many2one(
        'crm.lead', string='CRM Pipeline', copy=False, tracking=True,
        domain="[('type', '=', 'opportunity')]",
        help="Pipeline record this quotation originates from. Kept in sync with "
             "the Opportunity field, so the CRM stage automation continues to work.")
    crm_ref = fields.Char(
        related='crm_pipeline_id.crm_ref', string='CRM Reference', readonly=True)
    crm_link_override = fields.Boolean(
        string='Proceed Without CRM Pipeline', copy=False, tracking=True,
        help="Tick to save a new quotation that has no pipeline record behind it. "
             "A reason is required and is logged in the chatter.")
    crm_link_override_reason = fields.Text(string='Override Reason', copy=False)

    # ── Proposal narrative ────────────────────────────────────────────────
    proposal_name = fields.Char(
        string='Proposal Name',
        help="Printed on the cover of the proposal and the agreement, e.g. "
             "'eInvoicing Services' gives \"eInvoicing Services Proposal\". "
             "Left empty, the documents fall back to 'eInvoicing Services'.")

    # ── Service Engagement Agreement ──────────────────────────────────────
    se_agreement_type = fields.Char(
        string='Agreement Type', default='Service Engagement Agreement',
        help="Printed as the title on the Service Engagement Agreement cover.")
    se_effective_date = fields.Date(
        string='Effective Date',
        help="Date the agreement takes effect. Set automatically when the "
             "quotation is approved; editable afterwards.")
    se_project_duration = fields.Char(
        string='Engagement Duration', compute='_compute_se_project_duration',
        store=True, readonly=False,
        help="Shown on the agreement cover. Derived from the engagement dates on "
             "the order lines; override it here if the agreement says otherwise.")

    @api.depends('order_line.engagement_start', 'order_line.engagement_end')
    def _compute_se_project_duration(self):
        for order in self:
            lines = order.order_line.filtered(
                lambda line: line.engagement_start and line.engagement_end)
            if not lines:
                order.se_project_duration = order.se_project_duration or False
                continue
            start = min(lines.mapped('engagement_start'))
            end = max(lines.mapped('engagement_end'))
            months = (end.year - start.year) * 12 + end.month - start.month
            order.se_project_duration = (
                '%s months (%s – %s)' % (months, start.strftime('%b %Y'), end.strftime('%b %Y'))
                if months else start.strftime('%b %Y'))

    # Stamped when each document is actually produced — drives the dashboard.
    proposal_generated_on = fields.Datetime(
        string='Proposal Generated On', copy=False, readonly=True)
    se_generated_on = fields.Datetime(
        string='Agreement Generated On', copy=False, readonly=True)

    is_service_engagement_stage = fields.Boolean(
        compute='_compute_is_service_engagement_stage')

    @api.depends('crm_pipeline_id.stage_id', 'approval_state')
    def _compute_is_service_engagement_stage(self):
        """The agreement becomes available once the quotation is approved.

        Approving an order moves its pipeline record to Service Engagement
        (crm_extended_rk). Either signal is enough, so the button still appears
        if the stage was moved by hand or the automation was bypassed.
        """
        stage = self.env.ref(SE_STAGE_XMLID, raise_if_not_found=False)
        for order in self:
            order.is_service_engagement_stage = (
                order.approval_state == 'approved'
                or bool(stage and order.crm_pipeline_id.stage_id == stage))

    # ── CRM link <-> Opportunity synchronisation ──────────────────────────
    @api.model
    def _sync_crm_vals(self, vals):
        """Mirror the CRM pipeline link onto opportunity_id and vice versa.

        Both fields point at the same crm.lead: crm_pipeline_id is the one the
        sales team fills in, opportunity_id is what sale_crm and the stage
        automation in crm_extended_rk read.
        """
        if vals.get('crm_pipeline_id') and not vals.get('opportunity_id'):
            vals['opportunity_id'] = vals['crm_pipeline_id']
        elif vals.get('opportunity_id') and not vals.get('crm_pipeline_id'):
            vals['crm_pipeline_id'] = vals['opportunity_id']
        return vals

    @api.onchange('crm_pipeline_id')
    def _onchange_crm_pipeline_id(self):
        for order in self:
            if order.crm_pipeline_id:
                order.opportunity_id = order.crm_pipeline_id
                if not order.partner_id:
                    order.partner_id = order.crm_pipeline_id.partner_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._sync_crm_vals(vals)
        orders = super().create(vals_list)
        orders._check_crm_pipeline_required()
        orders._log_crm_override()
        return orders

    def write(self, vals):
        self._sync_crm_vals(vals)
        res = super().write(vals)
        if vals.get('crm_link_override') or 'crm_link_override_reason' in vals:
            self._log_crm_override()
        return res

    def _log_crm_override(self):
        for order in self.filtered(
                lambda o: o.crm_link_override and o.crm_link_override_reason):
            order.message_post(body=Markup(
                "<p><strong>%s</strong></p><p>%s</p>"
            ) % (
                _("Saved without a CRM pipeline record"),
                order.crm_link_override_reason,
            ))

    def _check_crm_pipeline_required(self):
        """Require a pipeline link (or a reasoned override) on a new quotation.

        Deliberately *not* an @api.constrains: it runs from create() only, so
        the rule applies to quotations being raised now. Quotations that already
        exist - including the ones that pre-date this module and have no
        pipeline record at all - stay editable without it.
        """
        for order in self:
            if order.new_renewed != 'new' or order.crm_pipeline_id:
                continue
            if not order.crm_link_override:
                raise ValidationError(_(
                    "A CRM Pipeline record is required on new quotations.\n\n"
                    "Link the pipeline record this quotation came from, or tick "
                    "'Proceed Without CRM Pipeline' and give a reason — the reason "
                    "is logged in the chatter."))
            if not (order.crm_link_override_reason or '').strip():
                raise ValidationError(_(
                    "Give a reason for proceeding without a CRM pipeline record. "
                    "It is logged in the chatter."))

    # ── Documents ─────────────────────────────────────────────────────────
    # Both PDFs are rendered by the KGRN eInvoicing PDF API; the payloads are
    # built in sale_order_pdf_api.py.
    def _attach_pdf(self, filename, datas):
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': datas,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }

    def _check_einvoicing_document(self):
        if not self.einvoicing_service:
            raise UserError(_(
                "The proposal documents are for eInvoicing engagements. Turn on "
                "eInvoicing Service on this quotation first."))

    def action_download_proposal(self):
        self.ensure_one()
        self._check_einvoicing_document()
        if self.state not in ('draft', 'sent'):
            raise UserError(_(
                "The proposal can only be downloaded while this is still a "
                "quotation."))
        # The document lists the client's entities from the discovery form.
        self._auto_fill_entities_from_discovery()
        datas = self._pdf_api_render('proposal', self._pdf_api_proposal_payload())
        self.proposal_generated_on = fields.Datetime.now()
        return self._attach_pdf('Proposal - %s.pdf' % self.name, datas)

    def action_download_se(self):
        self.ensure_one()
        self._check_einvoicing_document()
        if not self.is_service_engagement_stage:
            raise UserError(_(
                "The Service Engagement Agreement becomes available once this "
                "quotation is approved."))
        if not self.se_effective_date:
            self.se_effective_date = fields.Date.context_today(self)
        self._auto_fill_entities_from_discovery()
        datas = self._pdf_api_render(
            'service-engagement', self._pdf_api_service_engagement_payload())
        self.se_generated_on = fields.Datetime.now()
        return self._attach_pdf('Service Engagement - %s.pdf' % self.name, datas)

    def action_approve_order(self):
        """Stamp the agreement's effective date at the moment of approval."""
        res = super().action_approve_order()
        for order in self.filtered(
                lambda o: o.approval_state == 'approved' and not o.se_effective_date):
            order.se_effective_date = fields.Date.context_today(order)
        return res
