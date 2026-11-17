# -*- coding: utf-8 -*-
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

# Columns copied from an Unidentified row when it is added to Phase 1.
PREFILL_FIELDS = (
    "name", "peppol_id", "sale_order_id", "subscription_start_date",
    "renewal_date", "gap_assessment", "uat_onboarding",
    "emaratax_onboarding", "live_middleware", "remarks",
)


class EinvoicingPhase1Project(models.Model):
    _name = "einvoicing.phase1.project"
    _description = "E-Invoicing Phase 1 Project"
    _inherit = ["einvoicing.project.mixin"]
    _order = "s_no, id"
    _rec_name = "name"
    _sequence_code = "einvoicing.phase1.project"

    sale_order_id = fields.Many2one(required=True)

    # ------------------------------------------------------------------
    # Add from Unidentified
    # ------------------------------------------------------------------
    # The Unidentified row's Add button opens a new Phase 1 form with
    # context key `epm_from_unidentified_id`. default_get pre-fills the form
    # from that row, and create() archives the row once the Phase 1 row is
    # saved. A single custom key is used instead of default_* keys, because
    # default_* keys leak into every other model created in the same call
    # (chatter messages included).
    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        source = self._unidentified_source()
        if source:
            for fname in PREFILL_FIELDS:
                if fname not in fields_list:
                    continue
                value = source[fname]
                if not value:
                    continue  # leave the SE-driven dates to their compute
                values[fname] = value.id if fname == "sale_order_id" else value
        return values

    def _unidentified_source(self):
        source_id = self.env.context.get("epm_from_unidentified_id")
        if not source_id:
            return self.env["einvoicing.unidentified"]
        source = self.env["einvoicing.unidentified"].browse(source_id).exists()
        return source.filtered("active")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        source = self._unidentified_source()
        if source and len(records) == 1:
            # No sudo: a User can only move a row the record rules let them write.
            source.write({"active": False, "phase1_project_id": records.id})
            source.message_post(body=_(
                "Added to Phase 1 Projects as S.No %(s_no)s (%(name)s).",
                s_no=records.s_no, name=records.name))
            records.message_post(body=_(
                "Added from Unidentified (S.No %(s_no)s).", s_no=source.s_no))
        return records

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, salesperson_id=False):
        """Everything the Dashboard menu shows, in one call.

        Runs as the current user, so the record rules apply: a User's figures
        cover only the rows they created, an Administrator's cover every row.
        Pending is a list of SEs and counts, not anyone's rows, and is shared.
        Every clickable figure carries the domain that opens its rows.
        """
        today = fields.Date.context_today(self)
        base = [("user_id", "=", salesperson_id)] if salesperson_id else []
        rows = self.search_read(base, [
            "s_no", "name", "sale_order_id", "partner_id", "user_id",
            "gap_assessment", "uat_onboarding", "emaratax_onboarding",
            "live_middleware", "renewal_date",
        ], order="s_no")
        total = len(rows)

        def count(field, value):
            return sum(1 for r in rows if r[field] == value)

        def dom(*extra):
            return base + list(extra)

        sel = self._fields
        ga = [{
            "key": key, "label": label, "count": count("gap_assessment", key),
            "domain": dom(("gap_assessment", "=", key)),
        } for key, label in sel["gap_assessment"].selection]

        emaratax = [{
            "key": key, "label": label, "count": count("emaratax_onboarding", key),
            "domain": dom(("emaratax_onboarding", "=", key)),
        } for key, label in sel["emaratax_onboarding"].selection]
        emaratax.append({
            "key": "none", "label": _("Not set"), "count": count("emaratax_onboarding", False),
            "domain": dom(("emaratax_onboarding", "=", False)),
        })

        progress = [
            {"key": "listed", "label": _("Listed TRNs"), "count": total, "domain": dom()},
            {"key": "ga_done", "label": _("Gap Assessment Done"),
             "count": count("gap_assessment", "done"), "domain": dom(("gap_assessment", "=", "done"))},
            {"key": "uat", "label": _("UAT Onboarded"),
             "count": count("uat_onboarding", "yes"), "domain": dom(("uat_onboarding", "=", "yes"))},
            {"key": "emaratax", "label": _("Emaratax Active"),
             "count": count("emaratax_onboarding", "active"), "domain": dom(("emaratax_onboarding", "=", "active"))},
            {"key": "live", "label": _("LIVE Middleware"),
             "count": count("live_middleware", "yes"), "domain": dom(("live_middleware", "=", "yes"))},
        ]

        # Renewals: twelve calendar months from this one, plus what is overdue.
        month_start = today.replace(day=1)
        renewal_months = []
        for i in range(12):
            start = month_start + relativedelta(months=i)
            end = start + relativedelta(months=1, days=-1)
            renewal_months.append({
                "label": start.strftime("%B %Y"),
                "short": start.strftime("%b %y"),
                "count": sum(1 for r in rows if r["renewal_date"] and start <= r["renewal_date"] <= end),
                "domain": dom(("renewal_date", ">=", fields.Date.to_string(start)),
                              ("renewal_date", "<=", fields.Date.to_string(end))),
            })
        horizon = today + timedelta(days=60)
        due_30 = today + timedelta(days=30)
        upcoming = sorted(
            (r for r in rows if r["renewal_date"] and r["renewal_date"] <= horizon),
            key=lambda r: r["renewal_date"])
        renewals = [{
            "id": r["id"], "s_no": r["s_no"], "name": r["name"],
            "se": r["sale_order_id"] and r["sale_order_id"][1] or "",
            "customer": r["partner_id"] and r["partner_id"][1] or "",
            "date": fields.Date.to_string(r["renewal_date"]),
            "days": (r["renewal_date"] - today).days,
        } for r in upcoming[:12]]

        # Pending (shared, see the docstring).
        Pending = self.env["einvoicing.phase1.pending"]
        pbase = [("user_id", "=", salesperson_id)] if salesperson_id else []
        pending_rows = Pending.search_read(pbase, [
            "sale_order_id", "partner_id", "user_id",
            "total_entities", "listed_count", "pending_count",
        ], order="pending_count desc, sale_order_id desc")
        pending = [{
            "id": p["id"],
            "se": p["sale_order_id"] and p["sale_order_id"][1] or "",
            "customer": p["partner_id"] and p["partner_id"][1] or "",
            "salesperson": p["user_id"] and p["user_id"][1] or "",
            "total": p["total_entities"], "listed": p["listed_count"],
            "pending": p["pending_count"],
        } for p in pending_rows]

        # By salesperson: the TRNs listed against the entities still pending.
        people = {}
        for r in rows:
            key = r["user_id"] and r["user_id"][0] or 0
            name = r["user_id"] and r["user_id"][1] or _("No salesperson")
            people.setdefault(key, {"id": key, "name": name, "listed": 0, "pending": 0})["listed"] += 1
        for p in pending_rows:
            key = p["user_id"] and p["user_id"][0] or 0
            name = p["user_id"] and p["user_id"][1] or _("No salesperson")
            people.setdefault(key, {"id": key, "name": name, "listed": 0, "pending": 0})["pending"] += p["pending_count"]
        for person in people.values():
            person["domain"] = [("user_id", "=", person["id"] or False)]
        salespeople = sorted(people.values(), key=lambda p: (-(p["listed"] + p["pending"]), p["name"]))

        # Filter options ignore the current filter, so it can be switched back.
        options = {}
        for r in (rows if not salesperson_id else self.search_read([], ["user_id"])):
            if r["user_id"]:
                options[r["user_id"][0]] = r["user_id"][1]
        for p in (pending_rows if not salesperson_id else Pending.search_read([], ["user_id"])):
            if p["user_id"]:
                options[p["user_id"][0]] = p["user_id"][1]

        return {
            "today": fields.Date.to_string(today),
            "is_manager": self.env.user.has_group(
                "einvoicing_project_management_rk.group_einvoicing_pm_manager"),
            "salesperson_options": sorted(
                ({"id": k, "name": v} for k, v in options.items()), key=lambda o: o["name"]),
            "kpis": {
                "total": total,
                "ga_done": count("gap_assessment", "done"),
                "uat": count("uat_onboarding", "yes"),
                "emaratax_active": count("emaratax_onboarding", "active"),
                "live": count("live_middleware", "yes"),
                "pending_entities": sum(p["pending"] for p in pending),
                "pending_ses": len(pending),
                "renew_due": sum(1 for r in rows if r["renewal_date"] and today <= r["renewal_date"] <= due_30),
                "renew_overdue": sum(1 for r in rows if r["renewal_date"] and r["renewal_date"] < today),
            },
            "domains": {
                "renew_due": dom(("renewal_date", ">=", fields.Date.to_string(today)),
                                 ("renewal_date", "<=", fields.Date.to_string(due_30))),
                "renew_overdue": dom(("renewal_date", "<", fields.Date.to_string(today))),
                "pending": pbase,
            },
            "progress": progress,
            "ga": ga,
            "emaratax": emaratax,
            "uat": {"yes": count("uat_onboarding", "yes"), "no": count("uat_onboarding", "no")},
            "live": {"yes": count("live_middleware", "yes"), "no": count("live_middleware", "no")},
            "renewal_months": renewal_months,
            "renewals": renewals,
            "pending": pending[:10],
            "pending_more": max(len(pending) - 10, 0),
            "salespeople": salespeople,
        }
