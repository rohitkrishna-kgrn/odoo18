import base64
import io
import logging
from datetime import timedelta

from odoo import models, fields, api
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)

# Any team member below this figure is a red flag on the report.
COMPLIANCE_THRESHOLD = 80.0

_TH = ("padding:6px 8px;text-align:left;border:1px solid #ccc;"
       "background:#F15D22;color:#ffffff;font-weight:bold;")
_TD = "padding:6px 8px;border:1px solid #ccc;vertical-align:top;"


class TimesheetComplianceReport(models.Model):
    """One record per manager per week: how many days each of that manager's
    people filed a timesheet on, against the days they were actually expected
    to work.

    Teams come straight from the Manager field on the Employee form
    (hr.employee.parent_id). A manager's team is their direct reports - the
    employees whose Manager field points at them - and the report is emailed
    to that manager alone. There is no consolidated all-teams email.

    Note that ten of the managers in this database are their own manager
    (parent_id = own id), so they legitimately appear inside their own team
    list. That is the Manager field read literally, which is what was asked
    for, and it has the useful side effect that a manager's own compliance is
    visible somewhere. Employees with no Manager set are out of scope and
    appear on no report.

    Expected working days come from the employee's own resource calendar
    (Mon-Fri here), minus public holidays (`public.holiday`) and minus
    approved full-day leave (`leave.request`). A half-day leave still counts
    as a working day - the employee was in for half of it.
    """
    _name = 'timesheet.compliance.report'
    _description = 'Weekly Timesheet Compliance Report'
    _order = 'week_start desc, manager_name'

    name = fields.Char(compute='_compute_name', store=True)
    week_start = fields.Date(string='Week Starting (Mon)', readonly=True, index=True)
    week_end = fields.Date(string='Week Ending (Sun)', readonly=True)
    generated_date = fields.Datetime(default=fields.Datetime.now, readonly=True)

    manager_id = fields.Many2one('hr.employee', string='Manager', readonly=True, index=True)
    # Snapshotted so a historical report still reads correctly after a rename.
    manager_name = fields.Char(string='Manager Name', readonly=True)
    manager_user_id = fields.Many2one('res.users', string='Manager User', readonly=True)
    manager_email = fields.Char(string='Sent To', readonly=True)

    member_count = fields.Integer(string='Team Members', readonly=True)
    flagged_count = fields.Integer(
        string='Below Threshold', readonly=True,
        help="Team members who filed timesheets on less than 80%% of the days "
             "they were expected to work that week.")
    expected_days_total = fields.Integer(string='Expected Days', readonly=True)
    logged_days_total = fields.Integer(string='Days With Entries', readonly=True)
    compliance_rate = fields.Float(string='Team Compliance %', readonly=True)

    email_sent = fields.Boolean(readonly=True)
    report_file = fields.Binary(string='Report (xlsx)', readonly=True, attachment=True)
    report_filename = fields.Char(readonly=True)
    line_ids = fields.One2many(
        'timesheet.compliance.report.line', 'report_id', readonly=True)

    @api.depends('manager_name', 'week_start', 'week_end')
    def _compute_name(self):
        for rec in self:
            if rec.week_start and rec.week_end:
                rec.name = "%s - Week %s to %s" % (
                    rec.manager_name or 'Unassigned',
                    rec.week_start.strftime('%d %b'),
                    rec.week_end.strftime('%d %b %Y'))
            else:
                rec.name = "Timesheet Compliance - Draft"

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    @api.model
    def _cron_generate_weekly_report(self):
        """Fired every Monday morning by ir.cron (see data/ir_cron.xml).

        Reports on the week that has just finished - the Monday-to-Sunday
        block before today - so a Monday run always covers a complete week.
        Deriving it from weekday() rather than 'exactly 7 days ago' means a
        cron that misfires and catches up on Tuesday still reports the same
        week instead of a shifted one."""
        today = fields.Date.context_today(self)
        last_monday = today - timedelta(days=today.weekday() + 7)
        return self._generate_for_week(last_monday, send_email=True)

    @api.model
    def _managers(self):
        """Active employees who have at least one active direct report.

        Read straight off the Manager field - no hierarchy walking, so the
        self-referencing parent_id records in this database are harmless."""
        employees = self.env['hr.employee'].sudo().search(
            [('parent_id', '!=', False)])
        managers = employees.mapped('parent_id').filtered('active')
        return managers.sorted('name')

    @api.model
    def _generate_for_week(self, week_date, send_email=True, managers=None):
        """Build one report per manager for the week containing `week_date`.

        Called by the Monday cron with send_email=True, and by the
        "Generate for a Week" wizard (which defaults to False so the numbers
        can be checked on screen before anything is mailed). Returns the
        recordset of reports created."""
        week_date = fields.Date.to_date(week_date)
        week_start = week_date - timedelta(days=week_date.weekday())
        week_end = week_start + timedelta(days=6)
        week_dates = [week_start + timedelta(days=i) for i in range(7)]

        if managers is None:
            managers = self._managers()
        if not managers:
            _logger.info("Timesheet Compliance: no employee has anyone else's "
                         "Manager field pointing at them; nothing to report.")
            return self.browse()

        # Week-wide lookups computed once and sliced per manager.
        holidays = self._holiday_dates(week_start, week_end)
        leaves = self._full_day_leave_dates(week_start, week_end)
        logged = self._logged_dates(week_start, week_end)

        reports = self.browse()
        for manager in managers:
            members = self.env['hr.employee'].sudo().search(
                [('parent_id', '=', manager.id)])
            if not members:
                continue

            line_vals = []
            for employee in members:
                line_vals.append((0, 0, self._member_values(
                    employee, week_dates, holidays, leaves, logged)))

            expected_total = sum(v[2]['expected_days'] for v in line_vals)
            logged_total = sum(v[2]['logged_days'] for v in line_vals)
            user = manager.user_id

            report = self.create({
                'week_start': week_start,
                'week_end': week_end,
                'manager_id': manager.id,
                'manager_name': manager.name or '',
                'manager_user_id': user.id or False,
                'manager_email': user.email or manager.work_email or '',
                'member_count': len(line_vals),
                'flagged_count': sum(1 for v in line_vals if v[2]['is_flagged']),
                'expected_days_total': expected_total,
                'logged_days_total': logged_total,
                'compliance_rate': (
                    100.0 * logged_total / expected_total) if expected_total else 0.0,
                'line_ids': line_vals,
            })
            report.write({
                'report_file': report._render_xlsx(),
                'report_filename': "Timesheet_Compliance_%s_%s.xlsx" % (
                    (manager.name or 'team').replace(' ', '_')[:40],
                    week_start.strftime('%Y_%m_%d')),
            })
            if send_email:
                report._send_email()
            reports |= report

        return reports

    @api.model
    def _member_values(self, employee, week_dates, holidays, leaves, logged):
        """The compliance figures for one employee over one week."""
        workdays = self._working_weekdays(employee)
        leave_dates = leaves.get(employee.user_id.id, set())

        expected = [
            d for d in week_dates
            if d.weekday() in workdays
            and d not in holidays
            and d not in leave_dates
        ]
        filed = logged.get(employee.id, set())
        # Only entries landing on a day the person was expected in count.
        # Filing on a Saturday does not cover a missed Tuesday.
        covered = sorted(d for d in expected if d in filed)
        missing = sorted(d for d in expected if d not in filed)
        rate = (100.0 * len(covered) / len(expected)) if expected else 100.0

        return {
            'employee_id': employee.id,
            'employee_name': employee.name or '',
            'department_id': employee.department_id.id or False,
            'department_name': employee.department_id.name or 'No Department',
            'expected_days': len(expected),
            'logged_days': len(covered),
            'leave_days': len([d for d in week_dates
                               if d.weekday() in workdays and d in leave_dates]),
            'holiday_days': len([d for d in week_dates
                                 if d.weekday() in workdays and d in holidays]),
            'compliance_rate': rate,
            # Someone with no expected days at all (a full week of leave or
            # holiday) is never a red flag - there was nothing to file.
            'is_flagged': bool(expected) and rate < COMPLIANCE_THRESHOLD,
            'missing_dates': ', '.join(d.strftime('%a %d %b') for d in missing),
        }

    @api.model
    def _working_weekdays(self, employee):
        """Set of weekday numbers (0=Mon) the employee is scheduled to work,
        from their own resource calendar. Falls back to Mon-Fri when an
        employee has no calendar assigned at all."""
        calendar = employee.resource_calendar_id or self.env.company.resource_calendar_id
        if not calendar:
            return {0, 1, 2, 3, 4}
        days = {int(a.dayofweek) for a in calendar.attendance_ids if a.dayofweek}
        return days or {0, 1, 2, 3, 4}

    @api.model
    def _holiday_dates(self, date_from, date_to):
        holidays = self.env['public.holiday'].sudo().search([
            ('date', '>=', date_from), ('date', '<=', date_to),
        ])
        return {h.date for h in holidays}

    @api.model
    def _full_day_leave_dates(self, date_from, date_to):
        """{user_id: {date, ...}} of approved, full-day leave overlapping the
        week. Half-day leave is deliberately excluded - the employee was in for
        part of that day and is still expected to file a timesheet for it."""
        leaves = self.env['leave.request'].sudo().search([
            ('state', '=', 'approved'),
            ('is_half_day', '=', False),
            ('start_date', '<=', date_to),
            '|', ('end_date', '>=', date_from), ('end_date', '=', False),
        ])
        result = {}
        for leave in leaves:
            start = leave.start_date
            end = leave.end_date or leave.start_date
            if not start:
                continue
            day = max(start, date_from)
            last = min(end, date_to)
            while day <= last:
                result.setdefault(leave.user_id.id, set()).add(day)
                day += timedelta(days=1)
        return result

    @api.model
    def _logged_dates(self, date_from, date_to):
        """{employee_id: {date, ...}} - the days each employee actually has a
        timesheet entry on. Only project lines with real time on them count;
        a zero-hour line is not a filed day."""
        lines = self.env['account.analytic.line'].sudo().search_read(
            [('project_id', '!=', False),
             ('date', '>=', date_from), ('date', '<=', date_to),
             ('unit_amount', '>', 0),
             ('employee_id', '!=', False)],
            ['employee_id', 'date'])
        result = {}
        for line in lines:
            result.setdefault(line['employee_id'][0], set()).add(
                fields.Date.to_date(line['date']))
        return result

    # ------------------------------------------------------------------
    # Presentation
    # ------------------------------------------------------------------

    def _sorted_lines(self):
        """Worst compliance first, so the people needing a nudge are at the
        top of the manager's email."""
        self.ensure_one()
        return self.line_ids.sorted(lambda l: (l.compliance_rate, l.employee_name))

    def _render_email_html(self):
        self.ensure_one()

        rows = []
        for line in self._sorted_lines():
            flagged = line.is_flagged
            colour = '#a94442' if flagged else '#3c763d'
            bg = "background:#F9E2E2;" if flagged else ""
            rows.append(
                f"<tr style='{bg}'>"
                f"<td style='{_TD}'>{html_escape(line.employee_name)}"
                f"{' &#9873;' if flagged else ''}</td>"
                f"<td style='{_TD}'>{html_escape(line.department_name or '')}</td>"
                f"<td style='{_TD}text-align:center;'>{line.logged_days} / {line.expected_days}</td>"
                f"<td style='{_TD}text-align:center;color:{colour};font-weight:bold;'>"
                f"{line.compliance_rate:.0f}%</td>"
                f"<td style='{_TD}'>{html_escape(line.missing_dates or '')}</td>"
                f"</tr>")

        member_table = (
            f"<table style='border-collapse:collapse;width:100%;font-size:13px;'>"
            f"<tr><th style='{_TH}'>Team Member</th><th style='{_TH}'>Department</th>"
            f"<th style='{_TH}text-align:center;'>Days Filed / Expected</th>"
            f"<th style='{_TH}text-align:center;'>Compliance</th>"
            f"<th style='{_TH}'>Days Missing</th></tr>"
            f"{''.join(rows)}</table>")

        if self.flagged_count:
            headline = (
                f"<p style='color:#a94442;font-weight:bold;font-size:14px;'>"
                f"&#9873; {self.flagged_count} of your {self.member_count} team "
                f"member(s) filed timesheets on less than 80% of their expected "
                f"working days.</p>")
        else:
            headline = (
                "<p style='color:#3c763d;font-weight:bold;font-size:14px;'>"
                "&#10003; Every member of your team met the 80% threshold "
                "this week.</p>")

        return f"""
            <div style="font-family: Arial, sans-serif; font-size: 13px; color: #333;">
                <p>Dear {html_escape(self.manager_name or 'Manager')},</p>
                <p>
                    Timesheet compliance for your team for the week
                    <b>{self.week_start.strftime('%d %b')} &ndash; {self.week_end.strftime('%d %b %Y')}</b>:
                    <b>{self.logged_days_total}</b> of <b>{self.expected_days_total}</b>
                    expected working days were filed across
                    {self.member_count} team member(s)
                    &mdash; a team compliance of <b>{self.compliance_rate:.0f}%</b>.
                </p>
                {headline}
                {member_table}
                <p style="margin-top:18px;color:#666;font-size:12px;">
                    Your team is taken from the Manager field on the Employee
                    form. Expected working days come from each employee's
                    working schedule, less public holidays and approved
                    full-day leave. The attached spreadsheet has the same
                    detail.
                </p>
                <p>Regards,<br/>Timesheet Compliance Report (Automated)</p>
            </div>
        """

    def _send_email(self):
        """Email this report to its manager and nobody else."""
        self.ensure_one()
        if not self.manager_email:
            _logger.info(
                "Timesheet Compliance: manager %s has no email address, "
                "report %s saved in Odoo only.", self.manager_name, self.name)
            return False

        attachment = self.env['ir.attachment'].create({
            'name': self.report_filename,
            'datas': self.report_file,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        mail = self.env['mail.mail'].sudo().create({
            'subject': "Your Team's Timesheet Compliance - Week %s to %s" % (
                self.week_start.strftime('%d %b'),
                self.week_end.strftime('%d %b %Y')),
            'body_html': self._render_email_html(),
            'email_to': self.manager_email,
            'attachment_ids': [(6, 0, attachment.ids)],
            'auto_delete': False,
        })
        mail.send()
        self.email_sent = mail.state == 'sent'
        if mail.state != 'sent':
            _logger.warning(
                "Timesheet Compliance %s: email to %s failed (state=%s): %s",
                self.name, self.manager_email, mail.state, mail.failure_reason or '')
        return self.email_sent

    def _render_xlsx(self):
        self.ensure_one()
        import xlsxwriter

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Compliance')

        fmt_title = workbook.add_format({'bold': True, 'font_size': 12})
        fmt_header = workbook.add_format({
            'bold': True, 'bg_color': '#F15D22', 'font_color': '#ffffff',
            'border': 1, 'valign': 'vcenter', 'text_wrap': True})
        fmt_text = workbook.add_format({'border': 1, 'valign': 'top', 'text_wrap': True})
        fmt_int = workbook.add_format({'border': 1, 'valign': 'top', 'align': 'center'})
        fmt_pct = workbook.add_format({
            'border': 1, 'valign': 'top', 'align': 'center', 'num_format': '0"%"'})
        fmt_pct_bad = workbook.add_format({
            'border': 1, 'valign': 'top', 'align': 'center', 'num_format': '0"%"',
            'font_color': '#a94442', 'bold': True, 'bg_color': '#F9E2E2'})
        fmt_total = workbook.add_format({
            'bold': True, 'border': 1, 'bg_color': '#FBD9C4'})

        headers = ['Team Member', 'Department', 'Days With Entries',
                   'Expected Working Days', 'Compliance %', 'Red Flag',
                   'Leave Days', 'Holidays', 'Days Missing']
        widths = [28, 30, 16, 18, 13, 10, 11, 10, 45]

        sheet.merge_range(
            0, 0, 0, len(headers) - 1,
            "%s - team timesheet compliance, week %s to %s" % (
                self.manager_name or '',
                self.week_start.strftime('%d %b %Y'),
                self.week_end.strftime('%d %b %Y')),
            fmt_title)

        for c, (label, width) in enumerate(zip(headers, widths)):
            sheet.write(2, c, label, fmt_header)
            sheet.set_column(c, c, width)
        sheet.freeze_panes(3, 0)

        r = 3
        for line in self._sorted_lines():
            sheet.write(r, 0, line.employee_name or '', fmt_text)
            sheet.write(r, 1, line.department_name or '', fmt_text)
            sheet.write_number(r, 2, line.logged_days, fmt_int)
            sheet.write_number(r, 3, line.expected_days, fmt_int)
            sheet.write_number(r, 4, line.compliance_rate,
                               fmt_pct_bad if line.is_flagged else fmt_pct)
            sheet.write(r, 5, 'YES' if line.is_flagged else '', fmt_text)
            sheet.write_number(r, 6, line.leave_days, fmt_int)
            sheet.write_number(r, 7, line.holiday_days, fmt_int)
            sheet.write(r, 8, line.missing_dates or '', fmt_text)
            r += 1

        sheet.write(r, 0, 'Team Total', fmt_total)
        sheet.write(r, 1, '', fmt_total)
        sheet.write_number(r, 2, self.logged_days_total, fmt_total)
        sheet.write_number(r, 3, self.expected_days_total, fmt_total)
        sheet.write_number(r, 4, self.compliance_rate, fmt_total)
        for c in range(5, len(headers)):
            sheet.write(r, c, '', fmt_total)

        sheet.autofilter(2, 0, r - 1, len(headers) - 1)
        workbook.close()
        output.seek(0)
        return base64.b64encode(output.read())

    def action_send_email_now(self):
        """Manual resend from the report form - goes to the manager only."""
        for report in self:
            report._send_email()
        return True


class TimesheetComplianceReportLine(models.Model):
    _name = 'timesheet.compliance.report.line'
    _description = 'Weekly Timesheet Compliance Report Line'
    _order = 'compliance_rate, employee_name'

    report_id = fields.Many2one(
        'timesheet.compliance.report', required=True, ondelete='cascade', index=True)
    week_start = fields.Date(related='report_id.week_start', store=True)
    manager_id = fields.Many2one(related='report_id.manager_id', store=True)
    employee_id = fields.Many2one('hr.employee', readonly=True)
    # Names are snapshotted alongside the m2o so a historical report still reads
    # correctly after someone is renamed or moved to another department.
    employee_name = fields.Char(readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    department_name = fields.Char(string='Department Name', readonly=True)
    expected_days = fields.Integer(string='Expected Working Days', readonly=True)
    logged_days = fields.Integer(string='Days With Entries', readonly=True)
    leave_days = fields.Integer(string='Leave Days', readonly=True)
    holiday_days = fields.Integer(string='Holidays', readonly=True)
    compliance_rate = fields.Float(string='Compliance %', readonly=True)
    is_flagged = fields.Boolean(string='Red Flag', readonly=True)
    missing_dates = fields.Char(string='Days Missing', readonly=True)
