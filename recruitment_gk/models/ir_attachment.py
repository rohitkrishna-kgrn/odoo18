from odoo import models


class IrAttachmentRecruitment(models.Model):
    _inherit = 'ir.attachment'

    def _is_recruitment_user(self):
        return (
            self.env.user.has_group('recruitment_gk.group_recruitment_hr_admin')
            or self.env.user.has_group('recruitment_gk.group_recruitment_hiring_manager')
            or self.env.user.has_group('recruitment_gk.group_recruitment_management')
        )

    def check(self, mode, values=None):
        if mode == 'read' and self._is_recruitment_user():
            return
        super().check(mode, values=values)

    def read(self, fields=None, load='_classic_read'):
        if self._is_recruitment_user():
            return super(IrAttachmentRecruitment, self.sudo()).read(
                fields=fields, load=load
            )
        return super().read(fields=fields, load=load)
