# Recruitment GK — Module Documentation

**Module:** `recruitment_gk`
**Version:** 18.0.1.13.0
**Author:** KGRN
**Odoo Compatibility:** 18.0
**Category:** Human Resources / Recruitment
**License:** LGPL-3
**Dependencies:** `base`, `mail`, `hr`

---

## Overview

Recruitment GK is a complete end-to-end recruitment workflow module for Odoo 18. It covers the full hiring lifecycle — from raising a hiring request, sourcing and reviewing candidates, conducting multi-round interviews, selecting candidates, and handing off to the IT team for onboarding setup — all within a single, role-controlled application.

---

## User Roles & Permissions

### Security Groups (hierarchy, lowest → highest)

| Group | XML ID | Implied Groups | Description |
|---|---|---|---|
| IT Team | `group_recruitment_it_team` | `base.group_user` | Access to IT Onboarding menu only; can read selected candidates and write IT onboarding records |
| HR Admin | `group_recruitment_hr_admin` | `group_user`, `group_recruitment_it_team` | Full access to all recruitment records; manages the entire workflow |
| Hiring Manager | `group_recruitment_hiring_manager` | `group_user` | Creates requests; reviews and approves candidates forwarded to them |
| Management Admin | `group_recruitment_management` | All groups above | Super-admin role; identical to HR Admin plus full visibility everywhere |

### Record-Level Access Summary

| Model | IT Team | Hiring Manager | HR Admin | Management |
|---|---|---|---|---|
| Recruitment Request | — | Own requests only | All | All |
| Recruitment Candidate | Selected only (read) | Own requests (non-draft) + sent-to-them | All | All |
| Interview Round | — | Own candidates (read only) | All | All |
| Final Approval | Read all | — | All | All |
| IT Onboarding | All (read/write, no create/delete) | Own candidates (read) | All | All |
| CV Attachments (`ir.attachment`) | Candidate files (read) | Candidate files (read) | All | All |

> **Note:** Hiring Managers cannot create candidates directly. HR Admin creates candidates and shares them with the Hiring Manager via the Share Candidates wizard.

---

## Application Menu Structure

```
Recruitment (app icon)
├── Dashboard           [HR Admin, Management]
├── Recruitment Requests [HR Admin, Hiring Manager, Management]
├── Candidates          [HR Admin, Hiring Manager, Management]
├── Interview Pipeline  [HR Admin, Hiring Manager, Management]
├── IT Onboarding       [IT Team, HR Admin, Management]
├── Reports             [HR Admin, Management]
│   ├── Recruitment Overview
│   ├── Candidate Pipeline
│   ├── Interview Report
│   └── Hiring Manager Summary
└── Configuration       [HR Admin, Management]
    ├── Interview Round Configuration
    └── Pipeline Stages
```

---

## Data Models

### 1. `recruitment.request` — Hiring Request

The starting point of every recruitment cycle. A Hiring Manager raises a request for one or more vacancies.

**Key Fields**

| Field | Type | Description |
|---|---|---|
| `name` | Char | Auto-generated sequence (e.g. `REC/00001`) |
| `department_id` | Many2one `hr.department` | Department hiring for |
| `job_id` | Many2one `hr.job` | Position / Job title |
| `reporting_manager_id` | Many2one `hr.employee` | Who the new hire will report to |
| `num_vacancies` | Integer | Number of open positions (default 1) |
| `employment_type` | Selection | Permanent / Contract / Temporary / Internship |
| `job_description` | Text | Required |
| `required_skills` | Text | Required |
| `experience_required` | Char | e.g. "3-5 years" |
| `salary_currency` | Selection | AED or INR |
| `salary_range_min/max` | Float | Salary budget |
| `priority` | Selection | Low / Medium / High / Critical |
| `state` | Selection | Workflow state (see below) |
| `user_id` | Many2one `res.users` | Hiring Manager (defaults to current user) |
| `candidate_ids` | One2many | All candidates linked to this request |
| `vacancies_progress` | Char | Computed "X / Y vacancies filled" label |

**Workflow States**

```
draft (New)
  └─► submitted (Submitted to HR)   [action_submit — notifies HR Admins by email]
        └─► hr_review (HR Review)   [action_start_review]
              └─► in_progress       [action_in_progress — requires candidates_shared = True]
                    └─► interview   [action_interview_process]
                          ├─► selected  [auto when selected_count >= num_vacancies]
                          └─► rejected  [action_reject_request wizard]
```

**Vacancy Increase Guard (`write` override)**

When `num_vacancies` is increased while the request is in `interview` or `selected` state, the system validates that enough `interview_completed` candidates exist to fill the new slots. If not, a `UserError` is raised. On a valid increase, `interview_completed` candidates are automatically restored to `interview` state and the request reverts to `interview` if it was `selected`.

---

### 2. `recruitment.candidate` — Candidate

Tracks an individual candidate through the hiring pipeline.

**Key Fields**

| Field | Type | Description |
|---|---|---|
| `name` | Char | Candidate full name |
| `request_id` | Many2one `recruitment.request` | Linked hiring request |
| `stage_id` | Many2one `recruitment.stage` | Kanban pipeline stage |
| `phone_country_code` | Selection | 20+ country codes (default +971 UAE) |
| `phone` | Char | Digits only (validated) |
| `email` | Char | Personal email |
| `current_company` | Char | Current employer |
| `current_designation` | Char | Current job title |
| `total_experience` | Selection | 0–50 years |
| `total_experience_months` | Selection | 1–11 months |
| `relevant_experience` | Selection | 0–50 years |
| `current_salary / expected_salary` | Float | With `salary_currency` |
| `notice_period` | Char | |
| `skills / key_skills / technologies / certifications` | Text | |
| `cv_attachment_ids` | Many2many `ir.attachment` | CV / Resume files |
| `state` | Selection | Candidate workflow state (see below) |
| `priority` | Selection | 0–3 stars (Normal / Good / Very Good / Excellent) |
| `all_rounds_completed` | Boolean (stored) | True when every non-cancelled interview round is completed/selected/passed |
| `all_rounds_passed` | Boolean (stored) | True when all active rounds are in `selected` or `passed` state |
| `interview_ids` | One2many | Interview rounds |
| `final_approval_ids` | One2many | Final approval records |
| `it_onboarding_ids` | One2many | IT onboarding records |

**Candidate Workflow States**

```
[created] → draft
  └─► new          [action_submit — HR reviews CV]
        └─► manager_review   [action_move_to_manager_review — sends to Hiring Manager]
              └─► hm_approved [action_hm_select_candidate — HM approves]
                    └─► interview [action_approve_for_interview — HR schedules rounds]
                          ├─► interview_completed  [auto when vacancies filled by others]
                          ├─► selected             [action_mark_selected]
                          └─► rejected             [action_reject wizard]
```

> Selected candidates float to the top of list views via `sort_priority = 0`.

---

### 3. `recruitment.interview.round` — Interview Round

Represents a single interview round for a candidate. Multiple rounds are pre-created in sequence by the Schedule Interview Wizard.

**Key Fields**

| Field | Type | Description |
|---|---|---|
| `name` | Char | Round name (e.g. "HR Round", "Technical Round") |
| `candidate_id` | Many2one `recruitment.candidate` | |
| `round_order` | Integer | Sequence position (lower = earlier) |
| `interview_date` | Date | |
| `interview_time` | Float | Entered in UAE time (Asia/Dubai) |
| `interview_time_uae` | Char (computed) | Formatted 12-hour AM/PM UAE time |
| `interview_time_ist` | Char (computed) | Auto-calculated IST (UAE +1:30 h) |
| `interview_datetime` | Datetime | Stored in UTC |
| `interviewer_id` | Many2one `res.users` | Primary interviewer |
| `invited_user_ids` | Many2many `res.users` | Additional invited participants |
| `meeting_link` | Char | For online interviews |
| `location_type` | Selection | Online / Offline |
| `venue` | Char | For offline interviews |
| `round_result` | Selection | `selected` / `rejected` |
| `technical_rating` | Selection | 1–5 scale |
| `communication_rating` | Selection | 1–5 scale |
| `overall_rating` | Selection | 1–5 scale |
| `recommendation` | Selection | Strong Yes / Yes / Maybe / No / Strong No |
| `feedback_comments` | Text | Required before unlocking next round |
| `state` | Selection | Round workflow state (see below) |
| `can_schedule` | Boolean (computed) | False if a previous round is still incomplete |
| `is_last_round` | Boolean (computed) | True when no higher-order non-cancelled rounds exist |
| `is_rescheduled` | Boolean | Marked True on rescheduled copies |

**Round States**

```
draft → scheduled → completed → selected / rejected
                  └─► passed  (legacy state, treated same as selected)
                  └─► cancelled
```

**Sequential Enforcement**

Rounds enforce sequential scheduling: `can_schedule` is `False` for any round where a previous round (lower `round_order`) is not yet in `completed`, `selected`, `passed`, `rejected`, or `cancelled` state.

**Reschedule Flow**

Rescheduling a `scheduled` round:
1. Sends cancellation emails — one to the interviewer(s) and one to the candidate.
2. Sets the current round to `cancelled`.
3. Creates a new round with the same data, marked `is_rescheduled = True`, in `scheduled` state.

---

### 4. `recruitment.stage` — Kanban Pipeline Stage

Configurable kanban columns for the candidate pipeline.

| Field | Type | Description |
|---|---|---|
| `name` | Char | Stage label |
| `sequence` | Integer | Display order |
| `stage_type` | Selection | `new` / `draft` / `selected` / `rejected` / `final_evaluation` |
| `fold` | Boolean | Collapsed in kanban |

The `stage_type` is used by code logic (not just display) to find the correct stage record automatically (e.g. newly created candidates land in the `new`-type stage; selected candidates move to the `selected`-type stage).

---

### 5. `recruitment.final.approval` — Final Approval Details

Created after a candidate is selected. Captures offer and onboarding details.

**Key Fields**

| Field | Type | Description |
|---|---|---|
| `candidate_id` | Many2one `recruitment.candidate` | |
| `onboarding_date` | Date | Joining / onboarding date (required before notifying IT) |
| `ctc_currency` | Selection | AED / INR |
| `annual_ctc` | Float | Agreed CTC |
| `reporting_manager_id` | Many2one `hr.employee` | |
| `approval_remarks` | Text | |
| `offer_notes` | Text | Offer preparation notes |
| `state` | Selection | `draft` → `it_notified` → `onboarding_ready` → `closed` |
| `it_onboarding_id` | Many2one `recruitment.it.onboarding` | Created on IT notification |

**Workflow**

1. HR sets `onboarding_date` and clicks **Notify IT Team**.
2. System creates an `recruitment.it.onboarding` record and emails all IT Team users.
3. State moves to `it_notified`.
4. When IT completes the checklist and sends the onboarding-ready notification, state moves to `onboarding_ready`.
5. HR clicks **Close** to finalize.

---

### 6. `recruitment.it.onboarding` — IT Onboarding Checklist

A 5-step checklist filled by the IT Team after receiving a notification for a selected candidate.

**5 Steps**

| Step | Boolean Flag | Required Before Completing |
|---|---|---|
| 1. Email Account | `email_created` | `official_email` must be filled |
| 2. Odoo Account | `odoo_account_created` | `odoo_username` must be filled |
| 3. Wave Account | `wave_account_created` | None (optional username) |
| 4. Hardware & IT Assets | `laptop_arranged` | None |
| 5. Documentation | `setup_docs_shared` | At least one file in `document_ids` |

**`all_tasks_done`** is `True` when steps 1, 2, 4, and 5 are all checked (Wave account is tracked but not mandatory for this flag).

**States:** `pending` → `in_progress` → `completed`

**Send Onboarding Ready Notification**

Once `all_tasks_done = True`, the IT Team clicks **Send Onboarding Ready Notification**, which opens a wizard to confirm recipients (candidate personal email + HR Admins). On confirm:
- Sends the `onboarding_ready` email template.
- Sets `notification_sent = True`.
- Updates the linked `final_approval_id.state` to `onboarding_ready`.

---

### 7. `recruitment.dashboard` — Dashboard

Singleton model with computed statistics displayed to HR Admin and Management.

Stats shown:
- Total recruitment requests (by state breakdown)
- Total candidates (by state breakdown)
- IT Onboarding records (by state breakdown)

---

## Wizards

| Wizard Model | Purpose |
|---|---|
| `recruitment.add.candidate.wizard` | Add a new candidate to a request |
| `recruitment.share.candidates.wizard` | HR shares candidate profiles with the Hiring Manager; sets `candidates_shared = True` on the request |
| `recruitment.send.manager.wizard` | Move a candidate to `manager_review` and assign a Hiring Manager |
| `recruitment.schedule.interview.wizard` | Pre-creates all interview rounds for a candidate in draft state |
| `recruitment.send.invitation.wizard` | Send interview invitation email to candidate and invited users |
| `recruitment.final.selection.wizard` | Final selection confirmation before marking request as selected |
| `recruitment.set.to.new.wizard` | Reset a candidate back to `new` state |
| `recruitment.request.reset.wizard` | Reset a request back to `draft` state |
| `recruitment.request.reject.wizard` | Reject a request with a reason |
| `recruitment.reject.wizard` | Reject a candidate (from candidate or interview round) |
| `recruitment.candidate.send.hm.wizard` | Send a candidate to fill a vacancy in a different HM's request |
| `recruitment.it.onboarding.send.wizard` | Confirm recipients and send onboarding-ready notification |

---

## Email Templates (12)

| Template XML ID | Trigger |
|---|---|
| `email_template_request_submitted` | Request submitted → HR Admins |
| `email_template_candidate_added` | Candidate added to a request |
| `email_template_candidate_to_review` | Candidate moved to HR review |
| `email_template_candidate_approved` | Candidate approved for interview |
| `email_template_interview_invitation` | Interview invitation sent |
| `email_template_interview_passed` | Round passed → HR Admins + Hiring Managers |
| `email_template_candidate_rejected` | Candidate rejected |
| `email_template_candidate_selected` | Candidate selected → specific Hiring Manager |
| `email_template_hm_candidate_selected` | HM approves candidate → HR Admins |
| `email_template_interview_cancelled` | Round rescheduled → interviewer(s) |
| `email_template_it_onboarding_request` | IT team notified of onboarding |
| `email_template_onboarding_ready` | IT setup complete → candidate + HR Admins |

> All emails suppress chatter messages (mail.message is deleted after send) to keep the chatter clean.

---

## Frontend Assets

| File | Purpose |
|---|---|
| `static/src/css/recruitment_gk.css` | Custom styles for forms and kanban |
| `static/src/js/priority_no_autosave.js` | Prevents auto-save when clicking priority stars |
| `static/src/js/cv_attachment_download.js` | Custom CV download button widget |
| `static/src/js/float_time_ampm.js` | 12-hour AM/PM input widget for `interview_time` |
| `static/src/xml/cv_attachment_download.xml` | OWL template for CV download widget |
| `static/src/xml/float_time_ampm.xml` | OWL template for AM/PM time widget |

---

## Full Workflow Summary

```
[Hiring Manager]
  1. Create Recruitment Request (draft)
  2. Submit Request → state: submitted (email to HR Admins)

[HR Admin]
  3. Review Request → state: hr_review
  4. Add Candidates via wizard
  5. Share Candidates with Hiring Manager → state: in_progress
  6. Move to Interview Process → state: interview

[Hiring Manager]
  7. Review shared candidates
  8. Approve candidate → state: hm_approved (email to HR Admins)

[HR Admin]
  9. Schedule Interview Rounds (wizard creates all rounds in draft)
  10. Start Round 1 → draft → scheduled
  11. Conduct interview → mark Completed
  12. Pass to next round (requires feedback_comments)
      └─► Repeat for each round
  13. After all rounds: Select or Reject Candidate

[System — on Select Candidate]
  14. Candidate state → selected
  15. When selected_count >= num_vacancies: Request state → selected
  16. Remaining interview/hm_approved candidates → interview_completed

[HR Admin]
  17. Open Final Approval Details
  18. Fill onboarding date, CTC, reporting manager
  19. Click "Notify IT Team"
      └─► Creates IT Onboarding record
      └─► Emails IT Team

[IT Team]
  20. Complete 5-step IT checklist:
      ├─ Email Account
      ├─ Odoo Account
      ├─ Wave Account
      ├─ Hardware & IT Assets
      └─ Documentation
  21. Click "Send Onboarding Ready Notification"
      └─► Emails candidate personal email + HR Admins
      └─► Final Approval state → onboarding_ready

[HR Admin]
  22. Prepare offer
  23. Close Final Approval → state: closed
```

---

## Configuration

### Interview Round Templates (`recruitment.interview.config`)

Pre-defined round templates (e.g. "HR Round", "Technical Round", "Management Round") that are loaded as defaults in the Schedule Interview Wizard. Managed under **Configuration → Interview Round Configuration**.

### Pipeline Stages (`recruitment.stage`)

Kanban columns for the Candidate Pipeline. Managed under **Configuration → Pipeline Stages**. The `stage_type` field must be set correctly for system logic to work:

- `new` — landing stage for newly added candidates
- `draft` — after first review
- `selected` — final selected stage
- `rejected` — rejected candidates
- `final_evaluation` — stage after all interview rounds are passed (before final decision)

---

## Sequence

Recruitment requests receive an auto-incremented reference number from the `recruitment.request` IR sequence (e.g. `REC/2024/00001`). The sequence is assigned on `action_submit` — draft requests show "New".
