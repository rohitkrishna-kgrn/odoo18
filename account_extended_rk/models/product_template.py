from odoo import models, fields, api
from odoo.exceptions import ValidationError

# Billing periods a retainership product can be sold on, and how many months
# each one advances the schedule by.
RETAINERSHIP_INTERVALS = [
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly'),
    ('half_yearly', 'Half-Yearly'),
    ('yearly', 'Yearly'),
]

RETAINERSHIP_INTERVAL_MONTHS = {
    'monthly': 1,
    'quarterly': 3,
    'half_yearly': 6,
    'yearly': 12,
}

# Billing day is capped at 28 so every month can honour it. A contract that
# must bill on the last day of the month sets 28 and finance adjusts the two
# or three drafts a year where that matters.
MAX_BILLING_DAY = 28


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_retainership = fields.Boolean(
        string='Retainership Product',
        help="Tick for services sold on a standing retainer (monthly "
             "outsourcing, ongoing compliance support, and the like). Only "
             "these products can be put on a Retainership Contract, which "
             "raises the draft invoice automatically each period.",
    )
    retainership_interval = fields.Selection(
        RETAINERSHIP_INTERVALS,
        string='Billing Period',
        default='monthly',
        help="Default billing period proposed on a new Retainership Contract "
             "for this product. Each contract can still override it.",
    )
    retainership_billing_day = fields.Integer(
        string='Bill on Day',
        default=1,
        help="Default day of the month the draft invoice is raised on "
             "(1-%s). Each contract can still override it." % MAX_BILLING_DAY,
    )

    @api.constrains('is_retainership', 'retainership_billing_day')
    def _check_retainership_billing_day(self):
        for product in self:
            if not product.is_retainership:
                continue
            if not 1 <= product.retainership_billing_day <= MAX_BILLING_DAY:
                raise ValidationError(
                    "Bill on Day must be between 1 and %s on retainership "
                    "product '%s'." % (MAX_BILLING_DAY, product.display_name)
                )
