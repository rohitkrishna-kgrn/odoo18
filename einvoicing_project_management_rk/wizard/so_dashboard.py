# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.tools.misc import format_date


class EinvoicingSoDashboard(models.TransientModel):
    """E-Invoicing dashboard for one SE, opened from the sale order's button.

    Entities, Listed and Pending use every Phase 1 row on the SE, the same
    figures the Pending menu shows.
    """
    _name = "einvoicing.so.dashboard"
    _description = "E-Invoicing SE Dashboard"

    sale_order_id = fields.Many2one("sale.order", required=True, readonly=True, ondelete="cascade")
    pending_count = fields.Integer(compute="_compute_dashboard")
    dashboard_html = fields.Html(compute="_compute_dashboard", sanitize=False)

    def _reopen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("E-Invoicing - %s", self.sale_order_id.name),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {"dialog_size": "extra-large"},
        }

    def _rows(self):
        return self.env["einvoicing.phase1.project"].search(
            [("sale_order_id", "=", self.sale_order_id.id)], order="s_no")

    @staticmethod
    def _split(rows, field, selection):
        total = len(rows)
        out = []
        for key, label in selection:
            count = sum(1 for r in rows if (r[field] or False) == key)
            out.append({"key": key or "none", "label": label, "count": count,
                        "pct": round(count * 100 / total) if total else 0})
        return out

    def _quota_summary(self, rows, code, label):
        Mixin = self.env["einvoicing.phase1.project"]
        states = [(row, row._quota_state(code)) for row in rows]
        ok = [st for _row, st in states if st.get("status") == "ok"]
        counts = {}
        for _row, st in states:
            counts[st.get("status")] = counts.get(st.get("status"), 0) + 1
        summary = {
            "label": label, "found": len(ok), "total": len(rows),
            "na": counts.get("na", 0), "not_found": counts.get("not_found", 0),
            "pending": counts.get("pending", 0),
            "failed": counts.get("error", 0) + counts.get("rate_limited", 0) + counts.get("invalid", 0),
            "rows": [],
        }
        if ok:
            ar = Mixin._quota_overall([Mixin._quota_block(st.get("ar") or {}) for st in ok])
            ap = Mixin._quota_overall([Mixin._quota_block(st.get("ap") or {}) for st in ok])
            summary["rows"], _overall = Mixin._quota_rows(ar, ap)
        return summary

    @staticmethod
    def _short_quota(row, code):
        state = row._quota_state(code)
        if state.get("status") != "ok":
            return {"text": "NA", "over": False}
        Mixin = row.env["einvoicing.phase1.project"]
        overall = Mixin._quota_overall([Mixin._quota_block(state.get("ar") or {}),
                                        Mixin._quota_block(state.get("ap") or {})])
        text = "{:,}".format(overall["used"]) + " / " + (
            "{:,}".format(overall["limit"]) if overall["limit"] else _("no limit"))
        return {"text": text, "over": overall["over"] > 0, "over_text": "{:,}".format(overall["over"])}

    @api.depends("sale_order_id")
    def _compute_dashboard(self):
        Project = self.env["einvoicing.phase1.project"]
        sel = Project._fields
        for wiz in self:
            so = wiz.sale_order_id
            so_sudo = so.sudo()
            rows = wiz._rows()
            listed_all = Project.sudo().search_count([("sale_order_id", "=", so.id)])
            entities = len(so_sudo.entity_ids)
            pending = max(entities - listed_all, 0)
            wiz.pending_count = pending
            unidentified = self.env["einvoicing.unidentified"].search_count(
                [("sale_order_id", "=", so.id)])
            ga_labels = dict(sel["gap_assessment"].selection)
            em_labels = dict(sel["emaratax_onboarding"].selection)
            renewals = [r.renewal_date for r in rows if r.renewal_date]
            starts = [r.subscription_start_date for r in rows if r.subscription_start_date]
            values = {
                "so": {
                    "name": so.name,
                    "customer": so_sudo.partner_id.display_name or "",
                    "salesperson": so_sudo.user_id.name or "",
                    "start": format_date(self.env, min(starts)) if starts else False,
                    "renewal": format_date(self.env, min(renewals)) if renewals else False,
                },
                "kpis": {"entities": entities, "listed": listed_all, "pending": pending,
                         "visible": len(rows), "unidentified": unidentified},
                "ga": self._split(rows, "gap_assessment", sel["gap_assessment"].selection),
                "uat": self._split(rows, "uat_onboarding", sel["uat_onboarding"].selection),
                "emaratax": self._split(rows, "emaratax_onboarding",
                                        list(sel["emaratax_onboarding"].selection) + [(False, _("Not set"))]),
                "live": self._split(rows, "live_middleware", sel["live_middleware"].selection),
                "quotas": [wiz._quota_summary(rows, "live", "LIVE"), wiz._quota_summary(rows, "uat", "UAT")],
                "trns": [{
                    "s_no": r.s_no, "name": r.name, "peppol": r.peppol_id or "NA",
                    "ga": ga_labels.get(r.gap_assessment, ""), "ga_key": r.gap_assessment,
                    "uat": r.uat_onboarding == "yes",
                    "emaratax": em_labels.get(r.emaratax_onboarding) or _("Not set"),
                    "emaratax_key": r.emaratax_onboarding or "none",
                    "live": r.live_middleware == "yes",
                    "renewal": format_date(self.env, r.renewal_date) if r.renewal_date else "",
                    "q_live": self._short_quota(r, "live"), "q_uat": self._short_quota(r, "uat"),
                } for r in rows],
            }
            wiz.dashboard_html = self.env["ir.qweb"]._render(
                "einvoicing_project_management_rk.so_dashboard", values)

    # ------------------------------------------------------------- buttons
    def action_refresh_quotas(self):
        self.ensure_one()
        self._rows()._fetch_quotas()
        return self._reopen()

    def action_open_trns(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Phase 1 Projects - %s", self.sale_order_id.name),
            "res_model": "einvoicing.phase1.project",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("sale_order_id", "=", self.sale_order_id.id)],
            "context": {"default_sale_order_id": self.sale_order_id.id},
            "target": "current",
        }

    def action_add_trn(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Phase 1 Project"),
            "res_model": "einvoicing.phase1.project",
            "views": [[False, "form"]],
            "context": {"default_sale_order_id": self.sale_order_id.id},
            "target": "current",
        }
