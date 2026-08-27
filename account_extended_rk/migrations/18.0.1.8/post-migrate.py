"""Backfill the derived invoice type on existing customer documents.

Invoice Type stopped being a dropdown and is now read off the document itself.
Existing rows were entered (or left blank) under the old rules, so classify
them all in one pass with the same precedence the compute uses: credit note by
move type, then retainer by contract link, then advance by flag, otherwise
completion.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE account_move
           SET invoice_type_classification = CASE
                   WHEN move_type = 'out_refund' THEN 'credit_note'
                   WHEN retainership_contract_id IS NOT NULL THEN 'retainer'
                   WHEN advance_invoice THEN 'advance'
                   ELSE 'completion'
               END
         WHERE move_type IN ('out_invoice', 'out_refund')
    """)
    # Anything that is not a customer document has no classification.
    cr.execute("""
        UPDATE account_move
           SET invoice_type_classification = NULL
         WHERE move_type NOT IN ('out_invoice', 'out_refund')
           AND invoice_type_classification IS NOT NULL
    """)
