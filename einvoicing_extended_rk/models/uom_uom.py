# -*- coding: utf-8 -*-
from odoo import api, fields, models

from . import einvoice_lookups as lk


class UomUom(models.Model):
    _inherit = 'uom.uom'

    einv_unece_code = fields.Char(
        string='UN/ECE Rec 20 Code', default='C62',
        help='Unit of measure code sent on the invoice line. C62 (one) is the '
             'platform default; HUR is hours, DAY days, KGM kilograms.',
    )

    @api.model
    def _einv_set_unece_codes(self):
        """Stamp the UN/ECE code onto whichever stock units this database has.

        Resolved with ``raise_if_not_found=False`` because a database may have
        deleted or archived some of the units Odoo ships.
        """
        for xml_id, code in lk.DEFAULT_UOM_UNECE_CODES.items():
            uom = self.env.ref(xml_id, raise_if_not_found=False)
            if uom and not uom.einv_unece_code:
                uom.einv_unece_code = code
        return True
