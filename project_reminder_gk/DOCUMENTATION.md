# Project Reminder — Module Documentation

**Version:** 18.0.1.0.0
**Category:** Project Management
**Author:** KGRN
**Odoo Version:** 18.0
**Last Updated:** June 2026

---

## Table of Contents

1. [Overview](#1-overview)
2. [Key Features](#2-key-features)
3. [Prerequisites & Dependencies](#3-prerequisites--dependencies)
4. [Installation](#4-installation)
5. [Configuration](#5-configuration)
6. [User Guide](#6-user-guide)
   - 6.1 [Creating a Reminder Schedule](#61-creating-a-reminder-schedule)
   - 6.2 [Understanding the Wizard](#62-understanding-the-wizard)
   - 6.3 [Viewing Reminders](#63-viewing-reminders)
   - 6.4 [Managing Individual Reminder Lines](#64-managing-individual-reminder-lines)
   - 6.5 [Managing the Reminder Schedule](#65-managing-the-reminder-schedule)
   - 6.6 [Calendar View](#66-calendar-view)
7. [Status Lifecycle](#7-status-lifecycle)
   - 7.1 [Reminder Line Statuses](#71-reminder-line-statuses)
   - 7.2 [Reminder Schedule Statuses](#72-reminder-schedule-statuses)
8. [Automated Email Notifications](#8-automated-email-notifications)
9. [Scheduled Jobs (Cron)](#9-scheduled-jobs-cron)
10. [Period Types Reference](#10-period-types-reference)
11. [Access Rights](#11-access-rights)
12. [Models & Fields Reference](#12-models--fields-reference)
13. [Technical Notes](#13-technical-notes)
14. [Frequently Asked Questions](#14-frequently-asked-questions)

---

## 1. Overview

**Project Reminder** is a custom Odoo 18 module that enables project teams to schedule and track periodic delivery or obligation reminders for client projects. It integrates directly with the Project and Sale Order modules to automatically generate reminder checkpoints based on the client engagement timeline.

### Who Is This For?

- **Project Managers** — to stay on top of recurring client obligations and delivery milestones.
- **Management / Approvers** — to receive a consolidated monthly view of all active project commitments.
- **Operations Teams** — to ensure no periodic obligation is missed across a portfolio of projects.

### What Problem Does It Solve?

When a firm manages multiple ongoing engagements with recurring deliverables (e.g., monthly reports, quarterly reviews, annual compliance filings), tracking each obligation manually is error-prone. Project Reminder automates this by:

- Generating reminder checkpoints for the full engagement period in a single setup step.
- Sending automated email alerts 2 days before and on the actual due date.
- Providing a monthly digest to both the responsible project manager and senior management.

---

## 2. Key Features

| Feature | Description |
|---|---|
| **Period-based scheduling** | Automatically generates reminder lines for Yearly, Half-Yearly, Quarterly, or Monthly periods across the full engagement. |
| **Smart date picker** | Date picker in the setup wizard restricts selectable dates to the valid window for each period, preventing invalid entries. |
| **Dual-channel notifications** | Sends an early warning (2 days before) and a due-today alert on the actual reminder date. |
| **Monthly PM digest** | A consolidated HTML summary email is sent to each Project Manager on the 1st of every month. |
| **Monthly approver summary** | A company-wide management summary is emailed to the designated approver on the 1st of every month. |
| **Calendar view** | Reminders are visible in a colour-coded monthly calendar. |
| **Chatter integration** | All status changes and sent emails are logged in the schedule's Odoo chatter thread. |
| **One active schedule rule** | Each project can have only one active reminder schedule at a time, preventing duplicate tracking. |
| **Closed-project guard** | The Add Reminder button is hidden on projects in closed stages (Done, Cancelled, etc.). |

---

## 3. Prerequisites & Dependencies

The following Odoo modules must be installed before installing Project Reminder:

| Module | Purpose |
|---|---|
| `project` | Core Odoo project module |
| `sale` | Sale order and sale order line data |
| `mail` | Email templating and chatter |
| `project_extended_rk` | Adds `engagement_start` / `engagement_end` fields to Sale Order Lines |
| `crm_extended_rk` | CRM extensions required by the extended project module |

> **Important:** Engagement start and end dates come from the Sale Order Line via `project_extended_rk`. Ensure sale order lines have these dates populated before creating a reminder schedule.

---

## 4. Installation

1. Copy the `project_reminder_gk` folder into your Odoo `addons` directory (or your custom addons path as configured in `odoo.conf`).
2. Restart the Odoo server.
3. In Odoo, go to **Settings → Apps** and click **Update Apps List**.
4. Search for **Project Reminder** and click **Install**.
5. The five automated cron jobs and two email templates are created automatically on installation.

---

## 5. Configuration

### 5.1 Company Approver

The monthly management summary email is sent to a company-level approver. To set this up:

1. Go to **Settings → General Settings → Company**.
2. Find the **Approver** field (provided by `crm_extended_rk` / `project_extended_rk`).
3. Select the user who should receive the consolidated management summary.

> If no approver is configured, the monthly approver summary cron will silently skip sending.

### 5.2 Outgoing Mail Server

Ensure your Odoo instance has an outgoing mail server configured:

1. Go to **Settings → Technical → Email → Outgoing Mail Servers**.
2. Verify at least one server is active and working.
3. Test the connection using the **Test Connection** button.

All reminder emails are dispatched through this outgoing mail server.

### 5.3 Sale Order Line Engagement Dates

Before creating a reminder schedule on a project:

1. Open the linked Sale Order.
2. Ensure the relevant Sale Order Line has **Engagement Start** and **Engagement End** dates filled in.
3. These dates define the boundaries within which reminder periods and dates are generated.

---

## 6. User Guide

### 6.1 Creating a Reminder Schedule

A reminder schedule is created from the Project form using the **Add Reminder** button.

**Step-by-step:**

1. Open a project from **Project → Projects**.
2. In the project header area, locate the **Add Reminder** smart button or button (visible only when the project has no active reminder schedule and is not in a closed stage such as Done or Cancelled).
3. Click **Add Reminder**. The setup wizard opens in a popup window.
4. Configure the reminder as described in [Section 6.2](#62-understanding-the-wizard).
5. Click **Confirm & Schedule** to save and activate the schedule immediately.

> **Note:** Only one active reminder schedule is allowed per project. If an active schedule already exists, the button will show a validation error. You must cancel or complete the existing schedule before creating a new one.

---

### 6.2 Understanding the Wizard

The **Add Project Reminder** wizard has two sections:

#### Project Section (Read-only)

| Field | Description |
|---|---|
| **Project** | The current project (auto-filled, cannot be changed). |
| **Customer / Project Customer** | The customer linked to the project (auto-filled). |
| **Sale Order** | The sale order linked to the project (auto-filled). |
| **Sale Order Line** | Required. Select the specific line from the linked sale order. This determines the engagement period. |
| **Engagement Start** | Auto-filled from the selected Sale Order Line. |
| **Engagement End** | Auto-filled from the selected Sale Order Line. |

#### Reminder Configuration Section

| Field | Description |
|---|---|
| **Reminder Type** | The frequency of reminders. Choose from: Yearly, Half-Yearly, Quarterly, Monthly. |
| **Yearly Frequency** | Only visible for **Yearly** type. Choose 1, 2, or 3 reminders per year. |
| **Remarks** | Optional free-text notes. These are included in all notification emails for this schedule. |

#### Reminder Dates Tab

Once you select a Sale Order Line and Reminder Type, the system automatically generates one row per period across the full engagement date range.

| Column | Description |
|---|---|
| **Period** | The period label (e.g., "Q2 2026", "H1 2025", "March 2026"). Auto-generated, read-only. |
| **Reminder Date** | The specific date within the period by which the obligation must be met. **You must set this for every row.** |

**Date Picker Restriction:** The date picker for each row is automatically restricted to the valid date window — the intersection of the period's own start/end and the engagement start/end. Dates outside this window are greyed out and cannot be selected.

**Example:**
If the engagement runs from 01-Jan-2025 to 31-Dec-2026 and you select **Quarterly**, the wizard generates 8 rows: Q1 2025 through Q4 2026. For Q2 2025, the date picker only allows dates between 01-Apr-2025 and 30-Jun-2025.

---

### 6.3 Viewing Reminders

#### From the Project Form

The project form shows three smart buttons (or counters) in the header area:

| Counter | What It Shows |
|---|---|
| **Total Reminders** | Total number of reminder lines across all schedules for this project. |
| **Upcoming Reminders** | Lines currently in the Upcoming state. |
| **Completed Reminders** | Lines that have been completed. |

Click any of these buttons (or the dedicated **Reminders** button) to open the full list of reminder lines filtered to the current project.

#### From the Main Menu

Navigate to **Project → Reminders** for two dedicated menu options:

| Menu Item | Who Can Access | What It Shows |
|---|---|---|
| **Reminder Lines** | All project users | Individual reminder entries across all projects, with list, calendar, and form views. |
| **Reminder Schedules** | Project Managers only | The parent schedule records with their configuration. |

#### Filtering and Grouping

The list views include built-in search filters:

- **By Status:** Draft, Scheduled, Upcoming, Notification Sent, Completed, Cancelled
- **By Type:** Yearly, Half-Yearly, Quarterly, Monthly
- **Mail Pending:** Upcoming Mail Pending, Due Today Mail Pending
- **Group By:** Project, Reminder Type, Project Manager, Status, Month

---

### 6.4 Managing Individual Reminder Lines

Each reminder line represents a single period's obligation. You can open any line in form view from the list or calendar.

#### Available Actions on a Line

| Button | Available When | What It Does |
|---|---|---|
| **Mark Completed** | State is Upcoming or Notification Sent | Marks the line as Completed and updates the parent schedule state. |
| **Cancel Reminder** | Any state except Cancelled | Cancels this specific line only. Does not cancel the rest of the schedule. |

#### Line Form Fields

| Field | Description |
|---|---|
| **Project** | The linked project (read-only). |
| **Customer** | Customer from the project (read-only). |
| **Sale Order** | Linked sale order (read-only). |
| **Sale Order Line** | The specific line providing the engagement period (read-only). |
| **Project Manager** | The project's assigned manager (read-only). |
| **Reminder Type** | Inherited from the schedule (read-only). |
| **Period** | The period label, e.g., "Q3 2026" (read-only). |
| **Reminder Date** | The scheduled due date. Can be edited if the schedule is not completed or cancelled. |
| **Upcoming Email Date** | Computed as Reminder Date − 2 days. This is when the early-warning email is sent. |
| **Upcoming Reminder Sent** | Checkbox. Ticked automatically when the 2-day advance email has been dispatched. |
| **Due Today Reminder Sent** | Checkbox. Ticked automatically when the on-date email has been dispatched. |
| **Remarks** | Notes from the parent schedule (read-only on the line). |

---

### 6.5 Managing the Reminder Schedule

Open a schedule from **Project → Reminders → Reminder Schedules**.

#### Schedule Header Buttons

| Button | When Visible | What It Does |
|---|---|---|
| **Activate Schedule** | State is Draft | Transitions all Draft lines to Scheduled, and moves the schedule to Scheduled state. Requires at least one reminder line. |
| **Cancel** | State is not Completed or Cancelled | Cancels all lines and the schedule. Logs the action in chatter. |
| **Reset to Draft** | State is Cancelled | Resets the schedule and all its lines back to Draft. |

#### Schedule Form Sections

**Project Information Group**
- Project, Sale Order Line, Sale Order, Customer, Project Manager (most are auto-filled or read-only).

**Engagement & Reminder Group**
- Engagement Start / End (from the sale order line, read-only).
- Reminder Type and Yearly Frequency.

**Remarks**
- Free-text notes shown in all notification emails.

**Reminder Lines Tab**
- Inline editable list of all reminder lines. You can edit reminder dates directly here (except on completed or cancelled schedules).
- Colour coding: Orange = Upcoming, Blue = Scheduled, Green = Completed, Muted = Cancelled, Yellow-Green = Notification Sent.

**Chatter**
- All actions (schedule activated, emails sent, status changes) are automatically logged here.

---

### 6.6 Calendar View

Go to **Project → Reminders → Reminder Lines** and switch to the **Calendar** view.

- Each reminder line appears as a coloured event on its reminder date.
- Colour codes match the line's current status (see [Section 7.1](#71-reminder-line-statuses)).
- Use the month navigation to browse future or past reminders.
- Click any event to open the reminder line form.

---

## 7. Status Lifecycle

### 7.1 Reminder Line Statuses

| Status | Colour | Meaning |
|---|---|---|
| **Draft** | Grey | Line created but schedule not yet activated. |
| **Scheduled** | Blue | Reminder is confirmed and awaiting its due window. |
| **Upcoming** | Orange | Reminder date is within 2 days. Advance email will be sent. |
| **Notification Sent** | Yellow-Green | The due-today email has been sent. Awaiting manual completion. |
| **Completed** | Green | Obligation fulfilled. Terminal state. |
| **Cancelled** | Red | Reminder cancelled. Terminal state. |

#### Automatic State Transitions (Daily Cron)

The daily cron job checks each active line against today's date and transitions states automatically:

```
reminder_date > today + 2 days  →  Scheduled
reminder_date ≤ today + 2 days  →  Upcoming
reminder_date < today           →  Completed  (if not already Notification Sent)
```

> **Terminal states (Notification Sent, Completed, Cancelled) are never overridden by automatic date logic.** A line that has had its due-today email sent will stay in Notification Sent until you manually mark it Completed.

#### Manual State Transitions

```
Draft ──► [Activate Schedule] ──► Scheduled
Scheduled ──► [Auto: 2-day window] ──► Upcoming
Upcoming ──► [Auto: email sent] ──► Notification Sent
Notification Sent ──► [Mark Completed] ──► Completed
Any ──► [Cancel Reminder] ──► Cancelled
```

---

### 7.2 Reminder Schedule Statuses

The schedule state is automatically derived from the combined states of its active (non-cancelled) lines:

| Condition | Schedule State |
|---|---|
| All active lines are Completed | **Completed** |
| Any active line is Upcoming | **Upcoming** |
| Any active line is Notification Sent | **Notification Sent** |
| All active lines are Scheduled | **Scheduled** |
| All lines are Cancelled | Remains as-is (manual Cancel sets it to Cancelled) |

---

## 8. Automated Email Notifications

Project Reminder sends three types of automated emails. All emails are stored in Odoo's mail queue with **Auto Delete disabled**, so they remain in the system for audit purposes.

### 8.1 Upcoming Reminder Email (2 Days Before)

| Attribute | Value |
|---|---|
| **When** | 2 days before the Reminder Date (10:30 UAE / 06:30 UTC) |
| **Recipient** | Project Manager assigned to the project |
| **Subject** | `Upcoming Reminder - {Project Name} – {Period Label}` |
| **Trigger** | `upcoming_mail_sent = False` AND `reminder_date = today + 2 days` AND state in (Scheduled, Upcoming) |
| **Idempotent** | Yes — the `upcoming_mail_sent` flag prevents duplicate sends |

**Email Content Includes:**
- Project name
- Customer name
- Sale Order number
- Reminder Type
- Period (e.g., Q2 2026)
- Reminder Date
- Remarks (if any)

After a successful send, the chatter on the parent schedule is updated with a log note.

---

### 8.2 Due Today Reminder Email

| Attribute | Value |
|---|---|
| **When** | On the actual Reminder Date (11:00 UAE / 07:00 UTC) |
| **Recipient** | Project Manager assigned to the project |
| **Subject** | `Reminder Due Today - {Project Name} – {Period Label}` |
| **Trigger** | `due_today_mail_sent = False` AND `reminder_date = today` AND state in (Scheduled, Upcoming) |
| **Idempotent** | Yes — the `due_today_mail_sent` flag prevents duplicate sends |

**Effect on Line State:** After a successful due-today email, the reminder line is automatically moved to **Notification Sent** status. This ensures the line remains visible and actionable until a human confirms the obligation has been met.

---

### 8.3 Monthly PM Summary Email

| Attribute | Value |
|---|---|
| **When** | 1st of every month (10:00 UAE / 06:00 UTC) |
| **Recipients** | Every Project Manager who has at least one active reminder line in the current month |
| **Subject** | `Monthly Project Reminders – {Month Year}` |
| **Content** | HTML table: Project, Customer, SO Number, Type, Date |

Each Project Manager receives a personalised email listing only their own projects. The email is not sent if there are no active reminders for that manager in the current month.

---

### 8.4 Monthly Approver Summary Email

| Attribute | Value |
|---|---|
| **When** | 1st of every month (10:05 UAE / 06:05 UTC) |
| **Recipient** | `company.approver_user_id` (configured in company settings) |
| **Subject** | `Management Summary – Project Reminders {Month Year}` |
| **Content** | HTML table: Project Manager, Project, Customer, SO Number, Type, Date |

This is a company-wide consolidated view across all project managers, ordered by Project Manager then by Reminder Date. It is sent only if there are active reminder lines in the current month and the approver is configured.

---

## 9. Scheduled Jobs (Cron)

All five cron jobs are created automatically on module installation and are active by default. They can be viewed and manually triggered from **Settings → Technical → Automation → Scheduled Actions**.

| Job Name | Schedule | Time (UTC) | Time (UAE) | Method |
|---|---|---|---|---|
| Project Reminders: Daily Status Update | Daily | 06:00 | 10:00 | `_cron_update_statuses()` |
| Project Reminders: Upcoming Reminder Notification | Daily | 06:30 | 10:30 | `_cron_upcoming_reminder_notification()` |
| Project Reminders: Due Today Reminder Notification | Daily | 07:00 | 11:00 | `_cron_due_today_reminder_notification()` |
| Project Reminders: Monthly PM Summary Email | Monthly (1st) | 06:00 | 10:00 | `_cron_send_monthly_pm_summary()` |
| Project Reminders: Monthly Approver Summary Email | Monthly (1st) | 06:05 | 10:05 | `_cron_send_monthly_approver_summary()` |

### Execution Order (Daily)

The three daily crons fire in sequence to ensure correct state before notifications go out:

1. **Daily Status Update** — Transitions line states based on date (most important; runs first).
2. **Upcoming Reminder Notification** — Sends the 2-day advance email.
3. **Due Today Reminder Notification** — Sends the due-date email and promotes lines to Notification Sent.

> **To manually trigger a cron:** Go to **Settings → Technical → Scheduled Actions**, find the job, and click **Run Manually**.

---

## 10. Period Types Reference

### Yearly

| Frequency Setting | Periods Generated (Example: 2024–2025 engagement) |
|---|---|
| 1 reminder per year | 2024, 2025 |
| 2 reminders per year | 2024 – Reminder 1, 2024 – Reminder 2, 2025 – Reminder 1, 2025 – Reminder 2 |
| 3 reminders per year | 2024 – Reminder 1, 2 & 3; 2025 – Reminder 1, 2 & 3 |

### Half-Yearly

Periods follow the calendar halves: H1 = January–June, H2 = July–December.

| Example Period | Date Range |
|---|---|
| H1 2025 | 01-Jan-2025 – 30-Jun-2025 |
| H2 2025 | 01-Jul-2025 – 31-Dec-2025 |

### Quarterly

Periods follow standard calendar quarters.

| Period | Date Range |
|---|---|
| Q1 | 01-Jan – 31-Mar |
| Q2 | 01-Apr – 30-Jun |
| Q3 | 01-Jul – 30-Sep |
| Q4 | 01-Oct – 31-Dec |

### Monthly

Each month from the engagement start month to the engagement end month generates one reminder line (e.g., `January 2025`, `February 2025`, ...).

---

## 11. Access Rights

| Action | Project Manager | Project User |
|---|---|---|
| View Reminder Schedules | Yes (full) | No |
| Create / Edit Reminder Schedule | Yes | No |
| Delete Reminder Schedule | Yes | No |
| View Reminder Lines | Yes (full) | Read-only |
| Create / Edit Reminder Line | Yes | No |
| Delete Reminder Line | Yes | No |
| Use Add Reminder Wizard | Yes | Yes |

> Project Users can open the wizard and view reminder data but cannot create or modify schedules and lines directly outside the wizard. The wizard itself creates records using elevated permissions on confirmation.

---

## 12. Models & Fields Reference

### 12.1 `project.reminder.schedule` — Reminder Schedule

The parent record that holds the configuration for a reminder schedule. One per project (only one active at a time).

| Field | Type | Description |
|---|---|---|
| `name` | Char (computed) | Auto-generated as `{Project Name} – {Reminder Type}` |
| `project_id` | Many2one (project.project) | The project this schedule belongs to |
| `sale_order_line_id` | Many2one (sale.order.line) | Provides engagement dates |
| `sale_order_id` | Many2one (sale.order) | Derived from the sale order line |
| `customer_id` | Many2one (res.partner) | Related from the project |
| `project_manager_id` | Many2one (res.users) | Related from the project |
| `engagement_start` | Date | Related from the sale order line |
| `engagement_end` | Date | Related from the sale order line |
| `reminder_type` | Selection | `yearly`, `half_yearly`, `quarterly`, `monthly` |
| `yearly_frequency` | Selection | `1`, `2`, or `3` — only applicable for yearly type |
| `remarks` | Text | Optional notes, included in all emails |
| `state` | Selection | `draft`, `scheduled`, `upcoming`, `notification_sent`, `completed`, `cancelled` |
| `line_ids` | One2many (project.reminder.line) | The individual reminder lines |
| `line_count` | Integer (computed) | Total number of lines |

---

### 12.2 `project.reminder.line` — Reminder Line

One record per period. The atomic unit that gets emailed about and tracked.

| Field | Type | Description |
|---|---|---|
| `schedule_id` | Many2one (project.reminder.schedule) | Parent schedule |
| `project_id` | Many2one (project.project) | Related from schedule |
| `project_manager_id` | Many2one (res.users) | Related from schedule |
| `customer_id` | Many2one (res.partner) | Related from schedule |
| `sale_order_id` | Many2one (sale.order) | Related from schedule |
| `sale_order_line_id` | Many2one (sale.order.line) | Related from schedule |
| `reminder_type` | Selection | Related from schedule |
| `period_label` | Char (computed) | Human-readable period, e.g., "Q2 2026" |
| `reminder_date` | Date | The date by which the obligation is due |
| `notification_date` | Date (computed) | `reminder_date − 2 days` — when the advance email fires |
| `state` | Selection | `draft`, `scheduled`, `upcoming`, `notification_sent`, `completed`, `cancelled` |
| `upcoming_mail_sent` | Boolean | True after the 2-day advance email is sent |
| `due_today_mail_sent` | Boolean | True after the due-today email is sent |
| `remarks` | Text | Related from schedule (read-only) |
| `color` | Integer (computed) | Odoo calendar color code based on state |

---

### 12.3 `project.reminder.wizard` — Setup Wizard (Transient)

Transient model used only during the reminder creation process. Deleted after confirmation.

| Field | Type | Description |
|---|---|---|
| `project_id` | Many2one | Project (auto-filled from context) |
| `sale_order_line_id` | Many2one | Selected by user |
| `reminder_type` | Selection | Selected by user |
| `yearly_frequency` | Selection | Only for yearly type |
| `remarks` | Text | Optional notes |
| `line_ids` | One2many (project.reminder.wizard.line) | Generated period rows |

---

### 12.4 `project.reminder.wizard.line` — Wizard Period Row (Transient)

| Field | Type | Description |
|---|---|---|
| `wizard_id` | Many2one | Parent wizard |
| `period_label` | Char | Auto-generated period name (read-only) |
| `reminder_date` | Date | Date selected by the user for this period |
| `period_date_min` | Date (computed) | Earliest allowed date (period start ∩ engagement start) |
| `period_date_max` | Date (computed) | Latest allowed date (period end ∩ engagement end) |
| `sequence` | Integer | Sort order |

---

## 13. Technical Notes

### 13.1 Custom Date Widget (`period_date_field`)

A JavaScript widget defined in `static/src/js/period_date_field.js` extends Odoo's standard `DateField`. It reads the `period_date_min` and `period_date_max` values from the same row and disables any calendar date outside that range. This prevents users from accidentally picking a date that falls outside the period boundary or the engagement window, providing an in-UI guard before server-side validation.

### 13.2 Closed Stage Detection

The **Add Reminder** smart button is hidden when `is_closed_stage = True`. A project's stage is considered closed if the stage name is one of: **Done**, **Cancelled**, or **Sent for GRN Approval**. This list is hardcoded in `project_project.py` and can be adjusted by a developer if additional stage names need to be treated as closed.

### 13.3 One Active Schedule Per Project

`action_open_reminder_wizard()` checks `has_active_reminders` — which is True if any schedule exists whose state is not `completed` or `cancelled`. If an active schedule is found, the wizard raises a validation error and asks the user to complete or cancel the existing schedule first.

### 13.4 Idempotent Email Sending

Both the upcoming email and the due-today email use boolean guard fields (`upcoming_mail_sent`, `due_today_mail_sent`) to ensure they are sent exactly once, even if the cron fires multiple times or is run manually. Failed sends (e.g., mail server error) leave the flag as `False`, so the cron will retry on the next run.

### 13.5 Schedule State Derivation

The schedule's state is re-evaluated every time a line state changes, using `_refresh_state_from_lines()`. The priority order is: Upcoming > Notification Sent > Scheduled > Completed. This means as long as any one line is still Upcoming, the parent schedule will show as Upcoming.

### 13.6 Date Range Calculation

Period boundaries are computed by `_get_period_date_range()` on `project.reminder.line`. The effective allowed date range shown in the wizard is the **intersection** of:
- The period's calendar boundary (e.g., 01-Apr-2026 to 30-Jun-2026 for Q2 2026), and
- The sale order line's engagement start and end dates.

This means if an engagement ends on 15-May-2026, Q2 2026's allowed window in the wizard will be 01-Apr-2026 to 15-May-2026 rather than 30-Jun-2026.

---

## 14. Frequently Asked Questions

**Q: Why can't I see the "Add Reminder" button on my project?**

A: The button is hidden in two cases:
1. The project already has an active reminder schedule (state is not completed or cancelled). Cancel or complete the existing schedule first.
2. The project is in a closed stage (Done, Cancelled, or Sent for GRN Approval).

---

**Q: The wizard opens but the Reminder Dates tab is empty. What's wrong?**

A: Dates are generated only when both a **Sale Order Line** and a **Reminder Type** are selected, and the sale order line must have Engagement Start and End dates populated. Check that the sale order line has these dates filled.

---

**Q: I changed the reminder date on a line but the advance email was already sent. Will it resend?**

A: No. The `upcoming_mail_sent` flag is already `True`. The 2-day advance email will not be resent even if you change the date. The due-today email will fire on the new date as long as `due_today_mail_sent` is still `False`.

---

**Q: A reminder date has passed but the line is still in "Notification Sent" state. Is that correct?**

A: Yes. "Notification Sent" is a terminal-equivalent state that the automatic cron will not override. It means the due-today email was sent and the obligation is awaiting manual confirmation. Click **Mark Completed** on the line to close it out.

---

**Q: The monthly summary email was not received. What should I check?**

A: Check the following:
1. The outgoing mail server is configured and working (**Settings → Technical → Email → Outgoing Mail Servers**).
2. The project manager's user account has a valid email address.
3. There were reminder lines in the current month with state Scheduled or Upcoming (if no lines qualified, the email is skipped).
4. For the approver summary: confirm `company.approver_user_id` is set and has an email address.
5. Check **Settings → Technical → Email → Emails** for any failed mail records.

---

**Q: Can I have two different reminder schedules active at the same time for the same project?**

A: No. Only one active schedule is allowed per project. This prevents overlapping reminder tracking for the same project. If you need a different reminder frequency, cancel the existing schedule first and create a new one.

---

**Q: Can I manually run the cron jobs?**

A: Yes. Go to **Settings → Technical → Automation → Scheduled Actions**, find the relevant job (e.g., "Project Reminders: Due Today Reminder Notification"), and click **Run Manually**. This is useful for testing or catching up after a server downtime.

---

**Q: Where can I see whether an email was actually sent for a specific reminder line?**

A: Open the reminder line in form view. The **Upcoming Reminder Sent** and **Due Today Reminder Sent** checkboxes show the current send status. Additionally, the parent schedule's **Chatter** contains a timestamped log entry for each email dispatched.

---

*This documentation covers version 18.0.1.0.0 of the Project Reminder module. For support, contact the KGRN development team.*
