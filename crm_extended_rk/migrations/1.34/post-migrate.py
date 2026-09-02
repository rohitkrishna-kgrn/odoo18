# -*- coding: utf-8 -*-
"""Mark the counts already read from the discovery form as entered.

The two annual invoice counts used to be shown whenever the row matched the
form. They now hang off their own per-column flags, so that a count typed by
hand can sit next to one that is still unknown - and an unset column stays
blank instead of reading as "zero invoices a year". A row matched before this
version has both numbers from the form, so both flags are set; every other
state carries no counts at all.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE sale_order_entity
           SET inbound_count_set = TRUE,
               outbound_count_set = TRUE
         WHERE discovery_state = 'matched'
    """)
