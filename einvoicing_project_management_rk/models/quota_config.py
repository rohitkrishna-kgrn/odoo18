# -*- coding: utf-8 -*-
import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

QUOTA_PATH = "/api/v1/public/quota"
ENVIRONMENTS = [("uat", "UAT"), ("live", "LIVE")]


class EinvoicingQuotaConfig(models.Model):
    """Where the invoice quota API lives, one row per environment.

    The API is public (looked up by Peppol ID, no credentials), so only the
    base URL and a timeout are kept. The path is the same on both.
    """
    _name = "einvoicing.quota.config"
    _description = "E-Invoicing Quota API Endpoint"
    _order = "sequence, id"
    _rec_name = "name"

    name = fields.Char(required=True)
    code = fields.Selection(ENVIRONMENTS, string="Environment", required=True, readonly=True)
    sequence = fields.Integer(default=10)
    url = fields.Char(string="URL", required=True,
                      help="Base URL, e.g. https://live.kgrnaudit.com. The quota path is added to it.")
    timeout = fields.Integer(string="Timeout (seconds)", default=10, required=True)
    endpoint = fields.Char(compute="_compute_endpoint", string="Quota Endpoint")

    _sql_constraints = [
        ("code_unique", "unique(code)", "There is already an endpoint for this environment."),
        ("timeout_positive", "CHECK(timeout > 0)", "The timeout must be at least one second."),
    ]

    @api.depends("url")
    def _compute_endpoint(self):
        for rec in self:
            rec.endpoint = (rec.url or "").rstrip("/") + QUOTA_PATH if rec.url else False

    @api.model
    def _get_endpoint(self, code):
        """(endpoint, timeout) for an environment, or (False, 0) when unset."""
        rec = self.sudo().search([("code", "=", code)], limit=1)
        return (rec.endpoint, rec.timeout) if rec and rec.url else (False, 0)

    def action_test_connection(self):
        """POST an empty body: a reachable quota API answers 400 'peppolId is required'."""
        self.ensure_one()
        try:
            response = requests.post(self.endpoint, json={}, timeout=self.timeout,
                                     headers={"User-Agent": "Odoo E-Invoicing Projects"})
        except requests.RequestException as error:
            raise UserError(_("Could not reach %(url)s:\n%(error)s", url=self.endpoint, error=error))
        if response.status_code == 400:
            kind, message = "success", _("%(env)s quota API is reachable.", env=self.name)
        else:
            kind, message = "warning", _(
                "%(env)s answered HTTP %(code)s - expected 400 for an empty request. Check the URL.",
                env=self.name, code=response.status_code)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"type": kind, "message": message, "sticky": False},
        }
