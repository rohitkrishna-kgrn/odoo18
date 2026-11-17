# -*- coding: utf-8 -*-
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests

from odoo import _, api, fields, models
from odoo.tools.misc import format_datetime

_logger = logging.getLogger(__name__)

YES_NO = [("yes", "Yes"), ("no", "No")]


class EinvoicingProjectMixin(models.AbstractModel):
    """The columns Phase 1 Projects and Unidentified share.

    Each concrete model names its own S.No sequence in ``_sequence_code``.
    Phase 1 makes the SE required; on Unidentified it is optional.
    """
    _name = "einvoicing.project.mixin"
    _description = "E-Invoicing Project Columns"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _sequence_code = False

    s_no = fields.Integer(
        string="S.No", readonly=True, copy=False, tracking=True,
        help="Assigned automatically, in the order rows are created.")
    name = fields.Char(string="Emaratax Legal Name", required=True, tracking=True)
    peppol_id = fields.Char(string="Peppol ID", tracking=True)
    sale_order_id = fields.Many2one(
        "sale.order", string="SE Number", index=True,
        tracking=True, ondelete="restrict",
        domain="[('approval_state', '=', 'approved'), ('einvoicing_service', '=', True), ('state', '!=', 'cancel')]")
    partner_id = fields.Many2one(
        related="sale_order_id.partner_id", string="Customer", store=True)
    company_id = fields.Many2one(
        related="sale_order_id.company_id", string="Company", store=True)
    user_id = fields.Many2one(
        related="sale_order_id.user_id", string="Salesperson", store=True)
    # Filled from the SE's order lines when the SE is picked, then editable per
    # row. Renewal = the day after the last engagement end, the same rule the
    # SE billing view used.
    subscription_start_date = fields.Date(
        string="Subscription Start Date", compute="_compute_subscription_start_date",
        store=True, readonly=False, tracking=True,
        help="Taken from the earliest Engagement Start on the SE's order lines "
             "when the SE is chosen. Can be changed per row.")
    renewal_date = fields.Date(
        string="Renewal Date", compute="_compute_renewal_date",
        store=True, readonly=False, tracking=True,
        help="The day after the latest Engagement End on the SE's order lines, "
             "filled when the SE is chosen. Can be changed per row.")
    gap_assessment = fields.Selection([
        ("new", "New"),
        ("in_progress", "In Progress"),
        ("on_hold", "On Hold"),
        ("done", "Done"),
        ("cancelled", "Cancelled"),
    ], string="Gap Assessment", default="new", required=True, tracking=True)
    uat_onboarding = fields.Selection(
        YES_NO, string="UAT Onboarding", default="no", required=True, tracking=True)
    emaratax_onboarding = fields.Selection([
        ("active", "Active"),
        ("suspended", "Suspended"),
        ("delinked", "Delinked"),
    ], string="Emaratax Onboarding", tracking=True)
    live_middleware = fields.Selection(
        YES_NO, string="LIVE Middleware", default="no", required=True, tracking=True)
    remarks = fields.Char(string="Remarks - Emaratax", tracking=True)

    # Invoice quota from the KGRN platform, looked up by Peppol ID. The raw
    # result of the last call is kept per environment. It is not tracked, so a
    # refresh does not flood the chatter.
    quota_uat = fields.Json(string="UAT Quota", readonly=True, copy=False)
    quota_live = fields.Json(string="LIVE Quota", readonly=True, copy=False)
    quota_fetched_at = fields.Datetime(string="Quota Checked", readonly=True, copy=False)
    quota_uat_html = fields.Html(string="UAT", compute="_compute_quota_html", sanitize=False)
    quota_live_html = fields.Html(string="LIVE", compute="_compute_quota_html", sanitize=False)

    # Two computes, not one shared: on create Odoo protects every field of a
    # shared compute as soon as ONE of them is in vals, so typing only the
    # Renewal Date would leave the start date blank.
    def _se_lines(self):
        # sudo: a User may not be allowed to read another salesperson's order
        # lines, but the SE itself is already chosen on the row.
        return self.sale_order_id.sudo().order_line.filtered(lambda l: not l.display_type)

    @api.depends("sale_order_id")
    def _compute_subscription_start_date(self):
        for rec in self:
            starts = [d for d in rec._se_lines().mapped("engagement_start") if d]
            rec.subscription_start_date = min(starts) if starts else False

    @api.depends("sale_order_id")
    def _compute_renewal_date(self):
        for rec in self:
            ends = [d for d in rec._se_lines().mapped("engagement_end") if d]
            rec.renewal_date = (max(ends) + timedelta(days=1)) if ends else False

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"].sudo()
        for vals in vals_list:
            if not vals.get("s_no"):
                vals["s_no"] = int(sequence.next_by_code(self._sequence_code))
        records = super().create(vals_list)
        records.filtered("peppol_id")._quota_fetch_after_change()
        return records

    def write(self, vals):
        result = super().write(vals)
        if "peppol_id" in vals:
            self._quota_fetch_after_change()
        return result

    # ------------------------------------------------------------------
    # Quota API
    # ------------------------------------------------------------------
    # Fetch at once only for a handful of rows (a form or list save). A bulk
    # import is left to the cron, so it cannot exhaust the API's 60
    # requests/minute limit in a single save.
    _QUOTA_INLINE_MAX = 5

    def _quota_fetch_after_change(self):
        if self and len(self) <= self._QUOTA_INLINE_MAX:
            self._fetch_quotas()

    @staticmethod
    def _quota_call(endpoint, timeout, peppol_id):
        """One HTTP call, no ORM access, so it can run in a worker thread."""
        stamp = fields.Datetime.to_string(fields.Datetime.now())
        base = {"peppol_id": peppol_id, "fetched_at": stamp}
        if not peppol_id:
            return dict(base, status="na")
        if not endpoint:
            # plain text: this runs in a worker thread with no env to translate with
            return dict(base, status="error", error="No URL configured for this environment.")
        try:
            response = requests.post(
                endpoint, json={"peppolId": peppol_id}, timeout=timeout,
                headers={"User-Agent": "Odoo E-Invoicing Projects"})
        except requests.RequestException as error:
            return dict(base, status="error", error=str(error)[:300])
        try:
            body = response.json()
        except ValueError:
            body = {}
        code = response.status_code
        if code == 200 and body.get("success"):
            return dict(base, status="ok", se_number=body.get("seNumber") or "",
                        ar=body.get("ar") or {}, ap=body.get("ap") or {}, as_of=body.get("asOf"))
        status = {404: "not_found", 400: "invalid", 429: "rate_limited"}.get(code, "error")
        return dict(base, status=status, http=code, error=body.get("error") or response.reason)

    def _fetch_quotas(self):
        """Look every row up on UAT and LIVE in parallel, then store the results."""
        Config = self.env["einvoicing.quota.config"]
        targets = {code: Config._get_endpoint(code) for code in ("uat", "live")}
        jobs = [(rec, code, (rec.peppol_id or "").strip()) for rec in self for code in targets]
        if not jobs:
            return {}
        with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
            results = list(pool.map(
                lambda job: self._quota_call(targets[job[1]][0], targets[job[1]][1], job[2]), jobs))
        now = fields.Datetime.now()
        statuses = {}
        for (rec, code, _peppol), result in zip(jobs, results):
            # sudo: the stored result is a cache of public data, and a cron or a
            # User refreshing a shared SE dashboard must be able to write it.
            rec.sudo().write({"quota_" + code: result, "quota_fetched_at": now})
            statuses.setdefault(result["status"], 0)
            statuses[result["status"]] += 1
        return statuses

    def action_fetch_quota(self):
        statuses = self._fetch_quotas()
        failed = sum(n for st, n in statuses.items() if st in ("error", "rate_limited"))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "warning" if failed else "success",
                "message": _("Quota checked on UAT and LIVE.") if not failed else
                _("Quota checked, but %s lookups failed - see the sections for details.", failed),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    @api.model
    def _cron_refresh_quotas(self, batch=12):
        """Refresh the rows checked longest ago. 12 rows = 24 calls per run,
        well inside the API's 60 requests/minute."""
        records = self.sudo().search(
            [("peppol_id", "!=", False)], order="quota_fetched_at asc nulls first, id", limit=batch)
        statuses = records._fetch_quotas()
        if statuses.get("rate_limited"):
            _logger.warning("Quota API rate limit hit while refreshing %s", self._name)

    # ------------------------------------------------------------------
    # Presentation (shared with the sale order dashboard)
    # ------------------------------------------------------------------
    _QUOTA_STATUS = {
        "ok": ("Verified", "fa-check-circle", "good"),
        "na": ("N/A - no Peppol ID", "fa-minus-circle", "none"),
        "pending": ("Not checked yet", "fa-clock-o", "none"),
        "not_found": ("Not found on the platform", "fa-question-circle", "warning"),
        "invalid": ("Peppol ID not accepted", "fa-exclamation-circle", "critical"),
        "rate_limited": ("Rate limited - try again shortly", "fa-hourglass-half", "warning"),
        "error": ("Could not reach the platform", "fa-exclamation-triangle", "critical"),
    }

    @staticmethod
    def _se_digits(value):
        digits = re.sub(r"\D", "", value or "")
        return int(digits) if digits else None

    def _quota_state(self, code):
        """The stored result for one environment, or a placeholder state."""
        self.ensure_one()
        peppol = (self.peppol_id or "").strip()
        data = self["quota_" + code] or {}
        if not peppol:
            return {"status": "na"}
        if not data or data.get("peppol_id") != peppol:
            return {"status": "pending"}  # never checked, or the Peppol ID changed since
        return data

    @staticmethod
    def _quota_block(block):
        """Normalise an ar/ap block: limit 0 means 'not set', so remaining is None."""
        used = int(block.get("used") or 0)
        limit = int(block.get("limit") or 0)
        remaining = block.get("remaining")
        return {
            "used": used,
            "limit": limit or None,
            "remaining": None if not limit else int(remaining if remaining is not None else max(limit - used, 0)),
            "over": int(block.get("over") or 0),
        }

    @classmethod
    def _quota_overall(cls, blocks):
        """Add blocks together. The overall limit is known only when every side has one."""
        limits = [b["limit"] for b in blocks]
        known = all(limits) and bool(limits)
        return {
            "used": sum(b["used"] for b in blocks),
            "limit": sum(limits) if known else None,
            "remaining": sum(b["remaining"] for b in blocks) if known else None,
            "over": sum(b["over"] for b in blocks),
        }

    def _fmt_count(self, value):
        return "{:,}".format(value) if value is not None else None

    def _quota_rows(self, ar, ap):
        overall = self._quota_overall([ar, ap])
        rows = []
        for label, block, strong in ((_("Issued (AR)"), ar, False), (_("Received (AP)"), ap, False),
                                     (_("Overall"), overall, True)):
            pct = round(block["used"] * 100 / block["limit"]) if block["limit"] else None
            rows.append({
                "label": label, "strong": strong,
                "used": self._fmt_count(block["used"]),
                "limit": self._fmt_count(block["limit"]) if block["limit"] else _("Not set"),
                "remaining": self._fmt_count(block["remaining"]) if block["remaining"] is not None else "-",
                "over": self._fmt_count(block["over"]),
                "is_over": block["over"] > 0,
                "pct": pct, "bar": min(pct, 100) if pct is not None else 0,
            })
        return rows, overall

    def _quota_card(self, code, label):
        self.ensure_one()
        state = self._quota_state(code)
        status = state.get("status", "error")
        text, icon, tone = self._QUOTA_STATUS.get(status, self._QUOTA_STATUS["error"])
        card = {
            "label": label, "status": status, "status_text": _(text), "icon": icon, "tone": tone,
            "peppol": (self.peppol_id or "").strip() or "NA",
            "error": state.get("error") if status not in ("ok", "na", "pending") else False,
            "rows": [], "se_api": None, "se_check": None,
            "as_of": False, "checked": False,
        }
        if state.get("fetched_at"):
            card["checked"] = format_datetime(self.env, fields.Datetime.from_string(state["fetched_at"]))
        if status == "ok":
            card["rows"], _overall = self._quota_rows(self._quota_block(state.get("ar") or {}),
                                                      self._quota_block(state.get("ap") or {}))
            if state.get("as_of"):
                try:
                    as_of = datetime.fromisoformat(state["as_of"].replace("Z", "+00:00")).replace(tzinfo=None)
                    card["as_of"] = format_datetime(self.env, as_of)
                except ValueError:
                    card["as_of"] = state["as_of"]
            api_se = state.get("se_number") or ""
            card["se_api"] = api_se or _("Not recorded")
            ours = self.sale_order_id.name
            if not api_se:
                card["se_check"] = "unknown"
            elif ours:
                card["se_check"] = "match" if self._se_digits(api_se) == self._se_digits(ours) else "differs"
            card["se_ours"] = ours
        return card

    @api.depends("quota_uat", "quota_live", "peppol_id", "sale_order_id")
    def _compute_quota_html(self):
        QWeb = self.env["ir.qweb"]
        for rec in self:
            for code, label in (("uat", "UAT"), ("live", "LIVE")):
                rec["quota_%s_html" % code] = QWeb._render(
                    "einvoicing_project_management_rk.quota_card", {"card": rec._quota_card(code, label)})
