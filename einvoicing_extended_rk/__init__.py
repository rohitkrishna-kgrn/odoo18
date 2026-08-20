from . import models
from . import controllers
from . import wizard


def post_init_hook(env):
    """Seed the code mappings that make the field map usable out of the box.

    Both mappings are data the platform needs and Odoo has no equivalent for:
    the PINT-AE emirate codes differ from the l10n_ae state codes, and Odoo's
    units of measure carry no UN/ECE Rec 20 code at all.
    """
    from .models import einvoice_lookups as lk

    states = env['res.country.state'].search(
        [('country_id.code', '=', 'AE'), ('einv_emirate_code', '=', False)])
    for state in states:
        code = lk.ODOO_STATE_TO_EMIRATE.get((state.code or '').upper())
        if code:
            state.einv_emirate_code = code

    for xmlid, unece in lk.DEFAULT_UOM_UNECE_CODES.items():
        uom = env.ref(xmlid, raise_if_not_found=False)
        if uom:
            uom.einv_unece_code = unece
