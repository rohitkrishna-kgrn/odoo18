import os

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .correction_mail import queue_correction_mail

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'xls', 'xlsx'}
MAX_FILE_MB = 10

# Fields only the workflow actions may change (they run as su after an explicit group check)
PROTECTED_FIELDS = {'state', 'approved_by', 'approved_date', 'reject_reason', 'correction_reason', 'uploaded_by'}
# Everything an employee may touch on their own, not-yet-approved document
EMPLOYEE_WRITABLE = {'name', 'attachment_ids', 'notes', 'category_id'}
LOGGED_FIELDS = ['name', 'employee_id', 'category_id', 'attachment_ids', 'notes', 'expiry_date', 'active']


class HrDmsDocument(models.Model):
    _name = 'hr.dms.document'
    _description = 'Employee Document'
    _inherit = ['mail.thread', 'hr.dms.live.mixin']
    _mail_post_access = 'read'
    _order = 'employee_id, category_id, id desc'
    _rec_name = 'name'

    name = fields.Char(string='Title', required=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True,
                                  ondelete='cascade', default=lambda self: self._default_employee(),
                                  tracking=True)
    user_id = fields.Many2one('res.users', related='employee_id.user_id', store=True, index=True,
                              string='Employee User')
    company_id = fields.Many2one('res.company', related='employee_id.company_id', store=True, index=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', store=True)
    category_id = fields.Many2one('hr.dms.category', string='Category', required=True, index=True,
                                  ondelete='restrict', tracking=True,
                                  group_expand='_read_group_category_ids')
    # Category flags are stored so that record rules never have to join through the category model
    confidential = fields.Boolean(related='category_id.confidential', store=True, index=True)
    emp_can_view = fields.Boolean(related='category_id.employee_can_view', store=True)
    emp_can_upload = fields.Boolean(related='category_id.employee_can_upload', store=True)
    emp_can_edit = fields.Boolean(related='category_id.employee_can_edit', store=True)
    emp_can_download = fields.Boolean(related='category_id.employee_can_download', store=True)

    # Plain attachments (res_field empty) linked to the document; ir.attachment ties their access
    # to the document through res_model/res_id, and ir_attachment.py/ir_binary.py add the download rule
    attachment_ids = fields.Many2many('ir.attachment', 'hr_dms_document_attachment_rel', 'document_id',
                                      'attachment_id', string='Files', copy=False)
    file_count = fields.Integer(compute='_compute_file_count')
    notes = fields.Text(string='Description', tracking=True)
    # Each file carries its own expiry (ir.attachment.hr_dms_expiry_date); the document keeps the
    # earliest one so the list column, the 30-day filter and the kanban badge still work
    expiry_date = fields.Date(string='Earliest Expiry', compute='_compute_expiry_date', store=True,
                              help="Earliest expiry date among the document's files.")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', required=True, index=True, copy=False, string='Status', tracking=True)
    uploaded_by = fields.Many2one('res.users', default=lambda self: self.env.uid, readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_date = fields.Datetime(readonly=True, copy=False)
    reject_reason = fields.Text(readonly=True, copy=False)
    correction_reason = fields.Text(string='Correction Needed', readonly=True, copy=False,
                                    help="Why HR moved the document back to Draft.")
    active = fields.Boolean(default=True)
    # set when the document was archived only because its category was, so unarchiving the
    # category brings back exactly those and not documents HR archived on their own
    archived_by_category = fields.Boolean(copy=False, readonly=True)

    can_download = fields.Boolean(compute='_compute_can_flags')
    can_add_files = fields.Boolean(compute='_compute_can_flags')
    can_remove_files = fields.Boolean(compute='_compute_can_flags')
    can_edit = fields.Boolean(compute='_compute_can_flags')
    can_approve = fields.Boolean(compute='_compute_can_flags')
    can_reject = fields.Boolean(compute='_compute_can_flags')
    can_submit = fields.Boolean(compute='_compute_can_flags')
    can_reset_draft = fields.Boolean(compute='_compute_can_flags')
    is_expiring = fields.Boolean(compute='_compute_is_expiring')

    # ------------------------------------------------------------------ helpers
    @api.model
    def _default_employee(self):
        return self.env.user.employee_id

    @api.model
    def _read_group_category_ids(self, categories, domain):
        # Show every category the user may view as a pipeline column, even when it has no documents yet
        cats = self.env['hr.dms.category']
        if not self._is_hr():
            cats = cats.search([('employee_can_view', '=', True)])
        else:
            cats = cats.search([])
        return cats

    def _is_hr(self):
        return self.env.su or self.env.user.has_group('hr_dms.group_hr_dms_manager')

    def _is_own(self):
        return self.user_id == self.env.user

    @api.depends_context('uid')
    @api.depends('user_id', 'emp_can_download', 'emp_can_edit', 'state', 'confidential')
    def _compute_can_flags(self):
        user = self.env.user
        hr = user.has_group('hr_dms.group_hr_dms_manager')
        mgr = user.has_group('hr_dms.group_hr_dms_manager')
        for rec in self:
            own = rec.user_id == user
            rec.can_download = hr or (own and rec.emp_can_download)
            # An employee edits their own document, fields and files alike, only while it is in Draft
            # (new, or moved back by HR for correction) and the category lets them upload or update.
            # Once submitted it is HR's alone until HR moves it back to Draft.
            may_change = own and rec.state == 'draft' and (rec.emp_can_upload or rec.emp_can_edit)
            rec.can_add_files = rec.can_remove_files = rec.can_edit = hr or may_change
            rec.can_submit = rec.state == 'draft' and (hr or own)
            rec.can_reset_draft = mgr and rec.state in ('submitted', 'rejected')
            rec.can_approve = mgr and not own and rec.state in ('submitted', 'rejected')
            # an approval can be withdrawn later, e.g. a document found to be wrong after the fact
            rec.can_reject = mgr and not own and rec.state in ('submitted', 'approved')

    @api.depends('attachment_ids.hr_dms_expiry_date')
    def _compute_expiry_date(self):
        for rec in self:
            dates = [d for d in rec.sudo().attachment_ids.mapped('hr_dms_expiry_date') if d]
            rec.expiry_date = min(dates) if dates else False

    @api.depends('attachment_ids')
    def _compute_file_count(self):
        for rec in self:
            rec.file_count = len(rec.attachment_ids)

    @api.depends('expiry_date')
    def _compute_is_expiring(self):
        limit = fields.Date.add(fields.Date.context_today(self), days=30)
        for rec in self:
            rec.is_expiring = bool(rec.expiry_date and rec.expiry_date <= limit)

    # ------------------------------------------------------------- constraints
    @api.constrains('attachment_ids')
    def _check_file(self):
        max_mb = int(self.env['ir.config_parameter'].sudo().get_param('hr_dms.max_file_mb', MAX_FILE_MB))
        for att in self.sudo().attachment_ids:
            ext = os.path.splitext(att.name or '')[1].lstrip('.').lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise ValidationError(self.env._(
                    "File type '.%(ext)s' is not allowed (%(name)s). Allowed: %(allowed)s",
                    ext=ext, name=att.name, allowed=', '.join(sorted(ALLOWED_EXTENSIONS))))
            if att.file_size > max_mb * 1024 * 1024:
                raise ValidationError(self.env._("'%(name)s' exceeds the %(mb)s MB limit.", name=att.name, mb=max_mb))

    def _adopt_attachments(self):
        """Only files uploaded for this document (or uploaded by this user on an unsaved form) may be
        linked, so nobody can pull someone else's attachment into a document they can read."""
        for rec in self:
            for att in rec.sudo().attachment_ids:
                if att.res_model == rec._name and att.res_id == rec.id and not att.res_field:
                    continue
                if (att.res_model == rec._name and not att.res_id and not att.res_field
                        and (self.env.su or att.create_uid.id == self.env.uid)):
                    att.write({'res_id': rec.id})
                    continue
                raise AccessError(self.env._("'%s' was not uploaded to this document.", att.name))

    # -------------------------------------------------------------- access guards
    def _check_download(self, log=True, detail=None):
        """Raise unless the current user may fetch the file content."""
        if self.env.su:
            return
        user = self.env.user
        hr = user.has_group('hr_dms.group_hr_dms_manager')
        # unsaved records (form onchange on "New") have no stored file to protect
        saved = self.filtered('id')
        for rec in saved:
            if not (hr or (rec.user_id == user and rec.emp_can_download)):
                raise AccessError(self.env._("You are not allowed to download this document."))
        if log:
            for rec in saved:
                self.env['hr.dms.audit.log'].log(
                    'download', detail or rec._file_names(), document=rec, employee=rec.employee_id,
                    category=rec.category_id, confidential=rec.confidential)

    def action_download_files(self):
        """Download button: one file comes as it is, several as a zip."""
        self.ensure_one()
        self._check_download(log=False)
        files = self.sudo().attachment_ids
        if not files:
            raise UserError(self.env._("This document has no files yet."))
        url = (f'/web/content/{files.id}?download=true' if len(files) == 1
               else f'/hr_dms/document/{self.id}/download')
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'self'}

    def action_export_xlsx(self):
        """Configuration › Export: the selected documents as an Excel sheet (Administrator only)."""
        return self.env['hr.dms.excel.export']._export_action(self)

    def copy(self, default=None):
        raise UserError(self.env._("Documents cannot be duplicated."))

    # ------------------------------------------------------------------ CRUD
    @api.model_create_multi
    def create(self, vals_list):
        hr = self._is_hr()
        for vals in vals_list:
            if not hr:
                # An employee can only ever create for themselves; every new document starts in Draft
                emp = self.env.user.employee_id
                if not emp:
                    raise AccessError(self.env._("Your user is not linked to an employee record."))
                vals['employee_id'] = emp.id
            if not self.env.su:
                for f in PROTECTED_FIELDS - {'state'}:
                    vals.pop(f, None)
                vals['uploaded_by'] = self.env.uid
                vals['state'] = 'draft'
        records = super().create(vals_list)
        records._adopt_attachments()
        for rec in records:
            self.env['hr.dms.audit.log'].log(
                'upload', self.env._("Uploaded %s", rec._file_names() or rec.name), document=rec,
                employee=rec.employee_id, category=rec.category_id, confidential=rec.confidential)
        return records

    def write(self, vals):
        if not self.env.su:
            if PROTECTED_FIELDS & set(vals):
                raise AccessError(self.env._("Status and approval fields can only be changed through the workflow buttons."))
            if not self._is_hr():
                extra = {k for k in set(vals) - EMPLOYEE_WRITABLE if not k.startswith('message_')}
                if extra:
                    raise AccessError(self.env._("You may only update the title, category, description and files."))
                # upload-only employees may add files, nothing else
                if set(vals) - {'attachment_ids'} and not all(self.mapped('can_edit')):
                    raise AccessError(self.env._("You may only add files to this document."))
                if 'attachment_ids' in vals and not all(self.mapped('can_add_files')):
                    raise AccessError(self.env._("You cannot add files to this document."))
                if vals.get('category_id'):
                    cat = self.env['hr.dms.category'].browse(vals['category_id'])
                    if not cat.employee_can_upload:
                        raise AccessError(self.env._("You cannot file a document under '%s'.", cat.name))
        before_files = {rec.id: rec.sudo().attachment_ids for rec in self}
        may_remove = {rec.id: rec.can_remove_files for rec in self}
        changes = {}
        for rec in self:
            changes[rec.id] = rec._snapshot()
        res = super().write(vals)
        removed_all = self.env['ir.attachment']
        if 'attachment_ids' in vals:
            self._adopt_attachments()
            for rec in self:
                after_files = rec.sudo().attachment_ids
                added, removed = after_files - before_files[rec.id], before_files[rec.id] - after_files
                if removed and not may_remove[rec.id]:
                    raise AccessError(self.env._(
                        "You can only remove files while the document is in Draft. After that, only HR "
                        "Managers and Administrators can remove files."))
                lines = [self.env._("Added: %s", n) for n in added.mapped('name')]
                lines += [self.env._("Removed: %s", n) for n in removed.mapped('name')]
                if lines:
                    rec.message_post(body=Markup('<br/>').join(lines))
                removed_all |= removed
        for rec in self:
            before, after = changes[rec.id], rec._snapshot()
            diff = [f"{k}: {before[k]!r} -> {after[k]!r}" for k in after if before[k] != after[k]]
            if not diff:
                continue
            action = 'archive' if 'active' in vals else 'modify'
            self.env['hr.dms.audit.log'].log(
                action, '\n'.join(diff), document=rec, employee=rec.employee_id,
                category=rec.category_id, confidential=rec.confidential)
        # a file taken off a document is deleted, not left behind as a stray attachment
        removed_all.filtered(lambda a: a.res_model == self._name and a.res_id in self.ids).sudo().unlink()
        return res

    def _file_names(self):
        self.ensure_one()
        return ', '.join(self.sudo().attachment_ids.mapped('name'))

    def _snapshot(self):
        self.ensure_one()
        out = {}
        for f in LOGGED_FIELDS:
            val = self.sudo()[f]
            if f == 'attachment_ids':
                val = ', '.join(sorted(
                    f"{a.name} (expires {a.hr_dms_expiry_date})" if a.hr_dms_expiry_date else a.name
                    for a in val))
            out[f] = val.display_name if hasattr(val, '_name') else val
        return out

    def unlink(self):
        if not self.env.su and not self.env.user.has_group('hr_dms.group_hr_dms_manager'):
            raise AccessError(self.env._("Only HR Managers can delete documents."))
        for rec in self:
            self.env['hr.dms.audit.log'].log(
                'delete', self.env._("Deleted '%(name)s' (%(files)s)", name=rec.name, files=rec._file_names()),
                document=None,
                employee=rec.employee_id, category=rec.category_id, confidential=rec.confidential,
                document_name=rec.name)
        return super().unlink()

    # ------------------------------------------------------------------ workflow
    def _require_approver(self):
        if not self.env.user.has_group('hr_dms.group_hr_dms_manager'):
            raise AccessError(self.env._("Only HR Managers can approve or reject documents."))
        for rec in self:
            if rec.user_id == self.env.user:
                raise AccessError(self.env._("You cannot approve or reject your own document."))

    def action_submit(self):
        for rec in self:
            if not rec.can_submit:
                raise AccessError(self.env._("Only a Draft document can be submitted, by its employee or HR."))
            if not rec.attachment_ids:
                raise UserError(self.env._("Upload at least one file before submitting '%s'.", rec.name))
            rec.sudo().write({'state': 'submitted', 'reject_reason': False})
            self.env['hr.dms.audit.log'].log(
                'submit', '', document=rec, employee=rec.employee_id,
                category=rec.category_id, confidential=rec.confidential)

    def action_open_draft_wizard(self):
        if not all(self.mapped('can_reset_draft')):
            raise AccessError(self.env._("Only HR Managers and Administrators can move a Submitted or Rejected document to Draft."))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Move to Draft for Correction'),
            'res_model': 'hr.dms.draft.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_document_ids': [(6, 0, self.ids)]},
        }

    def action_move_to_draft(self, reason):
        if not all(self.mapped('can_reset_draft')):
            raise AccessError(self.env._("Only HR Managers and Administrators can move a Submitted or Rejected document to Draft."))
        for rec in self:
            rec.sudo().write({'state': 'draft', 'correction_reason': reason, 'reject_reason': False})
            # a log note, not a message: followers get no mail, the employee alone is mailed below
            rec.message_post(
                body=Markup("<b>%s</b>") % Markup('<br/>').join(
                    [self.env._("Moved to Draft for correction:")] + (reason or '-').splitlines()),
                subtype_xmlid='mail.mt_note')
            self.env['hr.dms.audit.log'].log(
                'draft', reason or '', document=rec, employee=rec.employee_id,
                category=rec.category_id, confidential=rec.confidential)
            rec._send_correction_mail(reason)

    def _send_correction_mail(self, reason):
        """Queue a mail to the employee alone (Settings > Technical > Emails). Deliberately not a
        chatter post, which would also notify every follower of the document."""
        self.ensure_one()
        emp = self.sudo().employee_id
        mail = queue_correction_mail(
            self, emp,
            title=self.env._("Document correction needed: %s", self.name),
            intro=self.env._("HR has moved one of your documents back to Draft so you can correct it."),
            rows=[(self.env._("Employee"), emp.name),
                  (self.env._("Document"), self.name),
                  (self.env._("Category"), self.sudo().category_id.name),
                  (self.env._("Status"), self.env._("Draft (open for correction)"))],
            reason=reason,
            url=f"/odoo/hr.dms.document/{self.id}",
            button=self.env._("Open the document"),
            action_text=self.env._("Please update the document and click Submit again."))
        if not mail:
            self.message_post(body=self.env._(
                "Moved to Draft, but %s has no work email, so no mail was sent.", emp.name))
        return mail

    def action_approve(self):
        self._require_approver()
        for rec in self:
            if rec.state not in ('submitted', 'rejected'):
                raise UserError(self.env._("Only a Submitted document can be approved: '%s' is in Draft.", rec.name))
            rec.sudo().write({'state': 'approved', 'approved_by': self.env.uid,
                              'approved_date': fields.Datetime.now(), 'reject_reason': False,
                              'correction_reason': False})
            self.env['hr.dms.audit.log'].log(
                'approve', '', document=rec, employee=rec.employee_id,
                category=rec.category_id, confidential=rec.confidential)

    def action_reject(self, reason):
        self._require_approver()
        for rec in self:
            if rec.state not in ('submitted', 'approved'):
                raise UserError(self.env._("Only a Submitted or Approved document can be rejected: '%s' is not.", rec.name))
            rec.sudo().write({'state': 'rejected', 'reject_reason': reason,
                              'approved_by': self.env.uid, 'approved_date': fields.Datetime.now()})
            # a log note, like Move to Draft: the reason stays in the chatter, followers are not mailed
            rec.message_post(
                body=Markup("<b>%s</b>") % Markup('<br/>').join(
                    [self.env._("Rejected:")] + (reason or '-').splitlines()),
                subtype_xmlid='mail.mt_note')
            self.env['hr.dms.audit.log'].log(
                'reject', reason or '', document=rec, employee=rec.employee_id,
                category=rec.category_id, confidential=rec.confidential)

    def action_open_reject_wizard(self):
        self._require_approver()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Reject Document'),
            'res_model': 'hr.dms.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_document_ids': [(6, 0, self.ids)]},
        }

