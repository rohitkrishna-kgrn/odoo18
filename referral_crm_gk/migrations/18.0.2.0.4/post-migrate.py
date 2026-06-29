from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """
    v2.0.4: Accounting invoice integration.

    - Recompute x_payment_status on all referral leads (field is now computed
      from the linked invoice; leads without an invoice stay 'pending').
    - Recompute state on all referral commissions (now driven by invoice
      payment_state via the lead).
    - Auto-link existing invoices to leads where the sale order already has
      confirmed invoices and the lead has no invoice linked yet.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1. Auto-link existing invoices ─ for leads whose SO already has invoices
    leads_with_so = env['crm.lead'].search([
        ('x_is_referral', '=', True),
        ('x_sale_order_id', '!=', False),
        ('x_invoice_id', '=', False),
    ])
    for lead in leads_with_so:
        so = lead.x_sale_order_id
        invoices = so.invoice_ids.filtered(
            lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
        )
        if invoices:
            lead.x_invoice_id = invoices[0].id

    # 2. Recompute payment status on all referral leads
    referral_leads = env['crm.lead'].search([('x_is_referral', '=', True)])
    referral_leads._compute_payment_status()

    # 3. Recompute commission states
    commissions = env['referral.commission'].search([])
    commissions._compute_state_from_invoice()
