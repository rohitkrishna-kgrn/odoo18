import ast

from odoo import models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def open_debit_note_ledger_action(self):
        """Dashboard "View > Debit Notes" — the ledger, scoped to this journal.

        The core `open_action` cannot serve this: it hard-prefixes the action
        name with "account.", so it can only open actions from that module.
        """
        self.ensure_one()
        xml_id = (
            'debit_note_ledger.action_customer_debit_note_ledger'
            if self.type == 'sale'
            else 'debit_note_ledger.action_vendor_debit_note_ledger'
        )
        action = self.env['ir.actions.act_window']._for_xml_id(xml_id)

        domain = action.get('domain') or []
        if isinstance(domain, str):
            domain = ast.literal_eval(domain)
        action['domain'] = domain + [('journal_id', '=', self.id)]

        context = action.get('context') or {}
        if isinstance(context, str):
            context = ast.literal_eval(context)
        context['default_journal_id'] = self.id
        action['context'] = context
        return action

    def _get_move_action_context(self):
        """Dashboard "New > Debit Note" — flag the move the wizard would flag."""
        ctx = super()._get_move_action_context()
        if ctx.get('debit_note'):
            ctx['default_is_debit_note'] = True
        return ctx

    def _fill_sale_purchase_dashboard_data(self, dashboard_data):
        """Add the Debit Notes counter to the sale and purchase journal cards."""
        super()._fill_sale_purchase_dashboard_data(dashboard_data)
        journals = self.filtered(
            lambda j: j.type in ('sale', 'purchase') and j.id in dashboard_data)
        if not journals:
            return

        groups = self.env['account.move']._read_group(
            domain=[
                ('journal_id', 'in', journals.ids),
                ('move_type', 'in', ('out_invoice', 'in_invoice')),
                ('state', '!=', 'cancel'),
                '|', ('debit_origin_id', '!=', False), ('is_debit_note', '=', True),
            ],
            groupby=['journal_id'],
            aggregates=['__count', 'amount_total_signed:sum'],
        )
        totals = {j.id: (count, total) for j, count, total in groups}

        for journal in journals:
            count, total = totals.get(journal.id, (0, 0.0))
            # User may have read access on the journal but not on the company.
            currency = journal.currency_id or self.env['res.currency'].browse(
                journal.company_id.sudo().currency_id.id)
            dashboard_data[journal.id].update({
                'number_debit_note': count,
                # amount_total_signed runs negative on the vendor side; the card
                # reads as a value, so show it positive like the ledger does.
                'sum_debit_note': currency.format(
                    total * (1 if journal.type == 'sale' else -1)),
            })
