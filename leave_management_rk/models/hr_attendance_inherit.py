from odoo import models


class HrAttendanceInherit(models.Model):
    _inherit = 'hr.attendance'

    def name_get(self):
        result = []
        for rec in self:
            if rec.check_in:
                label = rec.check_in.strftime('%A, %d %b %Y')
            else:
                label = f'Attendance #{rec.id}'
            result.append((rec.id, label))
        return result
