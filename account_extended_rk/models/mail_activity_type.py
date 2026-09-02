from odoo import api, models, fields

from .account_followup_log import FOLLOWUP_METHODS


class MailActivityType(models.Model):
    _inherit = 'mail.activity.type'

    # An activity marked done on a customer invoice is a logged follow-up, and
    # this is what says which kind. Explicit rather than sniffed from the type
    # name at report time: "Client Follow-up" and "Chase Client Feedback" say
    # nothing about whether anyone picked up a phone, and AR should be able to
    # settle that once here instead of having every report guess again.
    ar_followup_method = fields.Selection(
        FOLLOWUP_METHODS,
        string='AR Follow-up Method',
        help="How a completed activity of this type is recorded in the "
             "invoice Follow-up Log. Seeded from the activity type's name and "
             "category; change it here and the mapping sticks. Leave it empty "
             "for an activity that is not a client follow-up at all (an "
             "internal approval, say) and completing it will not be logged "
             "against the invoice.",
    )

    @api.model
    def _guess_ar_followup_method(self, name, category):
        """Seed value for the mapping. Only ever a starting point."""
        if category == 'phonecall':
            return 'call'
        text = (name or '').lower()
        if 'whatsapp' in text or 'whats app' in text:
            return 'whatsapp'
        if 'call' in text or 'phone' in text:
            return 'call'
        if 'mail' in text:
            return 'email'
        return 'other'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('ar_followup_method'):
                name = vals.get('name')
                # name is translatable, so a create can hand it over as a
                # {lang: value} dict rather than a plain string.
                if isinstance(name, dict):
                    name = name.get('en_US') or next(iter(name.values()), '')
                vals['ar_followup_method'] = self._guess_ar_followup_method(
                    name, vals.get('category'))
        return super().create(vals_list)
