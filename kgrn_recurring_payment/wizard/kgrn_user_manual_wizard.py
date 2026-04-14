from odoo import models


class KgrnUserManualWizard(models.TransientModel):
    """Displays the KGRN Recurring Payment user manual.
    The actual content lives entirely in the view XML."""

    _name = 'kgrn.user.manual.wizard'
    _description = 'KGRN Recurring Payment – User Manual'

    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}
