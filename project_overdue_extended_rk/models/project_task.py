from odoo import models, fields, api


class ProjectTask(models.Model):
    _inherit = 'project.task'

    overdue_days = fields.Integer(
        string='Overdue Days',
        compute='_compute_overdue_category',
    )

    overdue_category = fields.Selection(
        selection=[
            ('none', 'Not Overdue'),
            ('lt30', 'Overdue < 30 days'),
            ('30_60', 'Overdue 30–60 days'),
            ('60_90', 'Overdue 60–90 days'),
            ('gt90', 'Overdue > 90 days'),
            ('done', 'Done'),
        ],
        string='Overdue Category',
        compute='_compute_overdue_category',
    )

    @api.depends('date_deadline', 'stage_id.fold', 'state_additional')
    def _compute_overdue_category(self):
        today = fields.Date.today()   # returns datetime.date, always
        for task in self:
            # Tasks in a folded (done) stage or marked completed carry no overdue status
            is_done = (
                task.state_additional == 'completed'
                or (task.stage_id and task.stage_id.fold)
            )
            if is_done:
                task.overdue_days = 0
                task.overdue_category = 'done'
                continue

            if not task.date_deadline:
                task.overdue_days = 0
                task.overdue_category = 'none'
                continue

            # date_deadline may be a datetime.datetime on some Odoo builds;
            # fields.Date.to_date() normalises both str and datetime → date.
            deadline = fields.Date.to_date(task.date_deadline)
            delta = (today - deadline).days
            task.overdue_days = max(0, delta)

            if delta <= 0:
                task.overdue_category = 'none'
            elif delta < 30:
                task.overdue_category = 'lt30'
            elif delta <= 60:
                task.overdue_category = '30_60'
            elif delta <= 90:
                task.overdue_category = '60_90'
            else:
                task.overdue_category = 'gt90'
