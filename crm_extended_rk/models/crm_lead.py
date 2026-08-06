# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .discovery_schema import form_selection


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    discovery_form_type = fields.Selection(
        selection='_selection_discovery_form_type',
        string='Discovery Form', tracking=True,
        help="Select which service this opportunity concerns, then use "
             "'Send Discovery Form' to email the matching client form. "
             "You can send more than one form (of the same or different type) "
             "over the life of this opportunity.")

    def _selection_discovery_form_type(self):
        return form_selection()

    discovery_form_ids = fields.One2many(
        'crm.lead.discovery.form', 'lead_id', string='Discovery Forms', copy=False)
    discovery_form_count = fields.Integer(
        string='Discovery Forms Sent', compute='_compute_discovery_form_count')

    @api.depends('discovery_form_ids')
    def _compute_discovery_form_count(self):
        for lead in self:
            lead.discovery_form_count = len(lead.discovery_form_ids)

    sale_order_id = fields.Many2one(
        'sale.order', string='Sale Order', copy=False, readonly=True,
        help="Quotation / sale order created from this pipeline.")

    stage_reason_ids = fields.One2many(
        'crm.lead.stage.reason', 'lead_id', string='Qualification Reasons', copy=False)

    # Stage flags used to show/hide the manual stage buttons in the header.
    is_stage_new = fields.Boolean(compute='_compute_stage_flags')
    is_stage_lost = fields.Boolean(compute='_compute_stage_flags')
    is_stage_qualified = fields.Boolean(compute='_compute_stage_flags')
    is_stage_not_qualified = fields.Boolean(compute='_compute_stage_flags')

    @api.depends('stage_id')
    def _compute_stage_flags(self):
        new_stage = self.env.ref('crm.stage_lead1', raise_if_not_found=False)
        qualified_stage = self.env.ref('crm.stage_lead2', raise_if_not_found=False)
        not_qualified_stage = self.env.ref('crm_extended_rk.stage_not_qualified', raise_if_not_found=False)
        lost_stage = self.env.ref('crm_extended_rk.stage_lost', raise_if_not_found=False)
        for lead in self:
            lead.is_stage_new = bool(new_stage and lead.stage_id == new_stage)
            lead.is_stage_qualified = bool(qualified_stage and lead.stage_id == qualified_stage)
            lead.is_stage_not_qualified = bool(not_qualified_stage and lead.stage_id == not_qualified_stage)
            lead.is_stage_lost = bool(lost_stage and lead.stage_id == lost_stage)

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

    @api.constrains('stage_id', 'source_id')
    def _check_source_required_after_new(self):
        new_stage = self.env.ref('crm.stage_lead1', raise_if_not_found=False)
        for lead in self:
            if new_stage and lead.stage_id != new_stage and not lead.source_id:
                raise ValidationError(_(
                    "Please set a Source (Extra Information > Marketing) "
                    "before this lead/opportunity can leave the New stage."))

    def action_move_to_qualified(self):
        """Header button shown while in the New stage."""
        self.ensure_one()
        if not self.source_id:
            return {
                'name': _("Select a Source"),
                'type': 'ir.actions.act_window',
                'res_model': 'crm.lead.set.source.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_lead_id': self.id},
            }
        self._move_stage('crm.stage_lead2')

    def action_move_to_new(self):
        """Header button shown while in the Lost stage."""
        self._move_stage('crm.stage_lead1')

    def _action_open_reason_wizard(self, title, target_stage_xmlid):
        """Popup asking why the lead is moving to target_stage_xmlid; the
        wizard logs the reason on the chatter and applies the move."""
        self.ensure_one()
        target_stage = self.env.ref(target_stage_xmlid, raise_if_not_found=False)
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead.set.reason.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_lead_id': self.id,
                'default_target_stage_id': target_stage.id if target_stage else False,
            },
        }

    def action_open_not_qualified_wizard(self):
        """Header button shown in the New / Qualified stages."""
        return self._action_open_reason_wizard(
            _("Mark as Not Qualified"), 'crm_extended_rk.stage_not_qualified')

    def action_open_qualified_wizard(self):
        """Header button shown in the Not Qualified stage."""
        return self._action_open_reason_wizard(
            _("Mark as Qualified"), 'crm.stage_lead2')

    def action_set_lost(self, **additional_values):
        # The standard "Lost" button archives the lead; in addition we drop it
        # into the dedicated "Lost" pipeline column and keep it visible there.
        res = super().action_set_lost(**additional_values)
        lost_stage = self.env.ref('crm_extended_rk.stage_lost', raise_if_not_found=False)
        if lost_stage:
            self.write({'stage_id': lost_stage.id, 'active': True})
        return res

    # ------------------------------------------------------------------
    # Discovery form: prefill helper (used by the public controller)
    # ------------------------------------------------------------------
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
    # Discovery form: send a new one / browse the ones already sent
    # ------------------------------------------------------------------
    def action_send_discovery_form(self):
        """Header button: create and send a new discovery form submission of
        whichever type is currently selected. Can be clicked repeatedly to
        send further forms (same or different type) over the opportunity's
        lifetime."""
        self.ensure_one()
        if not self.discovery_form_type:
            raise UserError(_("Please select which Discovery Form to send first."))
        if not self.email_from:
            raise UserError(_(
                "Please set the email address on this pipeline before sending the "
                "discovery form."))

        submission = self.env['crm.lead.discovery.form'].create({
            'lead_id': self.id,
            'form_type': self.discovery_form_type,
        })
        submission.action_send()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Discovery Form Sent"),
                'message': _("The %(form)s discovery form link has been sent to %(email)s.") % {
                    'form': submission.form_label, 'email': self.email_from},
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'crm.lead',
                    'res_id': self.id,
                    'views': [[False, 'form']],
                    'target': 'current',
                },
            },
        }

    def action_view_discovery_forms(self):
        """Smart button: browse every discovery form sent for this opportunity."""
        self.ensure_one()
        return {
            'name': _("Discovery Forms"),
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead.discovery.form',
            'view_mode': 'list,form',
            'domain': [('lead_id', '=', self.id)],
            'context': {'default_lead_id': self.id, 'default_form_type': self.discovery_form_type},
        }
