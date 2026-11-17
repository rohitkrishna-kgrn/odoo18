# -*- coding: utf-8 -*-
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests

from odoo import _, api, fields, models
from odoo.tools import split_every
from odoo.tools.misc import format_amount, format_date, format_datetime

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
        ("not_required", "Not Required"),
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
    # SE billing, read live from the sale order and its invoices (no API).
    payment_html = fields.Html(string="Payment", compute="_compute_payment_html", sanitize=False)

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
        for (rec, code, peppol), result in zip(jobs, results):
            previous = rec["quota_" + code] or {}
            if (result["status"] in ("error", "rate_limited") and previous.get("status") == "ok"
                    and previous.get("peppol_id") == peppol):
                # A failed refresh must not wipe good figures: keep them, note the failure.
                result = dict(previous, refresh_error=result.get("error") or result["status"],
                              refresh_failed_at=result["fetched_at"])
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

    # Opening the app's pages refreshes quotas older than this. The page shows
    # at once and the figures update when the fetch returns (see
    # static/src/quota/quota_autorefresh.js). The cap keeps one page load
    # inside the API's 60 requests/minute: 25 rows = 50 calls.
    _QUOTA_STALE_MINUTES = 10  # matches the 10-minute cron; page loads only fill gaps
    _QUOTA_REFRESH_CAP = 25

    @api.model
    def refresh_stale_quotas(self, ids=None, force=False):
        """Re-check rows whose quota is older than _QUOTA_STALE_MINUTES.

        Rows checked for a different Peppol ID than they hold now count as
        stale too. ``ids`` limits the check to those rows (a form); ``force``
        ignores the age (the dashboard's Refresh button). Returns how many rows
        were re-checked, so the page knows whether to reload.
        """
        domain = [("peppol_id", "!=", False)]
        if ids:
            domain.append(("id", "in", list(ids)))
        records = self.search(domain, order="quota_fetched_at asc nulls first, id")
        if not force:
            limit = fields.Datetime.now() - timedelta(minutes=self._QUOTA_STALE_MINUTES)
            records = records.filtered(
                lambda r: not r.quota_fetched_at or r.quota_fetched_at < limit
                or any(r._quota_state(code).get("status") == "pending" for code in ("uat", "live")))
        records = records[:self._QUOTA_REFRESH_CAP]
        if records:
            records._fetch_quotas()
        return len(records)

    @api.model
    def _refresh_quotas_on_module_load(self):
        """Run from a data file on every install/upgrade: re-check every row,
        within the same per-call cap (the cron picks up anything beyond it)."""
        try:
            self.sudo().refresh_stale_quotas(force=True)
        except Exception:  # an unreachable API must never block an upgrade
            _logger.exception("Quota refresh on module load failed for %s", self._name)

    # The 10-minute cron: fetch and store UAT + LIVE for every row of both
    # lists. 25 rows (50 calls) per batch, then a minute's pause, keeps it
    # inside 60 requests/minute; each batch is committed as it lands. A run
    # stops after 8 minutes so it never overlaps the next one, and the rows it
    # did not reach are the oldest next time.
    _QUOTA_CRON_BATCH = 25
    _QUOTA_CRON_PAUSE = 61
    _QUOTA_CRON_BUDGET = 8 * 60

    @api.model
    def _cron_refresh_all_quotas(self):
        deadline = time.monotonic() + self._QUOTA_CRON_BUDGET
        fresh = fields.Datetime.now() - timedelta(minutes=9)  # already done this cycle
        first = True
        for model in ("einvoicing.phase1.project", "einvoicing.unidentified"):
            Model = self.env[model].sudo()
            records = Model.search(
                [("peppol_id", "!=", False), "|", ("quota_fetched_at", "=", False),
                 ("quota_fetched_at", "<", fresh)],
                order="quota_fetched_at asc nulls first, id")
            for batch in split_every(self._QUOTA_CRON_BATCH, records.ids):
                if not first:
                    if time.monotonic() + self._QUOTA_CRON_PAUSE > deadline:
                        _logger.info("Quota cron: time budget used, the rest waits for the next run")
                        return
                    time.sleep(self._QUOTA_CRON_PAUSE)
                first = False
                statuses = Model.browse(batch)._fetch_quotas()
                self.env.cr.commit()
                if statuses.get("rate_limited"):
                    _logger.warning("Quota cron: rate limited, stopping this run")
                    return

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
            "as_of": False, "checked": False, "refresh_error": False,
        }
        if status == "ok" and state.get("refresh_error"):
            failed_at = format_datetime(self.env, fields.Datetime.from_string(state["refresh_failed_at"]))
            card["refresh_error"] = _("Last refresh failed at %(when)s (%(error)s) - showing the previous figures.",
                                      when=failed_at, error=state["refresh_error"])
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

    # ------------------------------------------------------------------
    # Payment: the SE's value against its invoices
    # ------------------------------------------------------------------
    @api.model
    def _se_billing(self, orders):
        """Per sale order: value, posted invoices, paid, pending, not invoiced.

        Invoices belong to an SE through the sales-line link (sale_line_ids)
        or, when installed, account.move.sale_order_line_id. The two are joined
        and de-duplicated. Only posted customer invoices and credit notes count,
        signed so a credit note reduces the totals. Paid = posted - amount
        still due (an "in payment" invoice counts as paid). Pending = what is
        still due on posted invoices. Not invoiced = value - posted, never
        below zero.

        sudo: the figures are summaries for whoever can open the row; several
        roles (e.g. project managers) cannot read account.move themselves.
        """
        orders = orders.sudo()
        Move = self.env["account.move"].sudo()
        moves = {order.id: order.invoice_ids for order in orders}
        if "sale_order_line_id" in Move._fields and orders:
            for move in Move.search([("sale_order_line_id.order_id", "in", orders.ids)]):
                order_id = move.sale_order_line_id.order_id.id
                moves[order_id] = moves.get(order_id, Move) | move
        result = {}
        for order in orders:
            posted_moves = moves.get(order.id, Move).filtered(
                lambda m: m.move_type in ("out_invoice", "out_refund") and m.state == "posted")
            posted = sum(posted_moves.mapped("amount_total_signed"))
            pending = sum(posted_moves.mapped("amount_residual_signed"))
            total = order.amount_total
            result[order.id] = {
                "order": order,
                "currency": order.currency_id or self.env.company.currency_id,
                "total": total, "posted": posted, "paid": posted - pending,
                "pending": pending, "to_invoice": max(total - posted, 0.0),
                "moves": posted_moves.sorted(lambda m: (m.invoice_date or m.date, m.id)),
            }
        return result

    def _payment_card(self):
        self.ensure_one()
        order = self.sale_order_id
        if not order:
            return {"state": "na"}
        fig = self._se_billing(order)[order.id]
        cur = fig["currency"]
        money = lambda v: format_amount(self.env, v, cur)
        pct = lambda part: round(part * 100 / fig["total"]) if fig["total"] else 0
        payment_labels = dict(self.env["account.move"]._fields["payment_state"].selection)
        return {
            "state": "ok",
            "se": order.name,
            "customer": order.sudo().partner_id.display_name or "",
            "total": money(fig["total"]), "posted": money(fig["posted"]),
            "paid": money(fig["paid"]), "pending": money(fig["pending"]),
            "to_invoice": money(fig["to_invoice"]),
            "has_pending": fig["pending"] > 0.005,
            "pct_paid": min(pct(fig["paid"]), 100),
            "pct_pending": min(pct(fig["pending"]), 100),
            "pct_posted": pct(fig["posted"]),
            "invoices": [{
                "name": move.name,
                "date": format_date(self.env, move.invoice_date or move.date),
                "kind": _("Credit Note") if move.move_type == "out_refund" else _("Invoice"),
                "amount": money(move.amount_total_signed),
                "due": money(move.amount_residual_signed),
                "status": payment_labels.get(move.payment_state, move.payment_state or ""),
                "paid": move.payment_state in ("paid", "in_payment", "reversed"),
            } for move in fig["moves"]],
        }

    @api.depends("sale_order_id")
    def _compute_payment_html(self):
        QWeb = self.env["ir.qweb"]
        for rec in self:
            rec.payment_html = QWeb._render(
                "einvoicing_project_management_rk.payment_card", {"card": rec._payment_card()})
