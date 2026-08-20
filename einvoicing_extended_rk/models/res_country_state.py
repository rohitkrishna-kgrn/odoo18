# -*- coding: utf-8 -*-
from odoo import api, fields, models

from . import einvoice_lookups as lk


class ResCountryState(models.Model):
    """Map the l10n_ae state codes onto the PINT-AE emirate codes.

    Odoo ships the emirates as AZ / DU / SH / AJ / UQ / RK / FU while PINT-AE
    expects AUH / DXB / SHJ / AJM / UAQ / RAK / FUJ, so the two cannot be used
    interchangeably.
    """
    _inherit = 'res.country.state'

    einv_emirate_code = fields.Selection(
        lk.EMIRATE_CODES, string='PINT-AE Emirate Code',
        help='Country subdivision code sent for addresses in this state.',
    )

    @api.model
    def _einv_set_emirate_codes(self):
        """Stamp the PINT-AE code onto whichever emirate records exist.

        Done in code rather than as data records because the l10n_ae states
        are created per company chart installation, so their xml ids are not
        dependable — and a database may carry duplicates (both ``RK`` and
        ``RAK`` for Ras Al Khaimah, for instance).
        """
        uae = self.env['res.country'].search([('code', '=', 'AE')], limit=1)
        if not uae:
            return True
        states = self.with_context(active_test=False).search([('country_id', '=', uae.id)])
        for state in states:
            code = lk.ODOO_STATE_TO_EMIRATE.get((state.code or '').upper())
            if code and not state.einv_emirate_code:
                state.einv_emirate_code = code
        return True
