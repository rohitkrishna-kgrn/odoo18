from odoo import fields, models


class ClientHelpdeskStage(models.Model):
    _name = 'client.helpdesk.stage'
    _description = 'Helpdesk Stage'
    _order = 'sequence, id'

    name = fields.Char('Stage Name', required=True, translate=True)
    sequence = fields.Integer('Sequence', default=10)
    fold = fields.Boolean('Folded in Kanban', default=False)
    is_closed = fields.Boolean('Closing Stage', default=False,
        help='Tickets in this stage are considered closed.')
    description = fields.Text('Stage Description')

    ticket_ids = fields.One2many('client.helpdesk.ticket', 'stage_id', string='Tickets')
    ticket_count = fields.Integer('Ticket Count', compute='_compute_ticket_count')

    def _compute_ticket_count(self):
        data = self.env['client.helpdesk.ticket'].read_group(
            [('stage_id', 'in', self.ids)],
            ['stage_id'],
            ['stage_id'],
        )
        count_map = {d['stage_id'][0]: d['stage_id_count'] for d in data}
        for stage in self:
            stage.ticket_count = count_map.get(stage.id, 0)
