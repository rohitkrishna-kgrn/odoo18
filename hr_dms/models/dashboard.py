from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

DOC_STATES = ('draft', 'submitted', 'approved', 'rejected')
# the icon shown in a category cell is the furthest a document there got
CELL_ORDER = ('approved', 'submitted', 'rejected', 'draft')


class HrDmsDashboard(models.AbstractModel):
    """Data for the Employee Documents dashboard (static/src/dashboard).

    HR (HR Manager / Administrator) get every employee with a login: their latest personal
    details form and, per category, whether they submitted documents and how far those got.
    Everyone else gets the same picture for themselves only. Reads go through the normal
    access rules, so an employee never sees a document or category hidden from them.
    """
    _name = 'hr.dms.dashboard'
    _description = 'Employee Documents dashboard'

    @api.model
    def get_dashboard_data(self):
        user = self.env.user
        hr = user.has_group('hr_dms.group_hr_dms_manager')
        Employee = self.env['hr.employee'].sudo()
        if hr:
            employees = Employee.search([('user_id', '!=', False),
                                         ('company_id', 'in', self.env.companies.ids + [False])])
            doc_domain = [('employee_id', 'in', employees.ids)]
        else:
            employees = user.employee_id.sudo()
            doc_domain = [('employee_id', '=', employees.id or 0)]
        categories = self.env['hr.dms.category'].search([])
        Doc = self.env['hr.dms.document']

        # documents: employee x category x state
        cells, doc_states, by_category = {}, dict.fromkeys(DOC_STATES, 0), {}
        last_upload = {}
        for emp, cat, state, count, last in Doc._read_group(
                doc_domain, ['employee_id', 'category_id', 'state'], ['__count', 'create_date:max']):
            cell = cells.setdefault((emp.id, cat.id), dict.fromkeys(DOC_STATES, 0))
            cell[state] += count
            doc_states[state] += count
            by_category.setdefault(cat.id, dict.fromkeys(DOC_STATES, 0))[state] += count
            if last and (emp.id not in last_upload or last > last_upload[emp.id]):
                last_upload[emp.id] = last

        # personal details: the latest form of each employee
        latest = {}
        for form in self.env['hr.dms.personal.details'].search_read(
                [('employee_id', 'in', employees.ids)], ['employee_id', 'state'], order='id desc'):
            latest.setdefault(form['employee_id'][0], form)
        details_states = {'not_started': 0, 'draft': 0, 'submitted': 0, 'verified': 0}

        today = fields.Date.context_today(self)
        expiring = Doc.search_count(doc_domain + [('expiry_date', '!=', False),
                                                  ('expiry_date', '<=', today + relativedelta(days=30))])
        rows = []
        for emp in employees.sorted(lambda e: (e.name or '').lower()):
            form = latest.get(emp.id)
            details_state = form['state'] if form else 'not_started'
            details_states[details_state] += 1
            emp_cells, totals = {}, dict.fromkeys(DOC_STATES, 0)
            for cat in categories:
                counts = cells.get((emp.id, cat.id))
                if counts:
                    emp_cells[cat.id] = {'state': next(s for s in CELL_ORDER if counts[s]), 'counts': counts}
                    for s in DOC_STATES:
                        totals[s] += counts[s]
            rows.append({
                'id': emp.id,
                'name': emp.name,
                'department': emp.department_id.name or '',
                'details_state': details_state,
                'details_id': form['id'] if form else False,
                'cells': emp_cells,
                'totals': totals,
                'doc_count': sum(totals.values()),
                'missing': sum(1 for cat in categories if cat.id not in emp_cells),
                'last_upload': fields.Date.to_string(
                    fields.Datetime.context_timestamp(self, last_upload[emp.id]).date())
                if emp.id in last_upload else False,
            })

        # uploads per month, the last six months
        start = today.replace(day=1) - relativedelta(months=5)
        per_month = {month.strftime('%Y-%m'): count for month, count in Doc._read_group(
            doc_domain + [('create_date', '>=', fields.Datetime.to_datetime(start))],
            ['create_date:month'], ['__count'])}
        months = []
        for i in range(6):
            month = start + relativedelta(months=i)
            months.append({'label': month.strftime('%b %y'), 'count': per_month.get(month.strftime('%Y-%m'), 0)})

        return {
            'is_hr': hr,
            'is_admin': user.has_group('hr_dms.group_hr_dms_admin'),
            'employee_id': employees.id if not hr and employees else False,
            'categories': [{'id': c.id, 'name': c.name, 'code': c.code or c.name[:3].upper(),
                            'confidential': c.confidential, 'counts': by_category.get(c.id, dict.fromkeys(DOC_STATES, 0))}
                           for c in categories],
            'employees': rows,
            'doc_states': doc_states,
            'doc_total': sum(doc_states.values()),
            'details_states': details_states,
            'expiring': expiring,
            'months': months,
        }
