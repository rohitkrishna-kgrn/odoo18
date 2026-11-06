import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

# Keep in step with MIN_SEARCH_CHARS in static/src/js/customer_search_field.js.
MIN_SEARCH_CHARS = 3
SUGGESTION_LIMIT = 8
# Approval renames a quotation in place (S07877 -> SE07877), so the prefix is
# what tells a Service Engagement apart from a Sale Order.
SE_NAME_RE = re.compile(r'^\s*SE\d')
ACCESS_GROUP = 'project_search_customer_gk.group_project_search_customer'


def _selection_label(record, field_name):
    """Label of a selection field, or '' when the field is unset or not
    installed (the custom sale.order fields come from optional modules)."""
    field = record._fields.get(field_name)
    if not field or not record[field_name]:
        return ''
    return dict(field._description_selection(record.env)).get(record[field_name], '')


def _value(record, field_name):
    """Value of an optional field, False when the field is not installed."""
    return record[field_name] if field_name in record._fields else False


class ProjectSearchCustomerWizard(models.TransientModel):
    _name = 'project.search.customer.wizard'
    _description = 'Project Customer Search'

    partner_id = fields.Many2one('res.partner', string='Customer Search')
    line_ids = fields.One2many('project.search.customer.line', 'wizard_id', string='Sale Orders / Service Engagements')
    result_count = fields.Integer()

    @api.model
    def _check_search_access(self):
        # Everything below reads with sudo, so the checkbox on the user form is
        # the only gate; enforce it here as well as on the menu.
        if not self.env.user.has_group(ACCESS_GROUP):
            raise AccessError(_("You need the 'Project Search Customer' access right to search customers."))

    @api.model
    def _customer_domain(self):
        # Customers are contacts that have been sold to, or that hold a sale
        # order (366 order-holding contacts still carry customer_rank 0).
        return ['|', ('customer_rank', '>', 0), ('sale_order_ids', '!=', False)]

    @api.model
    def search_customers(self, name, limit=SUGGESTION_LIMIT):
        """Autocomplete source for the customer field.

        Runs with sudo: Project users often hold no Sales rights, and the
        `sale_order_ids` part of the customer domain would otherwise raise.
        Searches `name` rather than `display_name`, so contact_extended_rk's
        4-letter display_name gate does not apply here."""
        self._check_search_access()
        name = (name or '').strip()
        if len(name) < MIN_SEARCH_CHARS:
            return []
        partners = self.env['res.partner'].sudo().search(
            [('name', 'ilike', name)] + self._customer_domain(),
            limit=limit, order='name, id')
        return [(partner.id, partner.display_name) for partner in partners]

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        Line = self.env['project.search.customer.line']
        lines = Line
        if self.partner_id:
            self._check_search_access()
            # sudo: every order of the customer is listed, whatever the
            # user's sale access rights and record rules say.
            orders = self.env['sale.order'].sudo().search(
                [('partner_id', 'child_of', self.partner_id.ids)],
                order='date_order desc, id desc')
            for sequence, order in enumerate(orders):
                lines |= Line.new({
                    'sequence': sequence,
                    'order_id': order.id,
                    'customer_name': order.partner_id.display_name,
                    'record_type': 'se' if SE_NAME_RE.match(order.name or '') else 'so',
                    'order_name': order.name,
                    'salesperson_name': order.user_id.name or '',
                    'is_cancelled': order.state == 'cancel',
                })
        # Assign a recordset, not commands: commands on an unsaved wizard drop rows.
        self.line_ids = lines
        self.result_count = len(lines)

    @api.model
    def action_open_order(self, order_id, partner_id=False):
        """Row click: open the real sale.order form.

        Checked as the user, with the companies currently selected in the
        switcher (they arrive in the RPC context), so the result matches what
        the form will be able to load. Only if the form would be refused (in
        practice an order of a company not selected in the switcher) does this
        fall back to the read-only preview, so the click never ends in an
        access error.

        `partner_id` is the customer picked in the search. It rides along in
        the action context, so the order form shows a "Back to Search" button
        that reopens this search with the same customer and results."""
        self._check_search_access()
        order = self.env['sale.order'].browse(int(order_id or 0))
        if not order.sudo().exists():
            raise UserError(_("This quotation no longer exists."))
        if order.has_access('read'):
            return {
                'type': 'ir.actions.act_window',
                'name': order.sudo().name,
                'res_model': 'sale.order',
                'res_id': order.id,
                'views': [(False, 'form')],
                'target': 'current',
                'context': {'psc_back_partner_id': int(partner_id)} if partner_id else {},
            }
        return {'preview_id': self.action_preview_order(order.id)}

    @api.model
    def action_preview_order(self, order_id):
        """Build a read-only copy of the quotation and return its id.

        The web client cannot open sale.order itself with sudo, and Project
        users may lack the sale ACLs the real form needs, so the order is
        copied into a transient preview record the user can always read."""
        self._check_search_access()
        order = self.env['sale.order'].sudo().browse(int(order_id or 0)).exists()
        if not order:
            raise UserError(_("This quotation no longer exists."))
        return self.env['project.search.customer.preview'].create(
            self.env['project.search.customer.preview']._prepare_from_order(order)).id


class ProjectSearchCustomerLine(models.TransientModel):
    _name = 'project.search.customer.line'
    _description = 'Project Customer Search Result'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('project.search.customer.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer()
    # A plain integer, not a Many2one: the user may have no read access to
    # sale.order at all, and the preview is fetched with sudo from this id.
    order_id = fields.Integer(readonly=True)
    customer_name = fields.Char(string='Customer Name', readonly=True)
    record_type = fields.Selection([('so', 'SO'), ('se', 'SE')], string='Type', readonly=True)
    order_name = fields.Char(string='SO / SE Number', readonly=True)
    salesperson_name = fields.Char(string='Salesperson Name', readonly=True)
    is_cancelled = fields.Boolean(readonly=True)


class ProjectSearchCustomerPreview(models.TransientModel):
    """Read-only snapshot of one sale.order, built with sudo."""
    _name = 'project.search.customer.preview'
    _description = 'Project Customer Search - Quotation Preview'

    order_name = fields.Char(string='Number', readonly=True)
    record_type = fields.Selection([('so', 'Sale Order'), ('se', 'Service Engagement')], string='Type', readonly=True)
    state_label = fields.Char(string='Status', readonly=True)
    approval_label = fields.Char(string='Approval Status', readonly=True)
    customer_name = fields.Char(string='Customer', readonly=True)
    invoice_address = fields.Char(string='Invoice Address', readonly=True)
    client_order_ref = fields.Char(string='Customer Reference', readonly=True)
    crm_pipeline_name = fields.Char(string='CRM Pipeline', readonly=True)
    tag_names = fields.Char(string='Tags', readonly=True)
    new_renewed_label = fields.Char(string='New / Renewed', readonly=True)
    billable_type_label = fields.Char(string='Billing Type', readonly=True)
    salesperson_name = fields.Char(string='Salesperson', readonly=True)
    team_name = fields.Char(string='Sales Team', readonly=True)
    date_order = fields.Datetime(string='Order Date', readonly=True)
    validity_date = fields.Date(string='Expiration', readonly=True)
    payment_term_name = fields.Char(string='Payment Terms', readonly=True)
    se_effective_date = fields.Date(string='Effective Date', readonly=True)
    se_project_duration = fields.Char(string='Engagement Duration', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    amount_untaxed = fields.Monetary(string='Untaxed Amount', readonly=True)
    amount_tax = fields.Monetary(string='Taxes', readonly=True)
    amount_total = fields.Monetary(string='Total', readonly=True)
    note = fields.Html(string='Terms and Conditions', readonly=True, sanitize=False)
    line_ids = fields.One2many('project.search.customer.preview.line', 'preview_id', string='Order Lines', readonly=True)

    @api.model
    def _prepare_from_order(self, order):
        """`order` must already be sudo()."""
        crm_pipeline = _value(order, 'crm_pipeline_id')
        tags = _value(order, 'tag_ids')
        return {
            'order_name': order.name,
            'record_type': 'se' if SE_NAME_RE.match(order.name or '') else 'so',
            'state_label': _selection_label(order, 'state'),
            'approval_label': _selection_label(order, 'approval_state'),
            'customer_name': order.partner_id.display_name or '',
            'invoice_address': order.partner_invoice_id.display_name or '',
            'client_order_ref': order.client_order_ref or '',
            'crm_pipeline_name': crm_pipeline.display_name if crm_pipeline else '',
            'tag_names': ', '.join(tags.mapped('name')) if tags else '',
            'new_renewed_label': _selection_label(order, 'new_renewed'),
            'billable_type_label': _selection_label(order, 'billable_type'),
            'salesperson_name': order.user_id.name or '',
            'team_name': order.team_id.name or '',
            'date_order': order.date_order,
            'validity_date': order.validity_date,
            'payment_term_name': order.payment_term_id.name or '',
            'se_effective_date': _value(order, 'se_effective_date'),
            'se_project_duration': _value(order, 'se_project_duration') or '',
            'currency_id': order.currency_id.id,
            'amount_untaxed': order.amount_untaxed,
            'amount_tax': order.amount_tax,
            'amount_total': order.amount_total,
            'note': order.note,
            'line_ids': [
                fields.Command.create(self.env['project.search.customer.preview.line']._prepare_from_order_line(line))
                for line in order.order_line
            ],
        }


class ProjectSearchCustomerPreviewLine(models.TransientModel):
    _name = 'project.search.customer.preview.line'
    _description = 'Project Customer Search - Quotation Preview Line'
    _order = 'sequence, id'

    preview_id = fields.Many2one('project.search.customer.preview', required=True, ondelete='cascade')
    sequence = fields.Integer()
    # Same names as sale.order.line, so the section_and_note list widget works.
    display_type = fields.Selection([('line_section', 'Section'), ('line_note', 'Note')], readonly=True)
    name = fields.Text(string='Description', readonly=True)
    product_name = fields.Char(string='Product', readonly=True)
    product_uom_qty = fields.Float(string='Quantity', digits='Product Unit of Measure', readonly=True)
    uom_name = fields.Char(string='Unit', readonly=True)
    price_unit = fields.Float(string='Unit Price', digits='Product Price', readonly=True)
    discount = fields.Float(string='Disc.%', digits='Discount', readonly=True)
    tax_names = fields.Char(string='Taxes', readonly=True)
    currency_id = fields.Many2one(related='preview_id.currency_id')
    price_subtotal = fields.Monetary(string='Amount', readonly=True)
    engagement_start = fields.Date(readonly=True)
    engagement_end = fields.Date(readonly=True)
    manager_name = fields.Char(string='Manager', readonly=True)
    project_name = fields.Char(string='Linked Project', readonly=True)

    @api.model
    def _prepare_from_order_line(self, line):
        manager = _value(line, 'manager_id')
        project = _value(line, 'project_id')
        return {
            'sequence': line.sequence,
            'display_type': line.display_type or False,
            'name': line.name,
            'product_name': line.product_id.display_name or '',
            'product_uom_qty': line.product_uom_qty,
            'uom_name': line.product_uom.name or '',
            'price_unit': line.price_unit,
            'discount': line.discount,
            'tax_names': ', '.join(line.tax_id.mapped('name')),
            'price_subtotal': line.price_subtotal,
            'engagement_start': _value(line, 'engagement_start'),
            'engagement_end': _value(line, 'engagement_end'),
            'manager_name': manager.name if manager else '',
            'project_name': project.display_name if project else '',
        }
