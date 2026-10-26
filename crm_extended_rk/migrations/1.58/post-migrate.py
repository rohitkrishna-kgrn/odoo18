# -*- coding: utf-8 -*-
"""1.58: the Entities list shows the row's own name only.

Until now a quotation with a discovery form showed the linked form entity in
the Entity Name column, so a linked row with a blank `name` still looked named.
That column is gone - copy the linked entity's name onto any such row so it does
not turn up blank.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE sale_order_entity e
           SET name = d.name
          FROM crm_lead_discovery_entity d
         WHERE d.id = e.discovery_entity_id
           AND COALESCE(TRIM(e.name), '') = ''
    """)
