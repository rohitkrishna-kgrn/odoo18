# om_hr_payroll_extended_gk — Country Payroll (inside the Payroll app)

Status 2026-11-24: **18.0.1.1.0 live (05:11 UTC restart)**; 18.0.1.0.0 installed 2026-11-23.
1.1.0: the Companies options and default selection = companies on the contracts (open/closed, overlapping the period)
of employees whose user has the payroll's Leave Location, limited to companies registered in that country.
They follow Payroll / Month / Year. Allowed Companies no longer limit them, and Payroll Officers can read every company.
Fetch skips employees with another leave location and lists them under Not Fetched.
All 38 automated tests pass (`--test-tags /om_hr_payroll_extended_gk`, 0 failed / 0 errors).
The first test run caught one bug, now fixed: reading the label of a related selection field.

## 1. Existing modules analysed
| Module | What was found / reused |
|---|---|
| `om_hr_payroll` (Payroll) | `hr.payslip`: `onchange_employee_id` (Generate Payslips values), `get_worked_day_lines` (attendance + approved leave + Sundays + public holidays + late login + Dubai sick split), `get_inputs`, `compute_sheet` / `_get_payslip_lines` (salary rules incl. India Basic/EPF `india_pf`), `lop_days`, `pf_*` fields, report `om_hr_payroll.action_report_payslip`. One structure `BASE` (18 rules) serves both countries; India vs UAE is decided by `employee.country_for_leave`. |
| `leave_management_rk` | `res.users.country` (india / dubai) = the two existing locations; `leave.request` (approved / pending states, `is_half_day`, LOP type `leave_type_lop`, permission, Dubai sick tiers); `public.holiday`; 26th–25th leave month (`leave_month_bounds`); `hr.attendance._is_late_checkin`. |
| `employee_extended_rk`, `om_hr_payroll` (employee) | Bank fields `bank_account_no`, `bank_iban_number`, `bank_route_number`; core `bank_account_id` (res.partner.bank). |
| `sale_order_approval` | `res.company.approver_user_id` = Company Quotation Approver (re-used, no new approver config). |
| `salary_administration_gk` | **Does not exist.** The Salary Administration module (`salary_processing_gk`) was uninstalled and deleted on 2026-11-23 at the user's request. All salary logic therefore comes from the current Payroll rules. |

## 2. Design in one paragraph
A **Payroll Country** row (Dubai Payroll → AE / `dubai`, India Payroll → IN / `india`) creates its own
menu under Payroll. A **batch** (`payroll.country.batch`) = country + month + year + companies of that
country. **Fetch Employees** follows Employee → Contract → Company (all employees sit on company 1;
the paying entity is the contract's company). **Calculate** creates one draft `hr.payslip` per line exactly
like Payroll's Generate Payslips and runs **Compute Sheet**. Nothing is recalculated outside Payroll's
rules. Typed figures are applied on the payslip lines and Gross/Net re-added like the NET rule. The line
shows what the payslip holds. **Approve** sets the payslips to Done. **Send Payslips** emails the
Payroll PDF. **My Payslips** lists the user's own Done payslips of approved batches.

## 3. New models
| Model | Purpose |
|---|---|
| `payroll.country` | country config: name, `country_id`, `leave_location`, sequence, generated menu + action |
| `payroll.country.batch` | Payroll Reference (PAYRUN/YYYY/####), country, companies, month, year, period (26th–25th), totals, state draft → calculated → submitted → approved / rejected / cancel, submitted/approved/rejected by + dates, rejection reason, approving company + its approver |
| `payroll.country.line` | employee / contract / company / payslip + snapshots (employee, contract, previous payslip, bank masked + full, attendance, leave), salary figures + `calc_*` engine twins + `manual_keys`, check status, email status |
| `payroll.country.line.leave` | approved leave per line (type, dates, days in period, paid / unpaid / permission / Dubai sick) |
| `payroll.country.change.log` | audit trail of manual changes (old, new, calculated, user, date) |
| `payroll.country.excluded` | employees not fetched + reason (never silently excluded) |
| `payroll.country.notify.log` | notification history, unique (batch, kind, submission round, user) |
| `payroll.payslip.send.log` | payslip email history: recipient, status, attempt, mail.mail, sent date, failure |
| wizards | `payroll.country.reject.wizard` (reason required), `payroll.country.report.wizard` (PDF / Excel) |

## 4. Existing models extended
* `hr.payslip`: `country_line_id`, stored `country_batch_id`, `country_batch_state`, `payroll_month`, `payroll_year`; net/gross related; `action_download_my_payslip`; unlink refused while its batch is submitted/approved.
* `hr.employee`: `payroll_bank_holder`, `payroll_bank_name`, `payroll_bank_branch`, `payroll_bank_ifsc` (HR Officers only). These are the only bank values the existing fields could not hold.
* `res.users`: `payroll_country_ids` (Allowed Payroll Countries, m2m res.country).
* `mail.mail`: `payroll_send_log_id`; `write` follows the real mail state into the history.
* `ir.ui.menu._load_menus_blacklist`: hides country menus not assigned to the officer, and hides Payroll Approvals from users who approve no company.
* `res.company.write`: clears the menu cache when the quotation approver changes.
* `hr.salary.rule` data: `PAYROLL_OT` (Overtime Pay) and `PAYROLL_OTHER_EARN` (Other Earnings). These are **not attached to any structure**: Compute Sheet never runs them. They only carry typed values onto the payslip.

## 5. Menus (Payroll app)
Employee Payslips (existing, untouched) · Payslips Batches (existing) · **Dubai Payroll** (seq 11) ·
**India Payroll** (12) · **Payroll Approvals** (13, quotation approvers) · **Unsent Payslips** (14) ·
Employees (existing) · **Payroll Reports** (16) · **My Payslips** (20, every internal user) ·
Configuration › **Country Payroll** › Payroll Countries / Payroll Officers / All Country Payroll (Payroll Manager).

"My Payslips" is the employee self-service menu the spec calls "Employee Payslips". It was renamed
because Payroll already has an "Employee Payslips" menu (the officers' list). My Payslips is at
sequence 20, so the Payroll app still opens on Employee Payslips for payroll users.

## 6. Security
Groups: **Payroll Officer** (new category "Country Payroll", implies Internal User only, **no HR or
contract access**: every employee/contract/payslip read is sudo inside checked methods).
Administrator = Payroll **Manager** (`om_hr_payroll.group_hr_payroll_manager`).
Quotation Approver = `res.company.approver_user_id` (dynamic, no group).

| | Employee | Payroll Officer | Quotation Approver | Payroll Manager |
|---|---|---|---|---|
| My Payslips (own Done payslip of approved batch) | ✔ | ✔ | ✔ | ✔ |
| Country menus / batches | ✘ | assigned countries | read, after submission, batches of their companies | all |
| Lines | ✘ | assigned countries ∩ allowed companies | lines of companies they approve | all |
| Fetch / edit / calculate / submit / cancel | ✘ | ✔ (method checks + rules) | ✘ | ✔ |
| Approve / reject | ✘ | ✘ (unless also approver; never own submission) | ✔ (not own submission) | ✔ |
| Send payslips / unsent list | ✘ | assigned countries, approved only | ✘ | ✔ |
| Reports | ✘ | lines they can read | lines they can read | all |

Record rules: batch (officer countries / approver / manager), line (officer countries + `user.company_ids`,
the batch's approver + submitted+), children follow the line, `hr.payslip` own-approved rule for
base.group_user (OR-ed with Payroll's own officer/manager rules, so it only adds). Downloads go through
`/payroll/my-payslip/<id>/download`. The route checks the record rules, then ownership + approved batch +
Done on every request, then renders Payroll's own payslip PDF.

## 7. Calculation details
* **Eligibility:** contracts of the selected companies in state open/close overlapping the period.
  Excluded with a reason: New contract, employee archived before the period, left before the period,
  already in another live batch, already paid (Done payslip). Employees of the companies with no
  contract are listed too.
* **Joiners / leavers:** the payable window is contract start/end ∩ departure date. Sundays and public
  holidays outside the window are removed from Payroll's worked days, so the LOP rule charges those
  days. Present days come only from attendance.
* **Attendance / leave:** Payroll's `get_worked_day_lines` is used as is. The line also shows working
  days, absent days, half days, late arrivals, worked and overtime hours, per-leave detail and pending
  leave count. Pending leave is a warning; only approved leave counts.
* **Manual edits** (draft / calculated / rejected): LOP Days, Basic, HRA, Other Allowances, Overtime
  Pay, Other Earnings, EPF, Other Deductions.
  * Typed LOP days shift the PRESENT / LATE_DEDUCT worked days, so the LOP rule, India Basic/EPF and
    Net all follow.
  * Other figures are set on the payslip lines. India EPF follows a typed Basic unless EPF was typed too.
  * Each change is audited (change log + chatter tracking) and kept across Recalculate.
    "Back to Calculated Values" resets them.
* **Employee / Contract sync (1.9.0, `SYNC_FIELDS`):** employee details (name, ID, department,
  designation, joining date, work location, email), bank details and contract details (reference,
  dates, status, structure, schedule, every salary component) are the records' own values, in both
  directions:
  * Typed in the popup -> written (sudo) to the Employee / Contract, never kept as a manual override;
    the line re-reads the source and the payslip is recalculated. Department, work location,
    structure and schedule are matched by exact name (unknown name = error); contract status by
    label or key. The change log column "Also Updated In" says which record was changed.
  * Changed on the Employee / Contract / core Bank Account (`hr.employee`, `hr.contract`,
    `res.partner.bank` `write()`) -> every line of a draft / calculated / rejected batch built on it
    is refreshed, and recalculated when the pay depends on the change. Submitted / approved / cancelled
    batches keep their snapshot. A failed refresh never blocks the HR save; the line is flagged.
  * Still per payroll (manual_keys): attendance, leave lines, previous payslip, Payable From / To,
    Employee Status, and the salary figures (which go to the payslip).
  * Migration 1.9.0 dropped the employee / contract / bank values typed on open lines before the
    sync existed (live: line 327, test values only) instead of copying them into HR.
* **PF / ESI: India employees only (1.11.0).** `line.pf_esi_applies` = employee Leave Location is
  India (set at fetch / refresh). Otherwise EPF / ESI / formula values are always 0, the payslip carries
  no EPF / ESI line, typing EPF / ESI / PF-ESI entry is refused, and the fields, batch columns, country
  PF / ESI settings and PDF / Excel register columns are hidden.
* **Checks** (errors block Submit):
  * No contract or structure.
  * No user, or the leave location differs from the payroll country (the wrong country's rules would
    apply).
  * Bank details are NOT validated (removed in 1.10.0 on request): missing or malformed bank name,
    holder, account, IBAN or IFSC never blocks a line or Submit.
  * Not calculated, or payslip edited / cancelled in Payroll.
  * Another payslip for the period.
  * Attendance / leave / contract changed since the calculation.
  * Warnings only: pending leave, net ≤ 0, no work email, manual changes.
* **Submit** also checks that no eligible employee is missing and that the Approving Company has an
  active Quotation Approver. It never raises, so the check results stay saved; the problems come back as a
  sticky notification.
* **Approval (1.12.0): one approver per batch.** `batch.company_id` (Approving Company) = the active
  company the batch was created in (changeable before submission, among the user's own companies);
  its Quotation Approver is the only approver, whatever companies the batch pays, and one approval
  completes it. The batch's approver reads every line of it (rules on `batch_id.approver_user_ids`).
  A Payroll Manager can also approve. Approving writes payslip `state = done` directly; Payroll's
  `action_payslip_done` is **not** used because it emails every employee immediately.

## 8. Payslip distribution
* **Send Selected** with nothing ticked → error, no mail.
* **Send All** has a confirm dialog and skips sent / queued payslips.
* **Resend** is an explicit, confirmed action.
* Each email: Payroll's payslip PDF (rendered in sudo) attached; subject
  "Your Payslip for <Month> <Year> – <Company>". `mail.mail` is kept (`auto_delete` off).
* Status flow: pending → queued → sent / failed (mail.mail state + failure reason), plus
  no_email and awaiting-resend. A 30-minute cron re-syncs queued mails.

## 9. Files
`__manifest__.py`, `controllers/main.py`, `models/{tools,res_users,res_company,ir_ui_menu,payroll_country,payroll_logs,payroll_line,payroll_batch,hr_payslip,hr_employee,mail_mail}.py`,
`wizard/{reject_wizard,report_wizard}.py` + views, `report/report_actions.xml`, `report/report_templates.xml`,
`security/security.xml`, `security/ir.model.access.csv`, `data/{ir_sequence,salary_rule_data,mail_template_data,ir_cron,payroll_country_data}.xml`,
`views/{payroll_country,payroll_line,payroll_batch,my_payslip,hr_employee,res_users}_views.xml`, `views/menus.xml`,
`tests/{common,test_access,test_calculation,test_workflow}.py`.
No existing module was modified.

## 10. Tests (38, all passing 2026-11-23)
* 38 tests in `tests/`, tag `country_payroll`, covering spec sections A–I.
* Each test runs in a transaction that is rolled back.
* Period March 2039 (no live data). Reuses the UAE and India companies with the fewest contracts;
  their live contracts are parked as cancelled inside the test transaction.
* Most tests swap Payroll's worked days for a fixed full-attendance stand-in. D1–D3 use the real
  engine with real leave, attendance and holiday records.
* Static checks done: `py_compile` of every file, lxml parse of every XML, and every view `<field>`
  checked against its model.

## 11. Known gaps / decisions for the user
* **Live data blocks submission today:**
  * Ablez (12) and KGRN & Co LLP (13) have **no Quotation Approver**.
  * Companies 4 and 15 point to an archived approver.
  * Almost no employee has complete bank details (0 holder / bank name).
  * Outgoing SMTP has been failing since 2026-04, so every email will show **Failed**.
* Officers need the country's companies in **Allowed Companies** (res.company is only readable there).
* Writing Allowed Payroll Countries on users needs Settings rights (res.users).
* Payroll users can still open these draft payslips from Payroll › Employee Payslips and Compute Sheet
  them. The line then flags "changed in Payroll" and asks for Recalculate.
* There is no overtime salary rule in Payroll. Overtime hours are shown; overtime **pay** is a manual
  figure.

## 12. Upgrade / test commands
```
/opt/odoo18/venv/bin/python3 /opt/odoo18/odoo/odoo-bin -c /etc/odoo18.conf -d live \
  -u om_hr_payroll_extended_gk --test-tags /om_hr_payroll_extended_gk \
  --stop-after-init --workers=0 --http-port=8199 --gevent-port=8299
systemctl restart odoo18      # new Python must be imported by the workers
```

## Access levels, approval and self-service (18.0.1.17.x)

* **Payroll dropdown on the user** (om_hr_payroll category): **Officer → Manager → Admin**. The old
  "Country Payroll / Payroll Officer" checkbox group and the Allowed Payroll Countries field are gone
  (field kept unused in the DB).
* **Officer**: country = the user's own **Leave Location** (Country For Leave Model). Sees only that
  country's payroll menu / batches / lines, and in the Employees app only employees (and contracts)
  whose user has the same Leave Location: global rules `rule_employee_payroll_officer_location` /
  `rule_contract_payroll_officer_location` on `res.users.payroll_restricted_location` (Officer, not
  Manager, not HR Administrator). Changing a Leave Location applies at once (cache cleared).
* **Manager**: every country. **Admin** (`group_payroll_admin`, implies Manager): the only approvers.
  Approval requests (mail + activity) go to the Payroll Admins only; Payroll Approvals menu is Admins
  only. Four-eyes: an Admin cannot decide on their own submission unless they are the only Admin.
* **Submitted batch**: Approve, Reject, **Resubmission**. Resubmission opens the reason popup, logs the
  reason in the chatter, mails only the preparer (`submitted_by`) and puts the batch in
  **Resubmission Requested** (editable, Submit again).
* **Approved / rejected mails**: the country's Officers, then every Payroll Manager (Admins included)
  and the preparer get the same mail.
* **Payslip app**: My Payslips is its own top-level app (every internal user): own approved payslips
  only, download as PDF.
* Country menus are re-synced on every upgrade (`payroll.country._sync_all_menus`).
* **Archived employees (18.0.1.18.0) are never in a payroll**, not even for the month they left:
  Fetch lists them under Not Fetched ("Employee is archived"), they do not make a company appear,
  and archiving an employee removes them (and their draft payslip) from every open batch at once
  (chatter note). Submitted / approved batches are not changed.
* **Employees / Contracts menus (18.0.1.19.0)** list only employees whose user is active (the
  active users of Settings > Users), by overriding the domains of `hr.open_view_employee_list_my`
  and `hr_contract.action_hr_contract` (views/hr_employee_views.xml). Display only: payroll, leave
  and attendance still use every active employee. Upgrading `hr` / `hr_contract` restores core's
  domains - upgrade this module again afterwards. (Put here, not in employee_extended_rk, because
  upgrading that module also upgrades om_hr_payroll, which rewrites its salary rules.)
* **Speed (18.0.1.20.0)**: Fetch & Calculate of 43 employees 31.9 s -> 14.2 s profiled (10.4 s real),
  11,705 -> 3,414 queries; popup save ~0.2 s. `models/perf.py` = per-operation cache (one Save /
  Fetch / Calculate / Submit, `@scoped` entry points): the Payroll worked days are computed once per
  employee (were 4x: snapshot, calculation, fingerprint, Payroll's onchange), leave_management_rk's
  late-login rules read permission leaves once per user and late days once per period (were per
  check-in / per late day, quadratic) - `models/hr_attendance.py`, same results, only inside a
  payroll operation. The payslip is built without om's onchange (name rebuilt the same way), its
  worked-days / input lines are rewritten only when they changed, and its writes are untracked.
  Verified identical figures for all 43 lines with the cache on and off.
* **Active users only (18.0.1.21.x)**: payroll fetches only employees whose user is active
  (no user / archived user -> Not Fetched); archiving a user archives every contract of their
  employees and removes them from open batches (`res.users._payroll_user_archived`). Applied to
  everyone on 2026-11-24 by migration 1.21.0 (92 contracts archived, 40 open lines removed from
  PAYRUN/2026/0161; approved PAYRUN/2026/0554 untouched). Backup: /root/kgrn_backups/
  contracts_to_archive_20261124_1303.csv + payroll_tables_before_archived_users_20261124_1303.sql.
* **Buttons**: Check removed; Submit for Approval only in Calculated (server enforces it too) -
  a Rejected / Resubmission Requested batch is Recalculated first, which makes it Calculated.
* **LOP policy (18.0.1.22.0)**: LOP days = attendance **Absent days + approved Unpaid leave days**
  (or a typed LOP Days). Late logins (shown as "Late Login Days (not deducted)"), Dubai half-pay sick
  days (paid as full-pay sick) and days before joining / after leaving no longer reduce the salary.
  Done only on this module's payslips: `_normalize_worked_for_lop` + `_apply_lop_override` shift the
  worked days the unchanged Payroll LOP rule reads. "Calculated LOP Days" removed from the form.
* **LOP Days = Absent Days (18.0.1.23.0)**: Absent = working days - present - paid leave, so approved
  unpaid leave is counted in Absent (Unpaid Leave stays as information); LOP Days always equals Absent
  Days unless typed, also live on screen (onchange; the save does not treat that as a typed LOP).
* **Submit again from Resubmission Requested / Rejected (18.0.1.34.0)**: Submit for Approval shows in
  Calculated, Rejected and Resubmission Requested; from the last two it runs `action_calculate` first
  (manual changes kept), then the usual checks and submission. Banners say so.
* **Approval request email (18.0.1.33.0)**: the "Use Generate Report ... Approve, Reject or Resubmission"
  sentence removed.
* **Payslip PDF back on the employee payslip email (18.0.1.32.0)**: only that email carries an
  attachment (the PaySlip PDF); the body still has no salary figure and no My Payslips link. Core
  Payroll's confirm mails and the approval mails stay without attachments.
* **Download Payslip + payslip reference (18.0.1.31.0)**: gear (Actions) menu "Download Payslip" on the
  employee payroll form / list (server action -> `action_download_payslip`, Payroll's PaySlip PDF, one
  PDF for several lines; Officers of the country / Managers). `payslip_ref` is now computed from the
  payslip (number, or name before approval): the 1.29.0 renumbering had left the old numbers on the
  lines.
* **Work From Home Deduction, India (18.0.1.30.0)**: `work_from_home` checkbox on the line (Attendance
  tab, India lines only) -> `wfh_deduction` = Gross / 30 x WFH % (payroll.country.wfh_rate, 4) x 30, on its
  own payslip line PAYROLL_WFH "Work From Home Deduction" (structure-less DED rule, like PAYROLL_OT), set
  in `_apply_overrides` on the final Gross: one line, updated on every calculation, 0 when unticked.
  `other_deductions` keeps its meaning (contract / typed) and excludes WFH; Total Other Deductions =
  other + WFH; Total Deductions and Net include it. Register PDF / Excel get a WFH column when deducted.
  Reset to calculated unticks it.
* **References, payslip numbers, Payslip Batches (18.0.1.29.0)**: batch name = PAYROLL/<country
  reference code>/<year>/<month> (payroll.country.reference_code, UAE / IND; a second batch of the
  same country + month gets -2, -3...); the PAYRUN sequence is no longer used. Payslip numbers come from
  Payroll's salary.slip sequence (now no_gap, one series for every company) only when a payslip is
  confirmed: drafts never take one (`hr.payslip.compute_sheet` override), approval numbers the slips in
  payroll order (company, employee) and creates a Payroll > Payslip Batches entry named after the
  batch (state Close). Employee Payslips hides a country payroll's payslips until it is approved.
  Migration: 3 batches renamed, 54 approved payslips renumbered SLIP/1207-1260 (after SLIP/1206, the
  highest of the payslips removed on 2026-11-24), 3 Payslip Batches created, sequence next 1261.
* **Payroll chatter without emails (18.0.1.28.0)**: notification / payslip emails are created with
  model/res_id False (not posted on the batch / line chatter); `payroll.no.mail.chatter` refuses
  message_post with subtype mt_comment (Send message) or attachments, ir.attachment refuses
  res_model payroll.country.batch / line; the forms' class `o_payroll_no_mail_chatter` hides Send message
  and the attach buttons (static/src/payroll_chatter.scss). Log note stays. Migration detaches the
  email copies already in the chatter.
* **No payslip PDF in emails (18.0.1.27.0)**: the employee payslip email has no attachment; it links to
  Payslip > My Payslips. om_hr_payroll's own confirm mails (`action_payslip_done`, `done_payslip_run`)
  no longer attach the PDF either.
* **No salary figures in emails (18.0.1.26.0)**: Total Gross / Deductions / Net removed from the
  notification email table (`_mail_rows`, shared by the submit / approve / reject / resubmission mails).
* **Quotation Approver = default Payroll Admin (18.0.1.25.0)**: setting a company's Quotation Approver
  User (res.company.approver_user_id, sale_order_approval) adds that active internal user to Payroll
  Admin (`res.company._sync_payroll_admins`, also run by the 1.25.0 migration for every company). Only
  adds; removing Admin is done on the user.
* **LOP = Late Login + Unpaid Leave (18.0.1.24.0)** - replaces the two entries above. LOP Days =
  Late Login Days (half a day per late login past the grace days) + approved Unpaid (Loss of Pay type)
  leave days, unless typed. Absent days (no attendance, no approved leave) are shown but NOT deducted;
  Dubai half-pay sick days and days outside the contract still are not deducted. On screen, LOP Days
  follows Late Login / Unpaid Leave and LOP Deduction follows LOP Days (wage / days in period x LOP
  days) at once; Save recalculates through the rules and does not treat these onchange values as typed.
