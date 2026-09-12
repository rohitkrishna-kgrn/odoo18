# -*- coding: utf-8 -*-
def migrate(cr, version):
    """Re-assert that the two customer-invoice report actions are invoice
    reports.

    On this database `account.account_invoices.is_invoice_report` had been set
    to False, which makes `account.move.send._check_invoice_report()` raise
    "The sending of invoices is not set up properly" and blocks every
    Send & Print. The data file sets it again, but force it here too in case an
    ir_model_data noupdate flag skips the record write.
    """
    cr.execute("""
        UPDATE ir_act_report_xml r
           SET is_invoice_report = TRUE,
               report_file = 'template_rk.report_invoice_template_rk'
          FROM ir_model_data d
         WHERE d.model = 'ir.actions.report'
           AND d.res_id = r.id
           AND d.module = 'account'
           AND d.name IN ('account_invoices', 'account_invoices_without_payment')
    """)
