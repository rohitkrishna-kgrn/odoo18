# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    """Surface the per-company eInvoicing configuration in Settings.

    Every field is ``related`` to ``res.company`` so switching the company
    selector in Settings edits that company's own entity, token and webhook.
    """
    _inherit = 'res.config.settings'

    # --- AR outbound ---------------------------------------------------
    einv_enabled = fields.Boolean(related='company_id.einv_enabled', readonly=False)
    einv_api_base_url = fields.Char(related='company_id.einv_api_base_url', readonly=False)
    einv_api_token = fields.Char(related='company_id.einv_api_token', readonly=False)
    einv_token_expiry = fields.Datetime(related='company_id.einv_token_expiry', readonly=False)
    einv_token_name = fields.Char(related='company_id.einv_token_name', readonly=False)
    einv_token_prefix = fields.Char(related='company_id.einv_token_prefix', readonly=True)
    einv_erp_name = fields.Char(related='company_id.einv_erp_name', readonly=False)
    einv_entity_id = fields.Char(related='company_id.einv_entity_id', readonly=False)
    einv_location_id = fields.Char(related='company_id.einv_location_id', readonly=False)
    einv_entity_name = fields.Char(related='company_id.einv_entity_name', readonly=True)
    einv_entity_trn = fields.Char(related='company_id.einv_entity_trn', readonly=True)
    einv_location_name = fields.Char(related='company_id.einv_location_name', readonly=True)
    einv_peppol_sender_id = fields.Char(related='company_id.einv_peppol_sender_id', readonly=True)
    einv_connection_state = fields.Selection(
        related='company_id.einv_connection_state', readonly=True)
    einv_connection_message = fields.Text(
        related='company_id.einv_connection_message', readonly=True)
    einv_default_push_state = fields.Selection(
        related='company_id.einv_default_push_state', readonly=False)
    einv_auto_push = fields.Boolean(related='company_id.einv_auto_push', readonly=False)
    einv_attach_pdf = fields.Boolean(related='company_id.einv_attach_pdf', readonly=False)
    einv_timeout = fields.Integer(related='company_id.einv_timeout', readonly=False)
    einv_portal_email = fields.Char(related='company_id.einv_portal_email', readonly=False)

    # --- Seller / organisation defaults --------------------------------
    einv_seller_scheme_id = fields.Char(
        related='company_id.einv_seller_scheme_id', readonly=False)
    einv_seller_electronic_address = fields.Char(
        related='company_id.einv_seller_electronic_address', readonly=False)
    einv_legal_reg_type = fields.Selection(
        related='company_id.einv_legal_reg_type', readonly=False)
    einv_legal_reg_id = fields.Char(related='company_id.einv_legal_reg_id', readonly=False)
    einv_trade_license = fields.Char(related='company_id.einv_trade_license', readonly=False)
    einv_authority_name = fields.Char(related='company_id.einv_authority_name', readonly=False)
    einv_contact_point = fields.Char(related='company_id.einv_contact_point', readonly=False)
    einv_default_transaction_type = fields.Selection(
        related='company_id.einv_default_transaction_type', readonly=False)
    einv_default_payment_means = fields.Selection(
        related='company_id.einv_default_payment_means', readonly=False)
    einv_default_item_type = fields.Selection(
        related='company_id.einv_default_item_type', readonly=False)

    # --- AP inbound ----------------------------------------------------
    einv_ap_enabled = fields.Boolean(related='company_id.einv_ap_enabled', readonly=False)
    einv_ap_auth_type = fields.Selection(
        related='company_id.einv_ap_auth_type', readonly=False)
    einv_ap_token = fields.Char(related='company_id.einv_ap_token', readonly=False)
    einv_ap_api_key_header = fields.Char(
        related='company_id.einv_ap_api_key_header', readonly=False)
    einv_ap_username = fields.Char(related='company_id.einv_ap_username', readonly=False)
    einv_ap_password = fields.Char(related='company_id.einv_ap_password', readonly=False)
    einv_ap_webhook_url = fields.Char(related='company_id.einv_ap_webhook_url', readonly=True)
    einv_ap_journal_id = fields.Many2one(
        related='company_id.einv_ap_journal_id', readonly=False)
    einv_ap_auto_post = fields.Boolean(related='company_id.einv_ap_auto_post', readonly=False)
    einv_ap_create_partner = fields.Boolean(
        related='company_id.einv_ap_create_partner', readonly=False)
    einv_ap_product_id = fields.Many2one(
        related='company_id.einv_ap_product_id', readonly=False)
    einv_ap_account_id = fields.Many2one(
        related='company_id.einv_ap_account_id', readonly=False)
    einv_ap_tax_id = fields.Many2one(related='company_id.einv_ap_tax_id', readonly=False)
    einv_ap_store_xml = fields.Boolean(related='company_id.einv_ap_store_xml', readonly=False)
    einv_ap_last_status = fields.Selection(
        related='company_id.einv_ap_last_status', readonly=True)
    einv_ap_last_date = fields.Datetime(related='company_id.einv_ap_last_date', readonly=True)
    einv_ap_last_error = fields.Char(related='company_id.einv_ap_last_error', readonly=True)

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_einv_test_connection(self):
        """Call whoami and store which entity + location the token maps to.

        Saves the pending settings first, otherwise a token just typed into the
        form would not be the one tested.
        """
        self.ensure_one()
        self.execute()
        return self.company_id.sudo().action_einv_whoami()

    def action_einv_generate_token(self):
        """Open the wizard that issues a kgrn_out_ token from portal credentials."""
        self.ensure_one()
        self.execute()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate Outbound API Token'),
            'res_model': 'einvoice.token.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_company_id': self.company_id.id},
        }

    def action_einv_generate_ap_token(self):
        """Mint a new inbound webhook secret for this company."""
        self.ensure_one()
        self.execute()
        self.company_id.sudo().einv_generate_ap_token()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_einv_open_logs(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'einvoicing_extended_rk.action_einvoice_log')
        action['domain'] = [('company_id', '=', self.company_id.id)]
        return action
