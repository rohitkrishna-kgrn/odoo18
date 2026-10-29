# CRM Manager Access (`crm_manager_gk`)

A user set to **Sales: Manager** can also see the CRM and Services records of
everyone below them in the Employee > Manager hierarchy, at any depth, on top of
their own documents. On those records the
Manager can **view and edit** leads, quotations and service engagements (including
adding and removing order lines). They cannot create records on someone else's
behalf or delete them, and approval rights do not change.

## Turning it on for a user

Settings > Users > (user) > Access Rights > Sales > **Manager**.

The Sales dropdown now has four levels:

    User: Own Documents Only  >  Manager  >  User: All Documents  >  Administrator

Odoo only draws a category as a dropdown when its groups form one implication
chain, so Manager implies Own Documents, and **All Documents implies Manager**.
All Documents / Administrator users therefore also hold Manager. That adds
nothing for them, because they already see and edit every lead and order, and
the Services list filter skips them. To take Manager away, pick
*User: Own Documents Only* again.

**Prerequisite**

* Every report has an employee record that is linked to their user and has
  **Manager** set. Anyone without a linked user, or without a Manager, is outside
  every hierarchy.

## How the hierarchy is resolved

The module reuses `res.users.gk_manager_chain_ids` from `project_assigned_gk`.
It is a stored list of every user above a user in the Employee > Manager chain.
`project_assigned_gk` already uses it for the Project/Timesheet team-manager rules.

* It is computed from `user.employee_ids.parent_id.user_id`. It recomputes
  through the ORM whenever an employee's Manager, linked user or active flag
  changes, and the change cascades down every level below.
* It stops at loops: `current not in chain`.
* Each rule reads `('user_id.gk_manager_chain_ids', 'in', [user.id])`, meaning
  "the owner reports to me, directly or indirectly". The only value in the
  domain is `user.id`, so the per-user rule cache never holds a list of reports
  that could go stale. New joiners, transfers and new sub-teams take effect on
  the next request.
* Removing the group clears the rule cache (core behaviour on any group change).
* Archived logins of **active** employees still count as part of the hierarchy,
  so a manager keeps seeing the orders of a team member whose login was
  archived.

`hr_employee.py` adds the cycle check that core `hr` lacks: saving a Manager that
would make someone report to themselves (A → B → A, or A → A) is rejected. Only
employees that are themselves part of a loop are checked.

## Covered models

| App | Model | Owner field | What the Manager gains |
|---|---|---|---|
| CRM | `crm.lead` (leads, pipeline, the eInvoicing / Other Services dashboards) | `user_id` | read, edit |
| CRM | `crm.activity.report` (Reporting > Activities) | `user_id` | read |
| Services | `sale.order` (Proposal, Service Engagement, To Invoice, My Quotations) | `user_id` | read, edit, plus the list filter below |
| Services | `sale.order.line` (lines on the order form) | `salesman_id` | read, edit, add, remove (part of editing a quotation) |
| Services | `sale.report` (Reporting) | `user_id` | read |

**The Services list filter.** Every internal user can already read every
`sale.order` (`refund_management_rk`). On the Services menus, "Own Documents
Only" is applied by `crm_extended_rk`'s `sale.order._search` whenever the action
context has `own_created_quotations_only`.

`models/sale_order.py` intercepts that path for Managers who are Own-Documents
salespeople. It applies "own **or** my hierarchy" and turns the context key off,
so `crm_extended_rk` does not narrow the list back down.

**Not covered, on purpose:**

* invoices (`account.invoice.report`)
* projects and tasks (already handled by `project_assigned_gk`)
* Mail Leads
* Lead Journey (Own-Documents users already see every journey row)
* Sales Performance (administrators only)
* the CRM dashboard: its SQL is scoped to the logged-in user

## Install / upgrade

```
/opt/odoo18/venv/bin/python3 /opt/odoo18/odoo/odoo-bin -c /etc/odoo18.conf -d live \
    -u crm_manager_gk --stop-after-init --workers=0 --http-port=8199 --gevent-port=8299
```

After **editing** a `.py` file of an installed module, restart `odoo18` once the
upgrade has finished. A first install needs no restart.

Tests: add `--test-enable --test-tags /crm_manager_gk` (18 tests; the transaction
is rolled back). User-facing documents (technical, test, user manual) are built
from `/root/kgrn_docs/crm_manager/` with `python3 build.py`.

## Known limitations

* Proposal and My Quotations open with the default "My Quotations" filter, and
  CRM > My Pipeline with "My Pipeline". A Manager removes that filter to see the
  team's records.
* Deleting a report's lead or order is still refused, and so is creating a lead
  directly in a report's name. Create it in your own name and change the
  Salesperson: reassigning is an edit. Reassigning to someone outside the
  hierarchy also works, after which the Manager loses access to the record.
* Creating quotations is not governed by this module. `sale_renewal_rk` only lets
  **Sales Team** members create quotations at all, and that flag already lets them
  work on every quotation, including "New Quotation" on a report's opportunity.
* Outside the Services menus (a direct link, a related-record button) every
  internal user can already read any sale order because of `refund_management_rk`.
  This module does not change that.
* The two reports (Activities, Services > Reporting) are read-only by nature.
* Business guards still apply on top: approval states, the AML gate,
  locked confirmed orders and similar checks behave exactly as for the owner.
* If an employee has active records in two companies, only the first employee's
  Manager is used (same rule as `project_assigned_gk`).
