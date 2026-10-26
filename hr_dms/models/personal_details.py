import base64
import os
import re

from dateutil import parser as dateparser

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from . import details_extractor as extractor
from .correction_mail import queue_correction_mail

# "New" starts another (empty) form at any time; "My Personal Details" opens the latest one

PROTECTED = {'state', 'verified_by', 'verified_date', 'return_reason', 'submitted_date', 'employee_id',
             'profile_edit_open'}

# (details field, hr.employee field): the answers are shown pre-filled from the employee form while the
# employee has not typed anything, and HR can copy verified answers back with "Update Employee Profile".
EMPLOYEE_MAP = [
    ('full_name', 'name'),
    ('current_street', 'private_street'), ('private_street2', 'private_street2'),
    ('current_city', 'private_city'), ('private_state_id', 'private_state_id'),
    ('current_zip', 'private_zip'), ('current_country_id', 'private_country_id'),
    ('personal_email', 'private_email'), ('personal_mobile', 'private_phone'),
    ('km_home_work', 'km_home_work'), ('private_car_plate', 'private_car_plate'),
    ('country_id', 'country_id'), ('passport_no', 'passport_id'), ('gender', 'gender'),
    ('birthday', 'birthday'), ('place_of_birth', 'place_of_birth'),
    ('country_of_birth_id', 'country_of_birth'),
    ('emergency_name', 'emergency_contact'), ('emergency_phone', 'emergency_phone'),
    ('field_of_study', 'study_field'), ('school', 'study_school'),
    ('children', 'children'), ('visa_no', 'visa_no'), ('visa_expiry', 'visa_expire'),
    ('work_permit_no', 'permit_no'), ('work_permit_expiry', 'work_permit_expiration_date'),
]
# Only these never overwrite a populated employee value when the form has no answer to give
APPLY_SKIP = {'full_name'}

MARITAL_KEYS = {'single': 'single', 'unmarried': 'single', 'married': 'married',
                'legal cohabitant': 'cohabitant', 'cohabitant': 'cohabitant',
                'widower': 'widower', 'widow': 'widower', 'widowed': 'widower',
                'divorced': 'divorced'}


class HrDmsPersonalDetails(models.Model):
    _name = 'hr.dms.personal.details'
    _description = 'Employee Personal Details Form'
    _inherit = ['mail.thread', 'hr.dms.live.mixin']
    _mail_post_access = 'read'
    _rec_name = 'employee_id'
    _order = 'employee_id'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True,
                                  ondelete='cascade', default=lambda self: self.env.user.employee_id)
    user_id = fields.Many2one('res.users', related='employee_id.user_id', store=True, index=True)
    company_id = fields.Many2one('res.company', related='employee_id.company_id', store=True, index=True)
    state = fields.Selection([
        ('draft', 'Draft'), ('submitted', 'Submitted'),
        ('verified', 'Verified'),
    ], default='draft', required=True, copy=False, string='Status', index=True, tracking=True)
    submitted_date = fields.Datetime(readonly=True, copy=False)
    verified_by = fields.Many2one('res.users', readonly=True, copy=False)
    verified_date = fields.Datetime(readonly=True, copy=False)
    # set by Update Employee Profile: HR may edit the verified form once; the next save locks it again
    profile_edit_open = fields.Boolean(readonly=True, copy=False)
    # why HR last sent the form back to Draft (Return for Correction or Reopen); cleared on Submit
    return_reason = fields.Text(string='Correction Needed', readonly=True, copy=False)

    # Personal
    full_name = fields.Char(string='Name', default=lambda self: self.env.user.sudo().employee_id.name)
    father_name = fields.Char(string="Father's / Guardian's Name")
    birthday = fields.Date(string='Date of Birth')
    place_of_birth = fields.Char()
    gender = fields.Selection([('male', 'Male'), ('female', 'Female'), ('other', 'Other')])
    marital = fields.Char(string='Marital Status')
    spouse_name = fields.Char(string="Spouse's Name")
    children = fields.Integer(string='Number of Dependent Children')
    country_id = fields.Many2one('res.country', string='Nationality')
    blood_group = fields.Selection([('a+', 'A+'), ('a-', 'A-'), ('b+', 'B+'), ('b-', 'B-'),
                                    ('ab+', 'AB+'), ('ab-', 'AB-'), ('o+', 'O+'), ('o-', 'O-')])
    # Contact
    personal_mobile = fields.Char(string='Private Phone')
    personal_email = fields.Char(string='Private Email')
    current_street = fields.Char(string='Private Address - Street')
    current_city = fields.Char(string='City')
    current_zip = fields.Char(string='Postal Code')
    current_country_id = fields.Many2one('res.country', string='Country')
    permanent_address = fields.Text(string='Permanent Address')
    # Emergency
    emergency_name = fields.Char(string='Emergency Contact Name')
    emergency_relation = fields.Char(string='Relationship')
    emergency_phone = fields.Char(string='Emergency Contact Phone')
    # Identification
    national_id_no = fields.Char(string='National ID No')
    passport_no = fields.Char(string='Passport No')
    passport_expiry = fields.Date(string='Passport Expiry')
    visa_no = fields.Char(string='Visa No')
    visa_expiry = fields.Date(string='Visa Expiration Date')
    # Education & bank
    highest_qualification = fields.Char(string='Qualification')
    bank_name = fields.Char()
    bank_account_no = fields.Char(string='Bank Account')
    bank_ifsc = fields.Char(string='IFSC / Swift Code')
    # Added to follow the HR paper form
    employee_image = fields.Image(related='employee_id.image_128', string='Photo')
    designation = fields.Char(compute='_compute_employee_info')
    department_name = fields.Char(string='Department', compute='_compute_employee_info')
    private_street2 = fields.Char(string='Street 2')
    private_state_id = fields.Many2one('res.country.state', string='State',
                                       domain="[('country_id', '=?', current_country_id)]")
    km_home_work = fields.Integer(string='Home-Work Distance (km)')
    private_car_plate = fields.Char(string='Private Car Plate')
    uid_aadhar_no = fields.Char(string='UID No / Aadhar No')
    emirates_id_no = fields.Char(string='Emirates ID No')
    country_of_birth_id = fields.Many2one('res.country', string='Country of Birth')
    field_of_study = fields.Char(string='Field of Study')
    school = fields.Char(string='School')
    work_permit_no = fields.Char(string='Work Permit No')
    work_permit_expiry = fields.Date(string='Work Permit Expiration Date')
    work_permit_file = fields.Binary(string='Work Permit', attachment=True)
    work_permit_filename = fields.Char()
    source_file = fields.Binary(string='Document', attachment=True, copy=False,
                                help="A filled-in copy of the HR personal details form (PDF or Word).")
    source_filename = fields.Char(copy=False)
    can_edit_details = fields.Boolean(compute='_compute_can_edit_details')
    is_own = fields.Boolean(compute='_compute_can_edit_details')

    @api.depends_context('uid')
    @api.depends('state', 'user_id', 'profile_edit_open')
    def _compute_can_edit_details(self):
        hr = self.env.user.has_group('hr_dms.group_hr_dms_manager')
        for rec in self:
            rec.is_own = rec.user_id == self.env.user
            # a verified form is final: only Update Employee Profile opens it to HR for one save
            rec.can_edit_details = (hr and (rec.state in ('draft', 'submitted') or rec.profile_edit_open)) or (
                rec.user_id == self.env.user and rec.state == 'draft')

    @api.depends('employee_id')
    def _compute_employee_info(self):
        # plain employees cannot read hr.employee, so the header facts come through sudo
        for rec in self:
            emp = rec.employee_id.sudo()
            rec.designation = emp.job_title or emp.job_id.name or False
            rec.department_name = emp.department_id.name or False

    def _fill_from_employee(self):
        """Keep the form in step with the employee form: every value the employee form holds is
        shown here, so the two never disagree. Blank values on the employee form leave the
        answer untouched for the employee to fill in. A submitted form is left alone while HR
        reviews it. Only the employee's first form is kept in step: a form started with "New" is
        the employee's own fresh answers and starts empty."""
        first = {emp.id: form_id for emp, form_id in self.sudo()._read_group(
            [('employee_id', 'in', self.employee_id.ids)], ['employee_id'], ['id:min'])}
        for rec in self.filtered(lambda r: r.state == 'draft' and r.employee_id
                                 and first.get(r.employee_id.id) == r.id):
            emp = rec.employee_id.sudo()
            wanted = rec._employee_values(emp)
            vals = {}
            for det, val in wanted.items():
                cur = rec[det]
                cur = cur.id if hasattr(cur, '_name') else cur
                if cur != val:
                    vals[det] = val
            if emp.has_work_permit and not rec.work_permit_file:
                vals['work_permit_file'] = emp.has_work_permit
                vals['work_permit_filename'] = emp.work_permit_name or 'Work Permit'
            if vals:
                rec.sudo().with_context(hr_dms_no_sync=True).write(vals)

    def _employee_values(self, emp):
        """The answers the employee form holds, as values for this form (self may be empty)."""
        emp = emp.sudo()
        wanted = {}
        for det, emp_f in EMPLOYEE_MAP:
            val = emp[emp_f]
            if val:
                wanted[det] = val.id if hasattr(val, '_name') else val
        if emp.marital and (not self.marital or (self.marital or '').strip().lower() in MARITAL_KEYS):
            wanted['marital'] = dict(emp._fields['marital']._description_selection(self.env)).get(
                emp.marital, emp.marital)
        labels = {l.lower() for k, l in emp._fields['certificate']._description_selection(self.env)}
        if emp.certificate and (not self.highest_qualification
                                or self.highest_qualification.strip().lower() in labels):
            wanted['highest_qualification'] = dict(emp._fields['certificate']._description_selection(
                self.env)).get(emp.certificate, emp.certificate)
        acc = emp.bank_account_id.acc_number or emp.bank_account_no
        if acc:
            wanted['bank_account_no'] = acc
        return wanted

    def _check_employee_has_user(self, vals_list):
        # the form belongs to the employee's user (user_id), so an employee without a login can't have one
        for vals in vals_list:
            emp = self.env['hr.employee'].sudo().browse(vals.get('employee_id'))
            if not emp:
                raise UserError(self.env._("Select the employee this form is for."))
            if not emp.user_id:
                raise UserError(self.env._(
                    "%s has no user account, so a personal details form can't be assigned to them. "
                    "Link a user to the employee first.", emp.name))

    def _profile_vals(self, only=None):
        """hr.employee values for the answers on this form (only the given details fields if set)."""
        self.ensure_one()
        emp = self.employee_id.sudo()
        vals = {}
        for det_field, emp_field in EMPLOYEE_MAP:
            if det_field in APPLY_SKIP or (only is not None and det_field not in only):
                continue
            val = self[det_field]
            if val:
                vals[emp_field] = val.id if hasattr(val, '_name') else val
        if only is None or 'marital' in only:
            marital = MARITAL_KEYS.get((self.marital or '').strip().lower())
            if marital:
                vals['marital'] = marital
        if only is None or 'highest_qualification' in only:
            certificate = {label.lower(): key for key, label in
                           emp._fields['certificate']._description_selection(self.env)}.get(
                (self.highest_qualification or '').strip().lower())
            if certificate:
                vals['certificate'] = certificate
        if (only is None or 'spouse_name' in only) and self.spouse_name:
            vals['spouse_complete_name'] = self.spouse_name
        if (only is None or 'work_permit_file' in only) and self.work_permit_file:
            vals['has_work_permit'] = self.work_permit_file
        return vals

    def _log(self, text):
        for rec in self:
            self.env['hr.dms.audit.log'].log('details', text, employee=rec.employee_id)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group('hr_dms.group_hr_dms_manager'):
            emp = self.env.user.employee_id
            if not emp:
                raise AccessError(self.env._("Your user is not linked to an employee record."))
            for vals in vals_list:
                vals['employee_id'] = emp.id
        if not self.env.su:
            for vals in vals_list:
                for f in PROTECTED - {'employee_id'}:
                    vals.pop(f, None)
            self._check_employee_has_user(vals_list)
        for vals in vals_list:
            # the name is read-only on the employee's form, so it always comes from the employee record
            if not vals.get('full_name') and vals.get('employee_id'):
                vals['full_name'] = self.env['hr.employee'].sudo().browse(vals['employee_id']).name
        records = super().create(vals_list)
        # what was typed into a new form reaches the employee form before the blanks are filled from it
        for rec, vals in zip(records, vals_list):
            rec._sync_to_employee(set(vals))
        records._fill_from_employee()
        records._log(self.env._("Personal details form created"))
        return records

    NO_CHANGE_NOTE = {'state', 'submitted_date', 'verified_by', 'verified_date', 'return_reason',
                      'employee_id', 'source_file', 'source_filename', 'work_permit_file',
                      'work_permit_filename'}

    def _display_value(self, field, value):
        """Readable text of a field value for the chatter; blank shows as None."""
        if value is False or value is None or value == '' or (field.type == 'many2one' and not value):
            return 'None'
        if field.type == 'many2one':
            return value.display_name
        if field.type == 'selection':
            return dict(field._description_selection(self.env)).get(value, value)
        return str(value)

    def write(self, vals):
        if not self.env.su and PROTECTED & set(vals):
            raise AccessError(self.env._("Status fields can only be changed through the workflow buttons."))
        changes = {f for f in vals if not f.startswith('message_')}
        hr = self.env.user.has_group('hr_dms.group_hr_dms_manager')
        edit_once = self.filtered(lambda r: r.state == 'verified' and r.profile_edit_open and hr)
        if not self.env.su and changes and 'verified' in (self - edit_once).mapped('state'):
            raise UserError(self.env._("A verified form is read-only. HR can Reopen it if something must change."))
        noted = [f for f in vals if f in self._fields and f not in self.NO_CHANGE_NOTE
                 and self._fields[f].store and self._fields[f].type != 'binary'
                 and not f.startswith('message_')] if not self.env.su else []
        old = {rec.id: {f: self._display_value(self._fields[f], rec[f]) for f in noted} for rec in self}
        old_files = {rec.id: (rec.source_filename, rec.work_permit_filename) for rec in self}
        res = super().write(vals)
        if not self.env.su or self.env.context.get('hr_dms_log_details'):
            self._log(self.env._("Fields updated: %s", ', '.join(sorted(vals))))
        for rec in self:
            lines = []
            for f in noted:
                before, after = old[rec.id][f], self._display_value(self._fields[f], rec[f])
                if before != after:
                    lines.append((self._fields[f].string, before, after))
            for key, label, name in (('source_file', 'Document', 'source_filename'),
                                     ('work_permit_file', 'Work Permit', 'work_permit_filename')):
                if key in vals:
                    before = old_files[rec.id][0 if key == 'source_file' else 1] or 'None'
                    lines.append((label, before, rec[name] or ('uploaded' if vals[key] else 'None')))
            synced = False
            if not self.env.context.get('hr_dms_no_sync'):
                synced = rec._sync_to_employee(set(vals))
            if lines and not self.env.su:
                body = Markup('<ul>%s</ul>') % Markup('').join(
                    Markup('<li>%s: %s \u2192 %s</li>') % (label, before, after)
                    for label, before, after in lines)
                if synced:
                    body += Markup('<p>%s</p>') % self.env._("The Employee form was updated with these changes.")
                rec.message_post(body=body)
        if edit_once and changes and not self.env.su:
            edit_once.sudo().with_context(hr_dms_no_sync=True).write({'profile_edit_open': False})
            edit_once._log(self.env._("Verified form edited by HR and locked again"))
        return res

    def _sync_to_employee(self, changed):
        """What is typed here lands on the employee form too, so the two stay identical."""
        self.ensure_one()
        rec = self
        if rec.state == 'submitted' and not self.env.user.has_group('hr_dms.group_hr_dms_manager'):
            return False
        emp = rec.employee_id.sudo()
        emp_vals = {f: v for f, v in rec._profile_vals(only=changed).items()
                    if (emp[f].id if hasattr(emp[f], '_name') else emp[f]) != v}
        if not emp_vals:
            return False
        rec.employee_id.sudo().write(emp_vals)
        rec._log(self.env._("Employee profile updated from the form: %s", ', '.join(sorted(emp_vals))))
        return True

    def unlink(self):
        self._log(self.env._("Personal details form deleted"))
        return super().unlink()

    def action_submit(self):
        for rec in self:
            if rec.user_id != self.env.user:
                raise AccessError(self.env._("Only the employee can submit their own form."))
            if rec.state != 'draft':
                raise UserError(self.env._("This form has already been submitted."))
            rec.sudo().write({'state': 'submitted', 'submitted_date': fields.Datetime.now(),
                              'return_reason': False})
            rec._log(self.env._("Form submitted by employee"))

    def _require_hr(self):
        if not self.env.user.has_group('hr_dms.group_hr_dms_manager'):
            raise AccessError(self.env._("Only HR can review personal details."))

    def action_verify(self):
        self._require_hr()
        for rec in self:
            rec.sudo().write({'state': 'verified', 'verified_by': self.env.uid,
                              'verified_date': fields.Datetime.now(), 'profile_edit_open': False})
            rec._log(self.env._("Form verified by HR"))

    def _send_back_to_draft(self, reason, log_text, note_title, intro):
        for rec in self:
            rec.sudo().write({'state': 'draft', 'return_reason': reason, 'profile_edit_open': False,
                              'verified_by': False, 'verified_date': False})
            rec._log(log_text % (reason or '-'))
            # a log note, not a message: followers get no mail, the employee alone is mailed below
            rec.message_post(
                body=Markup("<b>%s</b>") % Markup('<br/>').join([note_title] + (reason or '-').splitlines()),
                subtype_xmlid='mail.mt_note')
            mail = queue_correction_mail(
                rec, rec.employee_id,
                title=self.env._("Personal details: correction needed"),
                intro=intro,
                rows=[(self.env._("Employee"), rec.employee_id.sudo().name),
                      (self.env._("Form"), self.env._("Employee Personal Details Form")),
                      (self.env._("Status"), self.env._("Draft (open for correction)"))],
                reason=reason,
                url=f"/odoo/hr.dms.personal.details/{rec.id}",
                button=self.env._("Open my form"),
                action_text=self.env._("Please make the corrections and click Submit to HR again."))
            if not mail:
                rec.message_post(body=self.env._("%s has no email address, so no mail was sent.",
                                                 rec.employee_id.sudo().name), subtype_xmlid='mail.mt_note')

    def action_return(self, reason=''):
        """HR sends a submitted form back to the employee, in Draft, with what to correct."""
        self._require_hr()
        if self.filtered(lambda r: r.state != 'submitted'):
            raise UserError(self.env._("Only a submitted form can be returned for correction."))
        self._send_back_to_draft(
            reason, self.env._("Form returned to employee for correction: %s"),
            self.env._("Returned for correction:"),
            self.env._("HR has reviewed your personal details form and moved it back to Draft so you can correct it."))

    def action_reopen(self, reason=''):
        """HR reopens a verified form, in Draft, with the reason."""
        self._require_hr()
        if self.filtered(lambda r: r.state != 'verified'):
            raise UserError(self.env._("Only a verified form can be reopened."))
        self._send_back_to_draft(
            reason, self.env._("Form reopened by HR: %s"), self.env._("Reopened by HR:"),
            self.env._("HR has reopened your verified personal details form and moved it back to Draft."))

    def _open_reason_wizard(self, mode, name):
        self._require_hr()
        return {
            'type': 'ir.actions.act_window', 'name': name,
            'res_model': 'hr.dms.return.wizard', 'view_mode': 'form', 'target': 'new',
            'context': {'default_details_id': self.id, 'default_mode': mode},
        }

    def action_open_return_wizard(self):
        return self._open_reason_wizard('return', self.env._('Return for Correction'))

    def action_open_reopen_wizard(self):
        return self._open_reason_wizard('reopen', self.env._('Reopen Form'))

    def action_apply_to_profile(self):
        """Copy the verified answers onto the hr.employee record (HR decision, never automatic)."""
        self._require_hr()
        for rec in self:
            if rec.state != 'verified':
                raise UserError(self.env._("Verify the form before updating the employee profile."))
            vals = rec._profile_vals()
            rec.employee_id.sudo().write(vals)
            rec._log(self.env._("Employee profile updated from the form: %s", ', '.join(sorted(vals))))
            # HR may now correct the form once; saving pushes the change to the profile and locks it again
            rec.sudo().write({'profile_edit_open': True})

    def action_export_xlsx(self):
        """Configuration › Export: the selected forms as an Excel sheet (Administrator only)."""
        return self.env['hr.dms.excel.export']._export_action(self)

    def action_lock_form(self):
        """HR closes the one-time edit without changing anything."""
        self._require_hr()
        self.sudo().write({'profile_edit_open': False})

    @api.constrains('source_file', 'source_filename')
    def _check_source_file(self):
        for rec in self:
            if rec.source_filename:
                ext = os.path.splitext(rec.source_filename)[1].lstrip('.').lower()
                if ext not in ('pdf', 'docx', 'doc', 'png', 'jpg', 'jpeg'):
                    raise ValidationError(self.env._("Upload a PDF or Word document."))
            if rec.source_file and len(rec.source_file) * 3 // 4 > extractor.MAX_BYTES:
                raise ValidationError(self.env._("The file exceeds the 10 MB limit."))

    COUNTRY_ALIASES = {'uae': 'AE', 'u.a.e': 'AE', 'u.a.e.': 'AE', 'emirates': 'AE', 'uk': 'GB',
                       'u.k': 'GB', 'england': 'GB', 'usa': 'US', 'u.s.a': 'US', 'america': 'US'}

    def _find_country(self, raw):
        Country = self.env['res.country']
        value = raw.strip(' .,')
        code = self.COUNTRY_ALIASES.get(value.lower())
        if code or len(value) <= 3:
            return Country.search([('code', '=', code or value.upper())], limit=1) or \
                Country.search([('name', '=ilike', value)], limit=1)
        # (an '=ilike' on `code` with a long word wrongly matched a country, so codes are exact only)
        return Country.search([('name', '=ilike', value)], limit=1) or \
            Country.search([('name', 'ilike', value)], limit=1)

    def _find_state(self, raw, country_id=False):
        """State by full name, code (TN) or part of the name, inside the country when known."""
        State = self.env['res.country.state']
        value = re.sub(r'\s*\(.*?\)\s*', ' ', raw).strip(' .,')
        value = re.sub(r'^state of\s+', '', value, flags=re.I)
        base = [('country_id', '=', country_id)] if country_id else []
        for domain in ([('name', '=ilike', value)], [('code', '=ilike', value)], [('name', 'ilike', value)]):
            if domain[0][0] == 'code' and len(value) > 3:
                continue
            state = State.search(base + domain, limit=2)
            if len(state) == 1 or (state and domain[0][0] == 'name' and domain[0][1] == '=ilike'):
                return state[0]
        # spelling without spaces / punctuation ("Tamilnadu" for "Tamil Nadu")
        squash = lambda t: re.sub(r'[^a-z0-9]', '', (t or '').lower())  # noqa: E731
        wanted = squash(value)
        if wanted:
            for state in State.search(base):
                if squash(state.name) == wanted:
                    return state
        return State

    def _convert_extracted(self, field, raw, vals):
        """Turn text read from the document into a value for `field`, or False if not understood."""
        if field in ('current_country_id', 'country_id', 'country_of_birth_id'):
            return self._find_country(raw).id or False
        if field == 'private_state_id':
            country = vals.get('current_country_id') or self.current_country_id.id
            state = self._find_state(raw, country)
            if state and not country:
                vals.setdefault('current_country_id', state.country_id.id)
            return state.id or False
        if field == 'gender':
            return {'male': 'male', 'm': 'male', 'female': 'female', 'f': 'female',
                    'other': 'other'}.get(raw.strip().lower(), False)
        if field in ('birthday', 'visa_expiry', 'work_permit_expiry'):
            try:
                return dateparser.parse(raw, dayfirst=True, fuzzy=False).date()
            except (ValueError, OverflowError):
                return False
        if field in ('km_home_work', 'children'):
            m = re.search(r'\d+', raw)
            return int(m.group()) if m else False
        return raw

    def action_fill_from_document(self):
        """Read the uploaded document and fill every blank field of this form from it."""
        self.ensure_one()
        if not self.can_edit_details:
            raise UserError(self.env._("This form can no longer be edited."))
        if not self.source_file:
            raise UserError(self.env._("Upload a document first."))
        text = extractor.extract_text(self.source_filename, base64.b64decode(self.source_file))
        found = extractor.parse(text)
        vals, filled, kept, unclear = {}, [], [], []
        # country before state, so a state is looked up inside the right country
        for field, raw in sorted(found.items(), key=lambda kv: kv[0] != 'current_country_id'):
            label = self._fields[field].string
            if self[field]:
                kept.append(label)
                continue
            value = self._convert_extracted(field, raw, vals)
            if value is False or value == '':
                unclear.append(f"{label} ({raw})")
                continue
            vals[field] = value
            filled.append(label)
        if vals:
            self.write(vals)
            self.message_post(body=self.env._("Filled from the uploaded document '%(file)s': %(fields)s",
                                              file=self.source_filename or '', fields=', '.join(filled)))
        if not found:
            msg = self.env._("No field labels were found in this file. Upload the HR Employee Personal "
                             "Details form with the details typed in (a scanned picture cannot be read).")
            kind = 'warning'
        else:
            parts = []
            if filled:
                parts.append(self.env._("Filled: %s.", ', '.join(filled)))
            if kept:
                parts.append(self.env._("Already filled, unchanged: %s.", ', '.join(kept)))
            if unclear:
                parts.append(self.env._("Could not be understood: %s.", ', '.join(unclear)))
            msg = ' '.join(parts) or self.env._("Nothing new to fill.")
            kind = 'success' if filled else 'warning'
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': self.env._("Fill from Document"), 'message': msg, 'type': kind,
                       'sticky': True, 'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}},
        }

    @api.model
    def action_open_my_details(self):
        emp = self.env.user.employee_id
        if not emp:
            raise UserError(self.env._("Your user is not linked to an employee record. Please contact HR."))
        rec = self.search([('employee_id', '=', emp.id)], order='id desc', limit=1)
        if not rec:
            rec = self.create({'employee_id': emp.id, 'full_name': emp.name})
        else:
            rec._fill_from_employee()
        return {
            'type': 'ir.actions.act_window', 'name': self.env._('My Personal Details'),
            'res_model': self._name, 'res_id': rec.id, 'view_mode': 'form',
            'views': [(self.env.ref('hr_dms.view_hr_dms_my_details_form').id, 'form')], 'target': 'current',
        }
