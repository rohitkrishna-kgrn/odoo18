from odoo import models, fields

from .retainership_contract import REVIEW_ACTIVITY_SUMMARY


class AccountMoveRetainership(models.Model):
    """Retainership provenance on the invoice.

    Kept in its own class so the retainership feature stays separable from the
    AR follow-up logic in account_move.py.
    """
    _inherit = 'account.move'

    retainership_contract_id = fields.Many2one(
        'retainership.contract',
        string='Retainership Contract',
        readonly=True,
        copy=False,
        index='btree_not_null',
        help="Contract this invoice was generated from.",
    )
    retainership_period_start = fields.Date(
        string='Retainership Period From',
        readonly=True,
        copy=False,
    )
    retainership_period_end = fields.Date(
        string='Retainership Period To',
        readonly=True,
        copy=False,
    )
    is_retainership_auto = fields.Boolean(
        string='Auto-Generated Retainership Draft',
        readonly=True,
        copy=False,
        help="Raised by the retainership scheduler rather than by a person. "
             "Posting the invoice is the finance approval.",
    )

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        for move in posted.filtered(lambda m: m.retainership_contract_id):
            # Posting is the approval step, so the review activity is answered
            # by the post itself rather than left hanging on the reviewer.
            review_activities = move.activity_ids.filtered(
                lambda a: a.summary == REVIEW_ACTIVITY_SUMMARY
            )
            if review_activities:
                review_activities.action_feedback(
                    feedback="Approved and posted by %s." % self.env.user.name
                )
            move.retainership_contract_id.message_post(
                body="Draft %s for period %s was reviewed and posted by %s." % (
                    move._get_html_link(),
                    move.retainership_contract_id._period_label(
                        move.retainership_period_start, move.retainership_period_end,
                    ) if move.retainership_period_start and move.retainership_period_end
                    else 'n/a',
                    self.env.user.name,
                )
            )
        return posted
