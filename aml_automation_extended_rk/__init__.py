from . import models
from . import wizards
from . import controllers


def _ensure_additional_docs_wizard_access(env):
    """Create ir.model.access entries for the two new wizard models.

    Called from both post_init_hook (fresh install) and the upgrade migration
    script, so access rules exist regardless of whether the XML data file's
    `ref` lookups were resolved during the data-loading phase.
    """
    group = env.ref('aml_automation_extended_rk.group_aml_user', raise_if_not_found=False)
    if not group:
        return
    wizard_models = [
        ('aml.additional.docs.wizard', 'aml.additional.docs.wizard.user'),
        ('aml.additional.docs.wizard.line', 'aml.additional.docs.wizard.line.user'),
    ]
    for model_name, access_name in wizard_models:
        model = env['ir.model'].search([('model', '=', model_name)], limit=1)
        if not model:
            continue
        already = env['ir.model.access'].search([
            ('model_id', '=', model.id),
            ('group_id', '=', group.id),
        ], limit=1)
        if not already:
            env['ir.model.access'].create({
                'name': access_name,
                'model_id': model.id,
                'group_id': group.id,
                'perm_read': True,
                'perm_write': True,
                'perm_create': True,
                'perm_unlink': True,
            })


def post_init_hook(env):
    _ensure_additional_docs_wizard_access(env)
