from odoo import api, fields, models
from odoo.exceptions import AccessError

CONTENT_FIELDS = {'datas', 'raw', 'db_datas'}


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    hr_dms_expiry_date = fields.Date(string='Expiry Date', help="Expiry of an HR document file (visa, ID, licence).")

    def _hr_dms_guard(self):
        """Attachments of HR documents never get a share token and obey the download rule.
        Returns the documents the attachments belong to, files of the Files field and chatter alike."""
        ids = self.ids
        if not ids:
            return self.browse()
        self.env.cr.execute(
            "SELECT res_id FROM ir_attachment WHERE id IN %s AND res_model = 'hr.dms.document' "
            "AND res_id IS NOT NULL", [tuple(ids)])
        return self.env['hr.dms.document'].browse([r[0] for r in self.env.cr.fetchall()]).exists()

    @api.model
    def check(self, mode, values=None):
        res = super().check(mode, values)
        if self.env.su:
            return res
        if mode == 'read':
            self._hr_dms_guard()._check_download()
        return res

    def _read_format(self, fnames, load='_classic_read'):
        # name/mimetype stay readable (the Files widget lists them); the content obeys the download rule
        if not self.env.su and not self.env.context.get('bin_size') and (not fnames or CONTENT_FIELDS & set(fnames)):
            self._hr_dms_guard()._check_download(log=False)
        return super()._read_format(fnames, load)

    def generate_access_token(self):
        if self._hr_dms_guard():
            raise AccessError(self.env._("HR documents cannot be shared through links."))
        return super().generate_access_token()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('res_model') == 'hr.dms.document':
                if vals.get('access_token') or vals.get('public'):
                    raise AccessError(self.env._("HR documents cannot be shared through links."))
        return super().create(vals_list)

    def _hr_dms_check_manage(self, vals=None):
        # write access on the document lets an employee add files, not rewrite or delete saved ones;
        # the per-file expiry date is the exception: whoever may edit the document, or added that file
        docs = self._hr_dms_guard() if not self.env.su else None
        if not docs or self.env.user.has_group('hr_dms.group_hr_dms_manager'):
            return
        if vals is not None and set(vals) <= {'hr_dms_expiry_date'} and (
                all(docs.mapped('can_edit'))
                or (all(docs.mapped('can_add_files')) and set(self.sudo().mapped('create_uid').ids) == {self.env.uid})):
            return
        raise AccessError(self.env._("Only HR Managers and Administrators can change or remove an uploaded file."))

    def write(self, vals):
        if ('access_token' in vals and vals['access_token']) or vals.get('public'):
            if self._hr_dms_guard():
                raise AccessError(self.env._("HR documents cannot be shared through links."))
        self._hr_dms_check_manage(vals)
        return super().write(vals)

    def unlink(self):
        self._hr_dms_check_manage()
        return super().unlink()
