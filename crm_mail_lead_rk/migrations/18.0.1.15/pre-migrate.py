# -*- coding: utf-8 -*-
"""18.0.1.15: the "Mail Lead Alert Tags" user field is gone.

Its two user-form extension views must leave the database BEFORE the module's
data loads: writing the security groups re-validates base.view_users_form, and
the stale views would still reference the removed field and abort the upgrade.
"""

XMLIDS = ('view_users_form_crm_mail_lead_alerts',
          'view_users_form_simple_modif_crm_mail_lead_alerts')


def migrate(cr, version):
    cr.execute("""
        SELECT id, res_id FROM ir_model_data
         WHERE module = 'crm_mail_lead_rk' AND model = 'ir.ui.view'
           AND name IN %s
    """, (XMLIDS,))
    rows = cr.fetchall()
    if not rows:
        return
    cr.execute("DELETE FROM ir_ui_view WHERE id IN %s",
               (tuple(r[1] for r in rows),))
    cr.execute("DELETE FROM ir_model_data WHERE id IN %s",
               (tuple(r[0] for r in rows),))
