from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    dms_document_count = fields.Integer(compute='_compute_dms_counts', groups='hr_dms.group_hr_dms_manager')
    dms_details_state = fields.Selection(
        [('draft', 'Draft'), ('submitted', 'Submitted'), ('verified', 'Verified')],
        compute='_compute_dms_counts', string='Personal Details Form',
        groups='hr_dms.group_hr_dms_manager')

    def _compute_dms_counts(self):
        docs = self.env['hr.dms.document']._read_group(
            [('employee_id', 'in', self.ids)], ['employee_id'], ['__count'])
        counts = {emp.id: n for emp, n in docs}
        # the latest form wins
        forms = {d.employee_id.id: d.state for d in self.env['hr.dms.personal.details'].search(
            [('employee_id', 'in', self.ids)], order='id')}
        for emp in self:
            emp.dms_document_count = counts.get(emp.id, 0)
            emp.dms_details_state = forms.get(emp.id, False)

    def action_open_dms_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': self.env._('Documents'),
            'res_model': 'hr.dms.document', 'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id, 'search_default_employee_id': self.id,
                        'search_default_group_category': 1},
        }

    def action_open_dms_details(self):
        self.ensure_one()
        rec = self.env['hr.dms.personal.details'].search([('employee_id', '=', self.id)], order='id desc', limit=1)
        if not rec:
            rec = self.env['hr.dms.personal.details'].create({'employee_id': self.id, 'full_name': self.name})
        else:
            rec._fill_from_employee()
        return {
            'type': 'ir.actions.act_window', 'name': self.env._('Personal Details'),
            'res_model': 'hr.dms.personal.details', 'res_id': rec.id,
            'view_mode': 'form', 'views': [(False, 'form')],
        }
