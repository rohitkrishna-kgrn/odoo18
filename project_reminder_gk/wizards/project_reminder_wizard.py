from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ProjectReminderWizard(models.TransientModel):
    _name = 'project.reminder.wizard'
    _description = 'Add Project Reminder Wizard'

    project_id = fields.Many2one('project.project', string='Project', required=True)
    sale_order_id = fields.Many2one(
        'sale.order', string='Sale Order',
        related='project_id.sale_order_id', readonly=True,
    )
    customer_id = fields.Many2one(
        'res.partner', string='Project / Customer',
        related='project_id.partner_id', readonly=True,
    )
    sale_order_line_id = fields.Many2one(
        'sale.order.line', string='Sale Order Line',
        domain="[('order_id', '=', sale_order_id)]",
    )
    engagement_start = fields.Date(
        string='Engagement Start',
        related='sale_order_line_id.engagement_start', readonly=True,
    )
    engagement_end = fields.Date(
        string='Engagement End',
        related='sale_order_line_id.engagement_end', readonly=True,
    )
    reminder_type = fields.Selection([
        ('yearly', 'Yearly Reminder'),
        ('half_yearly', 'Half-Yearly Reminder'),
        ('quarterly', 'Quarterly Reminder'),
        ('monthly', 'Monthly Reminder'),
    ], string='Reminder Type', required=True)
    yearly_frequency = fields.Selection([
        ('1', 'One Reminder Per Year'),
        ('2', 'Two Reminders Per Year'),
        ('3', 'Three Reminders Per Year'),
    ], string='Yearly Frequency', default='1')
    remarks = fields.Text(string='Remarks')
    line_ids = fields.One2many('project.reminder.wizard.line', 'wizard_id', string='Reminder Dates')

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if not self.project_id:
            return
        sol = self.env['sale.order.line'].search(
            [('project_id', '=', self.project_id.id)], limit=1
        )
        if sol:
            self.sale_order_line_id = sol

    @api.onchange('sale_order_line_id', 'reminder_type', 'yearly_frequency')
    def _onchange_generate_lines(self):
        self.line_ids = [(5, 0, 0)]
        if not self.sale_order_line_id or not self.reminder_type:
            return
        start = self.engagement_start
        end = self.engagement_end
        if not start or not end:
            return
        self.line_ids = [(0, 0, v) for v in self._generate_line_vals(start, end)]

    def _generate_line_vals(self, start, end):
        lines = []
        rtype = self.reminder_type
        freq = int(self.yearly_frequency or '1')
        start_year = start.year
        end_year = end.year

        if rtype == 'yearly':
            for year in range(start_year, end_year + 1):
                for i in range(freq):
                    label = str(year) if freq == 1 else f"{year} – Reminder {i + 1}"
                    lines.append({'period_label': label, 'reminder_date': False, 'sequence': len(lines) + 1})

        elif rtype == 'half_yearly':
            start_half = 1 if start.month <= 6 else 2
            end_half = 1 if end.month <= 6 else 2
            year = start.year
            h = start_half
            while (year, h) <= (end.year, end_half):
                lines.append({'period_label': f"H{h} {year}", 'reminder_date': False, 'sequence': len(lines) + 1})
                if h == 1:
                    h = 2
                else:
                    h = 1
                    year += 1

        elif rtype == 'quarterly':
            start_quarter = (start.month - 1) // 3 + 1
            end_quarter = (end.month - 1) // 3 + 1
            year = start.year
            q = start_quarter
            while (year, q) <= (end.year, end_quarter):
                lines.append({'period_label': f"Q{q} {year}", 'reminder_date': False, 'sequence': len(lines) + 1})
                if q < 4:
                    q += 1
                else:
                    q = 1
                    year += 1

        elif rtype == 'monthly':
            current = start.replace(day=1)
            end_month = end.replace(day=1)
            while current <= end_month:
                lines.append({
                    'period_label': current.strftime('%B %Y'),
                    'reminder_date': False,
                    'sequence': len(lines) + 1,
                })
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)

        return lines

    def _get_period_date_range(self, period_label):
        """Delegate to the shared helper on project.reminder.line."""
        return self.env['project.reminder.line']._get_period_date_range(period_label, self.reminder_type)

    def action_confirm(self):
        self.ensure_one()
        if not self.sale_order_line_id:
            raise ValidationError(_(
                "A Sale Order Line is required to schedule reminders. "
                "Please ensure the project has a linked Sale Order with order lines."
            ))
        if not self.line_ids:
            raise ValidationError(_(
                "No reminder lines generated. "
                "Select a Sale Order Line and Reminder Type first."
            ))

        errors = []
        eng_start = self.engagement_start
        eng_end = self.engagement_end

        for line in self.line_ids:
            # Missing date
            if not line.reminder_date:
                errors.append(
                    _("• Period '%s': Reminder Date is required.", line.period_label)
                )
                continue

            # Date must fall within the period range
            period_start, period_end = self._get_period_date_range(line.period_label)
            if period_start and period_end:
                if not (period_start <= line.reminder_date <= period_end):
                    errors.append(_(
                        "• Period '%(period)s': %(date)s is outside the valid range "
                        "(%(start)s – %(end)s).",
                        period=line.period_label,
                        date=line.reminder_date.strftime('%d-%b-%Y'),
                        start=period_start.strftime('%d-%b-%Y'),
                        end=period_end.strftime('%d-%b-%Y'),
                    ))
                    continue

            # Date must also fall within the engagement window
            if eng_start and line.reminder_date < eng_start:
                errors.append(_(
                    "• Period '%(period)s': %(date)s is before the engagement start "
                    "(%(eng)s).",
                    period=line.period_label,
                    date=line.reminder_date.strftime('%d-%b-%Y'),
                    eng=eng_start.strftime('%d-%b-%Y'),
                ))
            elif eng_end and line.reminder_date > eng_end:
                errors.append(_(
                    "• Period '%(period)s': %(date)s is after the engagement end "
                    "(%(eng)s).",
                    period=line.period_label,
                    date=line.reminder_date.strftime('%d-%b-%Y'),
                    eng=eng_end.strftime('%d-%b-%Y'),
                ))

        if errors:
            raise ValidationError(
                _("Reminder date must fall within the selected period and "
                  "engagement date range. The following lines have invalid dates:\n\n")
                + '\n'.join(errors)
            )

        schedule = self.env['project.reminder.schedule'].create({
            'project_id': self.project_id.id,
            'sale_order_line_id': self.sale_order_line_id.id,
            'reminder_type': self.reminder_type,
            'yearly_frequency': self.yearly_frequency,
            'remarks': self.remarks,
        })

        self.env['project.reminder.line'].create([
            {
                'schedule_id': schedule.id,
                'reminder_date': line.reminder_date,
                'state': 'scheduled',
            }
            for line in self.line_ids
        ])

        schedule.write({'state': 'scheduled'})
        schedule.message_post(body=_("Reminder schedule activated via wizard."))
        return {'type': 'ir.actions.act_window_close'}


class ProjectReminderWizardLine(models.TransientModel):
    _name = 'project.reminder.wizard.line'
    _description = 'Project Reminder Wizard Line'
    _order = 'sequence asc, id asc'

    wizard_id = fields.Many2one('project.reminder.wizard', ondelete='cascade', required=True)
    period_label = fields.Char(string='Period', readonly=True)
    reminder_date = fields.Date(string='Reminder Date', required=True)
    sequence = fields.Integer(default=10)

    # Computed range for the client-side date-picker restriction.
    # = intersection of the period's own range and the engagement dates.
    period_date_min = fields.Date(
        compute='_compute_period_date_range', string='Period Min Date',
    )
    period_date_max = fields.Date(
        compute='_compute_period_date_range', string='Period Max Date',
    )

    @api.depends(
        'period_label',
        'wizard_id.reminder_type',
        'wizard_id.engagement_start',
        'wizard_id.engagement_end',
    )
    def _compute_period_date_range(self):
        for line in self:
            p_start, p_end = False, False
            if line.wizard_id and line.period_label and line.wizard_id.reminder_type:
                p_start, p_end = line.wizard_id._get_period_date_range(line.period_label)

            eng_start = line.wizard_id.engagement_start if line.wizard_id else False
            eng_end = line.wizard_id.engagement_end if line.wizard_id else False

            if p_start and eng_start:
                p_start = max(p_start, eng_start)
            elif eng_start:
                p_start = eng_start

            if p_end and eng_end:
                p_end = min(p_end, eng_end)
            elif eng_end:
                p_end = eng_end

            line.period_date_min = p_start or False
            line.period_date_max = p_end or False

    @api.onchange('reminder_date')
    def _onchange_validate_reminder_date(self):
        if not self.reminder_date or not self.period_label:
            return
        p_start, p_end = False, False
        if self.wizard_id and self.wizard_id.reminder_type:
            p_start, p_end = self.wizard_id._get_period_date_range(self.period_label)
        eng_start = self.wizard_id.engagement_start if self.wizard_id else False
        eng_end = self.wizard_id.engagement_end if self.wizard_id else False
        if p_start and eng_start:
            p_start = max(p_start, eng_start)
        if p_end and eng_end:
            p_end = min(p_end, eng_end)

        out_of_range = (p_start and self.reminder_date < p_start) or \
                       (p_end and self.reminder_date > p_end)
        if out_of_range:
            self.reminder_date = False  # clear the invalid date
            range_info = ''
            if p_start and p_end:
                range_info = (
                    f" Valid range for '{self.period_label}': "
                    f"{p_start.strftime('%d-%b-%Y')} – {p_end.strftime('%d-%b-%Y')}."
                )
            return {
                'warning': {
                    'title': _('Invalid Reminder Date'),
                    'message': _(
                        'Reminder date must fall within the selected period '
                        'and engagement date range.'
                    ) + range_info,
                }
            }

    @api.constrains('reminder_date')
    def _check_reminder_date_in_period(self):
        for line in self:
            if not line.reminder_date or not line.period_label or not line.wizard_id:
                continue
            period_start, period_end = line.wizard_id._get_period_date_range(line.period_label)
            if period_start and period_end and not (period_start <= line.reminder_date <= period_end):
                raise ValidationError(_(
                    "The selected Reminder Date (%(date)s) does not fall within the specified "
                    "Period '%(period)s' (%(start)s – %(end)s). "
                    "Please select a date within the valid Period range.",
                    date=line.reminder_date.strftime('%d-%b-%Y'),
                    period=line.period_label,
                    start=period_start.strftime('%d-%b-%Y'),
                    end=period_end.strftime('%d-%b-%Y'),
                ))
