# -*- coding: utf-8 -*-
"""Retarget the fetch cron from every 5 minutes to every 2 minutes.

The cron row was created inside ``<data noupdate="1">``, so its
``ir_model_data.noupdate`` flag is ``true`` and a plain ``-u`` never touches it
no matter what ``data/ir_cron_data.xml`` now says. Force the new cadence here.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_cron c
           SET interval_number = 2,
               interval_type = 'minutes'
          FROM ir_model_data d
         WHERE d.model = 'ir.cron'
           AND d.module = 'crm_mail_lead_rk'
           AND d.name = 'ir_cron_crm_mail_lead_fetch'
           AND d.res_id = c.id
    """)
