from odoo import models, fields, api, _


class RecruitmentInterviewConfig(models.Model):
    _name = 'recruitment.interview.config'
    _description = 'Interview Round Configuration'

    name = fields.Char('Configuration Name', required=True, default='Default Configuration')
    active = fields.Boolean(default=True)
    round_ids = fields.One2many(
        'recruitment.round.config', 'config_id', 'Interview Rounds',
    )

    def action_apply_config(self):
        """Update interview pipeline stages from this configuration (upsert by name)."""
        for config in self:
            rounds_sorted = config.round_ids.sorted('sequence')
            existing = self.env['recruitment.stage'].search(
                [('stage_type', '=', 'interview')]
            )
            existing_by_name = {s.name: s for s in existing}
            processed_ids = []
            base_seq = 30

            for idx, rnd in enumerate(rounds_sorted):
                seq = base_seq + idx * 10
                if rnd.name in existing_by_name:
                    stage = existing_by_name[rnd.name]
                    stage.write({'sequence': seq, 'round_number': rnd.sequence})
                else:
                    stage = self.env['recruitment.stage'].create({
                        'name': rnd.name,
                        'sequence': seq,
                        'stage_type': 'interview',
                        'round_number': rnd.sequence,
                    })
                processed_ids.append(stage.id)

            # Remove stages not present in this config
            existing.filtered(lambda s: s.id not in processed_ids).unlink()

            # Re-sequence terminal stages
            terminal_seq = base_seq + len(rounds_sorted) * 10
            for stype, offset in [
                ('final_evaluation', 0),
                ('selected', 10),
                ('rejected', 20),
            ]:
                stage = self.env['recruitment.stage'].search(
                    [('stage_type', '=', stype)], limit=1
                )
                if stage:
                    stage.sequence = terminal_seq + offset

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Configuration Applied'),
                'message': _('Interview pipeline stages updated successfully.'),
                'type': 'success',
                'sticky': False,
            },
        }


class RecruitmentRoundConfig(models.Model):
    _name = 'recruitment.round.config'
    _description = 'Interview Round Configuration Item'
    _order = 'sequence, id'

    _sql_constraints = [
        ('unique_name_per_config', 'UNIQUE(config_id, name)',
         'Round names must be unique within a configuration.'),
    ]

    config_id = fields.Many2one(
        'recruitment.interview.config', 'Configuration',
        required=True, ondelete='cascade',
    )
    sequence = fields.Integer('Sequence', default=10)
    name = fields.Char('Round Name', required=True)
