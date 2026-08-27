from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ProjectProject(models.Model):
    _inherit = 'project.project'

    closure_invoice_type = fields.Selection(
        [
            ('odoo', 'Invoice Raised in Odoo'),
            ('group_company', 'Invoice Raised in Group Company'),
        ],
        string='Invoice Confirmation',
        copy=False,
    )
    closure_invoice_move_id = fields.Many2one(
        'account.move',
        string='Invoice',
        domain=[('move_type', '=', 'out_invoice')],
        copy=False,
    )
    closure_group_invoice_number = fields.Char(string='Group Company Invoice No.', copy=False)
    closure_group_invoice_date = fields.Date(string='Group Company Invoice Date', copy=False)
    closure_group_invoice_value = fields.Float(string='Group Company Invoice Value', copy=False)
    closure_group_invoice_document = fields.Binary(
        string='Group Company Invoice Document', copy=False, attachment=True
    )
    closure_group_invoice_document_name = fields.Char(string='Document Filename', copy=False)
    closure_invoice_confirmed_by = fields.Many2one(
        'res.users', string='Invoice Confirmed By', readonly=True, copy=False
    )
    closure_invoice_confirmed_date = fields.Datetime(
        string='Invoice Confirmed On', readonly=True, copy=False
    )
    closure_invoice_confirmed = fields.Boolean(
        string='Invoicing Confirmed', compute='_compute_closure_invoice_confirmed'
    )
    is_closure_pm = fields.Boolean(compute='_compute_is_closure_pm')

    _CLOSURE_INVOICE_FIELDS = {
        'closure_invoice_type', 'closure_invoice_move_id',
        'closure_group_invoice_number', 'closure_group_invoice_date',
        'closure_group_invoice_value', 'closure_group_invoice_document',
        'closure_group_invoice_document_name',
    }

    @api.depends('user_id')
    def _compute_is_closure_pm(self):
        is_admin = self.is_admin()
        for project in self:
            project.is_closure_pm = is_admin or (
                project.user_id and self.env.user == project.user_id
            )

    @api.depends(
        'closure_invoice_type', 'closure_invoice_move_id',
        'closure_group_invoice_number', 'closure_group_invoice_date',
        'closure_group_invoice_value', 'closure_group_invoice_document',
    )
    def _compute_closure_invoice_confirmed(self):
        for project in self:
            try:
                project._check_closure_invoice_confirmed()
                project.closure_invoice_confirmed = True
            except UserError:
                project.closure_invoice_confirmed = False

    @api.constrains('closure_invoice_move_id')
    def _check_closure_invoice_service_engagement(self):
        """The invoice has to bill this project. Matched on the Sale Order Line's
        project first -- that is the engagement link on the invoice now -- and on
        the invoice's own stamped engagement second, which is what retainership
        invoices carry since they are raised without a sale order line."""
        for project in self:
            invoice = project.closure_invoice_move_id
            if not invoice:
                continue
            invoice_project = (invoice.sale_order_line_id.project_id
                               or invoice.service_engagement_id)
            if invoice_project != project:
                raise ValidationError(_(
                    "Cannot link invoice '%s' to project '%s': its Sale Order Line "
                    "bills '%s'. Select an invoice whose Sale Order Line delivers "
                    "this project, or correct the invoice's Sale Order Line first."
                ) % (
                    invoice.name or invoice.display_name,
                    project.name,
                    invoice_project.name or 'no project',
                ))

    def _check_closure_invoice_confirmed(self):
        for project in self:
            if project.closure_invoice_type == 'odoo':
                if not project.closure_invoice_move_id:
                    raise UserError(_(
                        "Cannot close project '%s': select the invoice raised in Odoo "
                        "to confirm invoicing."
                    ) % project.name)
                if project.closure_invoice_move_id.state != 'posted':
                    raise UserError(_(
                        "Cannot close project '%s': the selected invoice is not posted "
                        "(still a draft or cancelled). Select a posted invoice to confirm invoicing."
                    ) % project.name)
            elif project.closure_invoice_type == 'group_company':
                missing = [
                    f for f in (
                        'closure_group_invoice_number', 'closure_group_invoice_date',
                        'closure_group_invoice_value', 'closure_group_invoice_document',
                    ) if not project[f]
                ]
                if missing:
                    raise UserError(_(
                        "Cannot close project '%s': the Project Manager must attach the "
                        "group company invoice document and enter its number, date and value."
                    ) % project.name)
            else:
                raise UserError(_(
                    "Cannot close project '%s': the Project Manager must confirm invoicing "
                    "(invoice raised in Odoo, or invoice raised in group company) before "
                    "this project can be closed."
                ) % project.name)

    def write(self, vals):
        current_user = self.env.user

        if self._CLOSURE_INVOICE_FIELDS.intersection(vals):
            is_admin = self.is_admin()
            for project in self:
                if not is_admin and not (project.user_id and current_user == project.user_id):
                    raise UserError(_(
                        "Only the Project Manager can confirm invoicing details for project '%s'."
                    ) % project.name)
            vals = dict(vals)
            vals['closure_invoice_confirmed_by'] = current_user.id
            vals['closure_invoice_confirmed_date'] = fields.Datetime.now()

        # Block any path (bulk action, kanban drag, direct stage edit) that
        # moves a project into the 'Done' stage without invoice confirmation.
        if 'stage_id' in vals and vals['stage_id']:
            new_stage = self.env['project.project.stage'].browse(vals['stage_id'])
            if new_stage.name == 'Done':
                for project in self:
                    if project.stage_id.name != 'Done':
                        project._check_closure_invoice_confirmed()

        return super().write(vals)
