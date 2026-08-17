# -*- coding: utf-8 -*-
import base64
import io

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.pdf import PdfFileReader, PdfFileWriter

from .proposal_content import DEFAULT_TERMS_HTML

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
    proposal_line_ids = fields.One2many(
        'sale.order.proposal.line', 'order_id',
        string='Proposal Services', copy=True)
    proposal_executive_summary = fields.Text(
        string='Executive Summary',
        help="Opening paragraph of the proposal. Left empty, the PDF uses the "
             "standard KGRN opening for this client.")
    proposal_terms = fields.Html(
        string='Terms & Conditions', sanitize=False,
        default=lambda self: DEFAULT_TERMS_HTML,
        help="Overall terms printed at the end of the commercial section. "
             "Pre-filled with the standard KGRN payment terms; edit per proposal.")

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
        orders._log_crm_override()
        orders._sync_proposal_lines()
        return orders

    def write(self, vals):
        self._sync_crm_vals(vals)
        res = super().write(vals)
        if vals.get('crm_link_override') or 'crm_link_override_reason' in vals:
            self._log_crm_override()
        if 'order_line' in vals:
            self._sync_proposal_lines()
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

    @api.constrains('new_renewed', 'crm_pipeline_id',
                    'crm_link_override', 'crm_link_override_reason')
    def _check_crm_pipeline_required(self):
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

    # ── Proposal service lines ────────────────────────────────────────────
    def _prepare_proposal_line_vals(self, product, sequence):
        self.ensure_one()
        template = product.product_tmpl_id
        return {
            'order_id': self.id,
            'sequence': sequence,
            'product_id': product.id,
            'name': product.name,
            'code': product.default_code or False,
            'scope': template.proposal_scope,
            'methodology': template.proposal_methodology,
            'deliverables': template.proposal_deliverables,
        }

    def _sync_proposal_lines(self):
        """Keep one proposal narrative per product on the quotation.

        Adds narratives for newly added products (pre-filled from the product)
        and drops those whose product left the order. Existing narratives are
        never overwritten — edits made for this proposal survive.
        """
        proposal_line = self.env['sale.order.proposal.line']
        for order in self:
            if not isinstance(order.id, int):
                continue  # onchange/new record — nothing to persist against yet
            products = order.order_line.filtered(
                lambda line: line.product_id and not line.display_type
            ).mapped('product_id')
            stale = order.proposal_line_ids.filtered(
                lambda narrative: narrative.product_id not in products)
            if stale:
                stale.unlink()
            existing = order.proposal_line_ids.mapped('product_id')
            vals_list = [
                order._prepare_proposal_line_vals(product, (index + 1) * 10)
                for index, product in enumerate(products)
                if product not in existing
            ]
            if vals_list:
                proposal_line.create(vals_list)

    def action_refresh_proposal_lines(self):
        """Re-pull scope/methodology/deliverables from the products, discarding
        any per-proposal edits."""
        for order in self:
            order.proposal_line_ids.unlink()
            order._sync_proposal_lines()
        return True

    # ── Documents ─────────────────────────────────────────────────────────
    def _build_proposal_pdf(self):
        """Render the proposal and return the PDF bytes.

        The cover and closing pages need zero page margins to bleed to the paper
        edge; the content pages need an 18mm/16mm inset on every page. wkhtmltopdf
        clips all painting to the margin box and takes one set of margins per run,
        so the two halves are rendered separately and stitched back together here.
        """
        self.ensure_one()
        report = self.env['ir.actions.report']
        bleed, _dummy = report._render_qweb_pdf(
            'proposal_workflow_extended_rk.action_report_proposal_bleed', res_ids=self.ids)
        content, _dummy = report._render_qweb_pdf(
            'proposal_workflow_extended_rk.action_report_proposal_content', res_ids=self.ids)

        bleed_reader = PdfFileReader(io.BytesIO(bleed), strict=False)
        content_reader = PdfFileReader(io.BytesIO(content), strict=False)
        if len(bleed_reader.pages) != 2:
            raise UserError(_(
                "The proposal cover and closing pages rendered as %s page(s) "
                "instead of 2. Check the proposal report template.",
                len(bleed_reader.pages)))

        writer = PdfFileWriter()
        writer.addPage(bleed_reader.pages[0])          # cover
        for page in content_reader.pages:              # sections 1-11 + acceptance
            writer.addPage(page)
        writer.addPage(bleed_reader.pages[1])          # thank-you

        stream = io.BytesIO()
        writer.write(stream)
        return stream.getvalue()

    def action_download_proposal(self):
        self.ensure_one()
        if self.state not in ('draft', 'sent'):
            raise UserError(_(
                "The proposal can only be downloaded while this is still a "
                "quotation."))
        self._sync_proposal_lines()
        if not self.proposal_line_ids:
            raise UserError(_(
                "Add at least one product line to this quotation before "
                "downloading the proposal."))

        filename = 'Proposal - %s.pdf' % self.name
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(self._build_proposal_pdf()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }

    def _build_se_pdf(self):
        """Render the Service Engagement Agreement — cover full-bleed, terms and
        schedules inset 20mm per `@page` in pdf.js `seHtml`."""
        self.ensure_one()
        report = self.env['ir.actions.report']
        cover, _dummy = report._render_qweb_pdf(
            'proposal_workflow_extended_rk.action_report_se_cover', res_ids=self.ids)
        body, _dummy = report._render_qweb_pdf(
            'proposal_workflow_extended_rk.action_report_se_content', res_ids=self.ids)

        writer = PdfFileWriter()
        for page in PdfFileReader(io.BytesIO(cover), strict=False).pages:
            writer.addPage(page)
        for page in PdfFileReader(io.BytesIO(body), strict=False).pages:
            writer.addPage(page)
        stream = io.BytesIO()
        writer.write(stream)
        return stream.getvalue()

    def action_download_se(self):
        self.ensure_one()
        if not self.is_service_engagement_stage:
            raise UserError(_(
                "The Service Engagement Agreement becomes available once this "
                "quotation is approved."))
        self._sync_proposal_lines()
        if not self.proposal_line_ids:
            raise UserError(_(
                "Add at least one product line to this quotation before "
                "downloading the agreement."))
        if not self.se_effective_date:
            self.se_effective_date = fields.Date.context_today(self)

        filename = 'Service Engagement - %s.pdf' % self.name
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(self._build_se_pdf()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }

    def action_approve_order(self):
        """Stamp the agreement's effective date at the moment of approval."""
        res = super().action_approve_order()
        for order in self.filtered(
                lambda o: o.approval_state == 'approved' and not o.se_effective_date):
            order.se_effective_date = fields.Date.context_today(order)
        return res


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # The Proposal tab follows the products on the quotation. Editing the order
    # through the form writes order_line on the order (handled in SaleOrder.write),
    # but imports, server actions and renewals touch the lines directly — so the
    # narratives are kept in step from here as well.
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.order_id._sync_proposal_lines()
        return lines

    def write(self, vals):
        orders = self.order_id
        res = super().write(vals)
        if 'product_id' in vals:
            (orders | self.order_id)._sync_proposal_lines()
        return res

    def unlink(self):
        orders = self.order_id
        res = super().unlink()
        orders.exists()._sync_proposal_lines()
        return res
