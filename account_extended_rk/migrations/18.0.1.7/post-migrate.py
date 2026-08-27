"""Backfill the service engagement from the Sale Order Line.

The engagement is no longer picked by hand on the invoice form — it is derived
from the sale order line the invoice bills against. Existing customer invoices
were entered before that, so point them at their line's project in one pass.
Invoices that already carry an engagement are left alone.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE account_move am
           SET service_engagement_id = sol.project_id
          FROM sale_order_line sol
         WHERE sol.id = am.sale_order_line_id
           AND sol.project_id IS NOT NULL
           AND am.service_engagement_id IS NULL
           AND am.move_type IN ('out_invoice', 'out_refund')
    """)
