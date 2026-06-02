from odoo import api, SUPERUSER_ID
from odoo.addons.aml_automation_extended_rk import _ensure_additional_docs_wizard_access


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _ensure_additional_docs_wizard_access(env)
