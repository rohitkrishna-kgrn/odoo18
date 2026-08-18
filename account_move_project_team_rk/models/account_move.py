# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    project_manager_ids = fields.Many2many(
        'res.users',
        'account_move_project_manager_rel', 'move_id', 'user_id',
        string='Project Manager',
        compute='_compute_project_manager_ids', store=True,
        help="Managers set on the sale order lines this invoice bills.")

    project_team_member_ids = fields.Many2many(
        'res.users',
        string='Team Member',
        compute='_compute_project_team_member_ids',
        help="Team members on the still-open tasks of the projects linked to "
             "this invoice's sale orders.")

    @api.depends('invoice_line_ids.sale_line_ids.manager_id')
    def _compute_project_manager_ids(self):
        for move in self:
            move.project_manager_ids = move.invoice_line_ids.sale_line_ids.manager_id

    def _compute_project_team_member_ids(self):
        """Invoice -> sale orders -> projects -> open tasks -> team members.

        A project is tied to an order three ways in this database: the project's
        own Sales Order field, the task's Sales Order field, or the sale order
        line the task was generated from. All three are followed, otherwise the
        column stays empty for almost every invoice — only a handful of projects
        carry project.sale_order_id, while thousands of tasks carry sale_line_id.

        Not stored: it tracks the *currently* open tasks, and there is no ORM
        dependency path from an invoice down to them. Resolved in one search for
        the whole batch so the list view stays cheap.
        """
        orders_by_move = {
            move: move.invoice_line_ids.sale_line_ids.order_id for move in self}
        order_ids = set().union(*[o.ids for o in orders_by_move.values()]) if self else set()
        if not order_ids:
            for move in self:
                move.project_team_member_ids = [(5, 0, 0)]
            return

        order_ids = list(order_ids)
        tasks = self.env['project.task'].search([
            ('is_closed', '=', False),
            ('team_member_ids', '!=', False),
            '|', '|',
            ('project_id.sale_order_id', 'in', order_ids),
            ('sale_order_id', 'in', order_ids),
            ('sale_line_id.order_id', 'in', order_ids),
        ])

        members_by_order = {}
        for task in tasks:
            for order in (task.project_id.sale_order_id, task.sale_order_id,
                          task.sale_line_id.order_id):
                if order and order.id in order_ids:
                    members_by_order.setdefault(order.id, set()).update(
                        task.team_member_ids.ids)

        for move in self:
            member_ids = set()
            for order in orders_by_move[move]:
                member_ids |= members_by_order.get(order.id, set())
            move.project_team_member_ids = [(6, 0, list(member_ids))]
