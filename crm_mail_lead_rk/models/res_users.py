# -*- coding: utf-8 -*-
"""Per-admin choice of which Mail Lead tags trigger an e-mail alert."""
from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    crm_mail_lead_notify_tag_ids = fields.Many2many(
        'crm.tag', 'crm_mail_lead_notify_tag_rel', 'user_id', 'tag_id',
        string='Mail Lead Alert Tags',
        help="Mail Leads Administrators get an e-mail every time a new Mail "
             "Lead arrives in a mailbox carrying one of these tags (for "
             "example DM or Einvoicing). Leave empty to receive no alerts. "
             "Has no effect for users who are not Mail Leads Administrators.")
    is_crm_mail_lead_admin = fields.Boolean(
        compute='_compute_is_crm_mail_lead_admin')

    @api.depends('groups_id')
    def _compute_is_crm_mail_lead_admin(self):
        admin_group = self.env.ref(
            'crm_mail_lead_rk.group_crm_mail_lead_admin', raise_if_not_found=False)
        for user in self:
            user.is_crm_mail_lead_admin = bool(
                admin_group and admin_group in user.groups_id)

    # Let an admin change their own alert tags from My Preferences.
    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + [
            'crm_mail_lead_notify_tag_ids', 'is_crm_mail_lead_admin']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ['crm_mail_lead_notify_tag_ids']
