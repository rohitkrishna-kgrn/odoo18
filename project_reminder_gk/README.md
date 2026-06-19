# Project Reminder GK

**Version:** 18.0.1.0.0  
**Category:** Project  
**Author:** KGRN  
**Depends:** `project`, `sale`, `mail`, `project_extended_rk`, `crm_extended_rk`

---

## Overview

This module adds a periodic reminder scheduling system to Odoo projects. Each project can have one active reminder schedule that generates individual reminder lines for fixed periods (yearly, half-yearly, quarterly, or monthly). Reminders trigger automated email notifications to project managers and a management summary to a company-level approver.

---

## Features

- Create reminder schedules tied to a project's sale order engagement period
- Four reminder frequencies: **Yearly**, **Half-Yearly**, **Quarterly**, **Monthly**
- Custom date picker in the wizard that restricts selectable dates to the valid period window
- Automatic state transitions via daily cron jobs
- Three email notification channels:
  - Individual reminder email to project manager (2 days before due date)
  - Monthly consolidated summary to each project manager (1st of month)
  - Monthly management summary to company approver (1st of month)
- Smart button on project form showing reminder count
- Calendar view for visual reminder tracking

---

## Installation

1. Copy `project_reminder_gk` into your Odoo `addons` path.
2. Ensure the following modules are installed: `project`, `sale`, `mail`, `project_extended_rk`, `crm_extended_rk`.
3. Update the app list and install **Project Reminder GK**.

---

## Configuration

### Company Approver
The monthly approver summary is sent to `company.approver_user_id`. Set this field on the company record (provided by a dependent module) before the first monthly cron run.

### Sale Order Lines
Engagement dates (`engagement_start`, `engagement_end`) are read from the selected sale order line. These fields are expected to be present via `project_extended_rk`.

---

## Usage

### Creating a Reminder Schedule

1. Open a project form.
2. Click **Add Reminder** in the project header (visible only when the project has no active schedule and is not in a closed stage).
3. The wizard opens in a new window:
   - **Sale Order Line** — required; filters by the project's sale order.
   - **Reminder Type** — Yearly / Half-Yearly / Quarterly / Monthly.
   - **Yearly Frequency** — visible only for Yearly type; controls how many reminders per year.
   - **Remarks** — optional notes included in notification emails.
4. Period rows are auto-generated based on the engagement date range.
5. Edit the **Reminder Date** for each period. The date picker is restricted to the valid window (period boundary ∩ engagement dates).
6. Click **Confirm & Schedule** to create and activate the schedule.

### Viewing Reminders

- **Smart button** on the project form opens the reminder lines in list/calendar/form views.
- **Project menu → Reminders → Reminder Lines** — all lines for all projects (accessible to all project users).
- **Project menu → Reminders → Reminder Schedules** — schedule records (project managers only).

### Manual Actions on Reminder Lines

| Current State | Available Action | Result |
|---|---|---|
| Upcoming | Action Completed | Completed |
| Any | Cancel Reminder | Cancelled |

### Reminder Schedule Actions

| Button | Condition | Effect |
|---|---|---|
| Activate | Draft, has lines | Draft → Scheduled |
| Cancel | Not cancelled | Cancels all lines and schedule |
| Reset to Draft | Cancelled | Returns to draft |

---

## State Lifecycle

### Reminder Line States

```
draft ──► scheduled ──► upcoming ──► completed
                │                        ▲
                └── cancelled ◄──────────┘
                         ▲
                         │ (from any state)
```

**Automatic transitions (daily cron):**
- `reminder_date < today` → **completed**
- `reminder_date ≤ today + 2 days` → **upcoming**
- `reminder_date > today + 2 days` → **scheduled**

### Reminder Schedule States

The schedule state is derived from its lines:
- All completed → **completed**
- Any upcoming → **upcoming**
- Any scheduled → **scheduled**
- All cancelled → **cancelled**

---

## Automated Jobs (Cron)

All jobs run at **06:00 UTC (10:00 UAE time)**.

| Job | Frequency | Action |
|---|---|---|
| `cron_reminder_daily` | Daily | Update line states; send individual reminder emails 2 days before due date |
| `cron_reminder_monthly_pm` | Monthly (1st) | Send consolidated monthly summary to each project manager |
| `cron_reminder_monthly_approver` | Monthly (1st, 06:05 UTC) | Send management summary to `company.approver_user_id` |

---

## Email Notifications

### Individual Reminder Email
- **Trigger:** Daily cron, 2 days before `reminder_date`
- **Recipient:** Project manager (`project_manager_id.email`)
- **Subject:** `Reminder: {Project Name} – {Period Label}`
- **Content:** Project, customer, sale order, reminder type, period, reminder date, remarks

### Monthly PM Summary
- **Trigger:** 1st of each month
- **Recipient:** Each project manager with upcoming/active reminders that month
- **Content:** Consolidated HTML table of all reminder lines for the month

### Monthly Approver Summary
- **Trigger:** 1st of each month (5 minutes after PM summary)
- **Recipient:** `company.approver_user_id`
- **Content:** Company-wide consolidated table for management review

---

## Period Label Reference

| Type | Example Labels |
|---|---|
| Yearly | `2025`, `2026` |
| Half-Yearly | `H1 2025`, `H2 2025` |
| Quarterly | `Q1 2025`, `Q2 2025`, `Q3 2025`, `Q4 2025` |
| Monthly | `January 2025`, `February 2025`, … |

---

## Access Rights

| Group | Schedules | Lines | Wizard |
|---|---|---|---|
| Project Manager | Full CRUD | Full CRUD | Full access |
| Project User | Read only | Read only | Full access |

---

## Models

| Model | Description |
|---|---|
| `project.reminder.schedule` | Reminder schedule configuration per project |
| `project.reminder.line` | Individual reminder entries with dates and states |
| `project.reminder.wizard` | Transient wizard for creating schedules |
| `project.reminder.wizard.line` | Transient lines within the wizard |

### Key Fields — `project.reminder.schedule`

| Field | Type | Description |
|---|---|---|
| `project_id` | Many2one | Linked project |
| `sale_order_line_id` | Many2one | Source sale order line (provides engagement dates) |
| `reminder_type` | Selection | yearly / half_yearly / quarterly / monthly |
| `yearly_frequency` | Integer | Reminders per year (Yearly type only) |
| `engagement_start` | Date | Related from sale order line |
| `engagement_end` | Date | Related from sale order line |
| `state` | Selection | draft / scheduled / upcoming / completed / cancelled |
| `line_ids` | One2many | Reminder lines |

### Key Fields — `project.reminder.line`

| Field | Type | Description |
|---|---|---|
| `schedule_id` | Many2one | Parent schedule |
| `period_label` | Char | Computed period string (e.g. "Q2 2026") |
| `reminder_date` | Date | Scheduled reminder date |
| `notification_date` | Date | Computed as reminder_date − 2 days |
| `notification_sent` | Boolean | Set to True after individual email is sent |
| `state` | Selection | draft / scheduled / upcoming / completed / cancelled |
| `color` | Integer | Calendar color code |

---

## Technical Notes

### Custom Date Widget (`period_date_field`)
A JavaScript widget (`static/src/js/period_date_field.js`) extends Odoo's standard `DateField` to disable calendar dates outside the computed `period_date_min` / `period_date_max` range. This prevents users from selecting a reminder date that falls outside the period boundary or the engagement window.

### Closed Stage Detection
A project is considered "closed" if its stage name is one of: `Done`, `Cancelled`, or `Sent for GRN Approval`. The **Add Reminder** button is hidden for closed projects.

### One Active Schedule Per Project
`action_open_reminder_wizard()` checks `has_active_reminders` before opening the wizard. Projects with an existing active schedule cannot create a second one without cancelling the first.
