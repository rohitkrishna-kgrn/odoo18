from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup


class UpsellingRejectWizard(models.TransientModel):
    _name = 'upselling.reject.wizard'
    _description = 'Upselling Rejection Wizard'

    upselling_id = fields.Many2one('upselling', string='Upselling', required=True)
    rejection_reason = fields.Text(string='Rejection Reason', required=True)

    @api.constrains('rejection_reason')
    def _check_rejection_reason(self):
        for wizard in self:
            if not (wizard.rejection_reason or '').strip():
                raise ValidationError(_('A rejection reason is mandatory.'))

    def action_confirm_reject(self):
        self.ensure_one()
        rec = self.upselling_id
        reason = (self.rejection_reason or '').strip()
        if not reason:
            raise UserError(_('A rejection reason is mandatory.'))
        if rec.state not in ('review', 'approval'):
            raise UserError(_(
                'Only requests submitted for review or approval can be rejected.'
            ))
        rec._check_reject_authorisation()

        rec.write({
            'state': 'rejected',
            'rejection_reason': reason,
            'rejected_by_id': self.env.user.id,
            'rejection_date': fields.Datetime.now(),
        })
        rec._add_log('reject', reason)
        rec.message_post(
            body=Markup(
                '<b style="color:#d9534f;">Upselling Rejected</b><br/>'
                '<span style="color:#1a73e8;">Rejected By :</span> %s<br/>'
                '<span style="color:#1a73e8;">Reason :</span> %s'
            ) % (self.env.user.name, reason),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        # Notify the submitter that the request will not proceed any further.
        if rec.user_id.partner_id:
            rec.message_notify(
                partner_ids=[rec.user_id.partner_id.id],
                subject=f'Upselling {rec.sequence} - Rejected',
                body=Markup(
                    'Dear {},<br/><br/>'
                    'Your upselling request <b>{}</b> has been rejected by {}.<br/><br/>'
                    '<b>Reason:</b> {}<br/><br/>'
                    'This request will not proceed to the next approval stage.'
                ).format(rec.user_id.name, rec.sequence, self.env.user.name, reason),
            )
        return {'type': 'ir.actions.act_window_close'}
