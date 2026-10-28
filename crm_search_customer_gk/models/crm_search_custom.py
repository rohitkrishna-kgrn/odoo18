import re

from odoo import api, fields, models

# Keep in step with MIN_SEARCH_CHARS in static/src/js/customer_search_field.js.
MIN_SEARCH_CHARS = 3
SUGGESTION_LIMIT = 8
# Approval renames a quotation in place (S07877 -> SE07877), so the prefix is
# what tells a Service Engagement apart from a Sale Order.
SE_NAME_RE = re.compile(r'^\s*SE\d')


class CrmSearchCustomWizard(models.TransientModel):
    _name = 'crm.search.custom.wizard'
    _description = 'CRM Customer Search'

    partner_id = fields.Many2one('res.partner', string='Customer Search')
    line_ids = fields.One2many('crm.search.custom.line', 'wizard_id', string='Sale Orders / Service Engagements')
    result_count = fields.Integer()

    @api.model
    def _customer_domain(self):
        # Customers are contacts that have been sold to, or that hold a sale
        # order (366 order-holding contacts still carry customer_rank 0).
        return ['|', ('customer_rank', '>', 0), ('sale_order_ids', '!=', False)]

    @api.model
    def search_customers(self, name, limit=SUGGESTION_LIMIT):
        """Autocomplete source for the customer field.

        Searches `name` rather than `display_name`, so contact_extended_rk's
        4-letter display_name gate does not apply here; the search still runs
        as the current user, under their record rules."""
        name = (name or '').strip()
        if len(name) < MIN_SEARCH_CHARS:
            return []
        partners = self.env['res.partner'].search(
            [('name', 'ilike', name)] + self._customer_domain(),
            limit=limit, order='name, id')
        return [(partner.id, partner.display_name) for partner in partners]

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        Line = self.env['crm.search.custom.line']
        lines = Line
        if self.partner_id:
            # No sudo: sale.order record rules decide what this user may see.
            orders = self.env['sale.order'].search(
                [('partner_id', 'child_of', self.partner_id.ids)],
                order='date_order desc, id desc')
            for sequence, order in enumerate(orders):
                lines |= Line.new({
                    'sequence': sequence,
                    'customer_name': order.partner_id.display_name,
                    'record_type': 'se' if SE_NAME_RE.match(order.name or '') else 'so',
                    'order_name': order.name,
                    'salesperson_name': order.user_id.name or '',
                    'is_cancelled': order.state == 'cancel',
                })
        # Assign a recordset, not commands: commands on an unsaved wizard drop rows.
        self.line_ids = lines
        self.result_count = len(lines)


class CrmSearchCustomLine(models.TransientModel):
    _name = 'crm.search.custom.line'
    _description = 'CRM Customer Search Result'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('crm.search.custom.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer()
    customer_name = fields.Char(string='Customer Name', readonly=True)
    record_type = fields.Selection([('so', 'SO'), ('se', 'SE')], string='Type', readonly=True)
    order_name = fields.Char(string='SO / SE Number', readonly=True)
    salesperson_name = fields.Char(string='Salesperson Name', readonly=True)
    is_cancelled = fields.Boolean(readonly=True)
