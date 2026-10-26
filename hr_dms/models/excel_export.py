import io

import xlsxwriter

from odoo import fields, models
from odoo.exceptions import AccessError, UserError

# Columns of the Excel export, in the order of the forms. A column is a field name, or
# (label, field name) to rename it; files are listed by name only, never their content.
DOCUMENT_COLUMNS = [
    ('Employee', 'employee_id'), ('Department', 'department_id'),
    'name', 'category_id', 'confidential', 'notes', 'state',
    ('Files', 'attachment_ids'), ('Number of Files', 'file_count'), 'expiry_date',
    'uploaded_by', ('Uploaded On', 'create_date'), 'approved_by', 'approved_date',
    'reject_reason', 'correction_reason', ('Last Updated', 'write_date'), ('Archived', 'active'),
]
DETAILS_COLUMNS = [
    ('Employee', 'employee_id'), 'full_name', ('Designation', 'designation'), 'department_name',
    'state', 'submitted_date', 'verified_by', 'verified_date', 'return_reason',
    ('Uploaded Document (file name)', 'source_filename'),
    # Private Contact
    'current_street', 'private_street2', 'current_city', 'private_state_id', 'current_zip',
    'current_country_id', 'personal_email', 'personal_mobile', 'bank_account_no',
    'private_car_plate', 'km_home_work',
    # Citizenship
    'country_id', 'gender', 'birthday', 'place_of_birth', 'country_of_birth_id', 'passport_no',
    'uid_aadhar_no', 'emirates_id_no',
    # Emergency Contact
    'emergency_name', 'emergency_phone',
    # Education
    'highest_qualification', 'field_of_study', 'school',
    # Family Status
    'marital', ('Dependent Children', 'children'),
    # Work Permit
    'visa_no', 'visa_expiry', 'work_permit_no', 'work_permit_expiry',
    ('Work Permit (file name)', 'work_permit_filename'),
    ('Created On', 'create_date'), ('Last Updated', 'write_date'),
]
EXPORT_COLUMNS = {'hr.dms.document': DOCUMENT_COLUMNS, 'hr.dms.personal.details': DETAILS_COLUMNS}


class HrDmsExcelExport(models.AbstractModel):
    """Configuration › Export: the selected documents or personal details forms as one Excel
    sheet, for the module Administrator only."""
    _name = 'hr.dms.excel.export'
    _description = 'Employee Documents Excel export'

    def _check_export_right(self):
        if not self.env.user.has_group('hr_dms.group_hr_dms_admin'):
            raise AccessError(self.env._("Only Employee Documents administrators can export."))

    def _export_action(self, records):
        self._check_export_right()
        if not records:
            raise UserError(self.env._("Select the records to export."))
        ids = ','.join(map(str, records.ids))
        return {'type': 'ir.actions.act_url', 'target': 'self',
                'url': f'/hr_dms/export/{records._name}?ids={ids}'}

    def _cell(self, rec, field, file_expiry=False):
        value = rec[field.name]
        if field.type == 'boolean':
            return self.env._("Yes") if value else self.env._("No")
        if field.type == 'selection':
            return dict(field._description_selection(self.env)).get(value, value or '')
        if field.type == 'many2one':
            return value.display_name or ''
        if field.type == 'many2many':
            if field.comodel_name == 'ir.attachment':
                return '\n'.join(
                    f"{att.name} (expires {att.hr_dms_expiry_date.strftime('%d/%m/%Y')})"
                    if file_expiry and att.hr_dms_expiry_date else att.name for att in value)
            return ', '.join(value.mapped('display_name'))
        if field.type == 'datetime':
            return fields.Datetime.context_timestamp(rec, value).replace(tzinfo=None) if value else ''
        if value is False or value is None:
            return ''
        return value

    def _build_xlsx(self, records):
        """The records as an .xlsx file (bytes), one row each, sorted by employee."""
        self._check_export_right()
        records.check_access('read')
        records = records.sudo().sorted(lambda r: ((r.employee_id.name or '').lower(), -r.id))
        columns = []
        for col in EXPORT_COLUMNS[records._name]:
            label, name = col if isinstance(col, tuple) else (None, col)
            field = records._fields[name]
            columns.append((label or field._description_string(self.env), field))

        buffer = io.BytesIO()
        book = xlsxwriter.Workbook(buffer, {'in_memory': True})
        head = book.add_format({'bold': True, 'bg_color': '#1F4E79', 'font_color': '#FFFFFF',
                                'border': 1, 'text_wrap': True, 'valign': 'vcenter'})
        text = book.add_format({'valign': 'top', 'text_wrap': True})
        date = book.add_format({'valign': 'top', 'num_format': 'dd/mm/yyyy'})
        stamp = book.add_format({'valign': 'top', 'num_format': 'dd/mm/yyyy hh:mm'})
        sheet = book.add_worksheet(self.env._("Documents") if records._name == 'hr.dms.document'
                                   else self.env._("Personal Details"))
        # a date that doesn't fit its column shows as ######## in Excel, so size them for the value
        min_width = {'date': 12, 'datetime': 18}
        widths = []
        for col, (label, field) in enumerate(columns):
            sheet.write(0, col, label, head)
            widths.append(max(min_width.get(field.type, 12), min(len(label) + 2, 40)))
        for row, rec in enumerate(records, start=1):
            for col, (label, field) in enumerate(columns):
                value = self._cell(rec, field, file_expiry=True)
                if field.type == 'date' and value:
                    sheet.write_datetime(row, col, fields.Datetime.to_datetime(value), date)
                elif field.type == 'datetime' and value:
                    sheet.write_datetime(row, col, value, stamp)
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    sheet.write_number(row, col, value, text)
                else:
                    value = str(value)
                    sheet.write_string(row, col, value, text)
                    widths[col] = max(widths[col], min(max(map(len, value.splitlines() or [''])) + 2, 60))
        for col, width in enumerate(widths):
            sheet.set_column(col, col, width)
        sheet.set_row(0, 30)
        sheet.freeze_panes(1, 1)
        sheet.autofilter(0, 0, len(records), len(columns) - 1)
        book.close()
        return buffer.getvalue()
