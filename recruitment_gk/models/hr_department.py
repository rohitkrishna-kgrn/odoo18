from odoo import models, fields, api


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    position_ids = fields.Many2many(
        'hr.job',
        string='Job Positions',
        compute='_compute_position_ids',
        inverse='_inverse_position_ids',
        store=False,
    )

    @api.depends('member_ids.job_id', 'jobs_ids')
    def _compute_position_ids(self):
        for dept in self:
            # Positions held by current employees in this department
            employee_jobs = self.env['hr.employee'].search([
                ('department_id', '=', dept.id),
                ('job_id', '!=', False),
            ]).mapped('job_id')
            # Positions explicitly linked to this department via hr.job.department_id
            dept_jobs = self.env['hr.job'].search([
                ('department_id', '=', dept.id)
            ])
            dept.position_ids = employee_jobs | dept_jobs

    def _inverse_position_ids(self):
        for dept in self:
            current = self.env['hr.job'].search([
                ('department_id', '=', dept.id)
            ])
            new = dept.position_ids
            # Link newly added positions to this department
            (new - current).write({'department_id': dept.id})
            # Unlink removed positions from this department
            (current - new).write({'department_id': False})
