from odoo import _, api, models
from odoo.exceptions import UserError


class CrmStage(models.Model):
    _inherit = 'crm.stage'

    @api.model_create_multi
    def create(self, vals_list):
        # The pipeline stages are fixed: the lead filters and the statusbar in
        # crm_lead_views.xml match on stage names, so an ad-hoc stage added
        # from the kanban "+" or the stage quick-create silently breaks them.
        # Only module data loading (data/crm_stage_data.xml) may add stages.
        if not self.env.context.get('install_module'):
            raise UserError(_(
                "Creating new CRM stages is not allowed.\n\n"
                "The pipeline stages are fixed: %s.",
                ", ".join(self.search([]).mapped('name')),
            ))
        return super().create(vals_list)
