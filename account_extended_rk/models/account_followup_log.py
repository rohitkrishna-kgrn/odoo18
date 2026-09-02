import re

from odoo import api, models, fields
from odoo.tools import html2plaintext

# How a follow-up reached the log. Every row is now materialised from a
# chatter message -- either a Log note somebody typed, or the message Odoo
# posts when a scheduled activity is marked done. 'manual' only ever appears
# on the handful of rows entered through the old Follow-up Log tab before it
# was removed.
FOLLOWUP_SOURCES = [
    ('note', 'Chatter Log Note'),
    ('activity', 'Activity'),
    ('manual', 'Manual Entry'),
]

FOLLOWUP_METHODS = [
    ('email', 'Email'),
    ('call', 'Call'),
    ('whatsapp', 'WhatsApp'),
    ('other', 'Other'),
]

# Read off a typed Log note when no activity type says what the method was.
# Earliest match in the note wins, so "Called the client, will email the SOA"
# is a Call -- the thing that was actually done leads the sentence. Word
# boundaries keep 'mail' out of 'emailed' and 'call' out of 'recall'.
_METHOD_PATTERNS = [
    ('whatsapp', re.compile(r'\b(whats\s?app|wapp|wa\s+msg)\w*', re.I)),
    ('call', re.compile(r'\b(call|phone|rang|dial|telephone|spoke|spoken)\w*', re.I)),
    ('email', re.compile(r'\b(e-?mail|mail)\w*', re.I)),
]


class AccountInvoiceFollowupLog(models.Model):
    _name = 'account.invoice.followup.log'
    _description = 'Invoice Follow-up Log'
    _order = 'date desc, id desc'

    move_id = fields.Many2one(
        'account.move',
        string='Invoice',
        required=True,
        ondelete='cascade',
        index=True,
    )
    date = fields.Date(
        string='Follow-up Date',
        required=True,
        default=fields.Date.context_today,
    )
    method = fields.Selection(
        FOLLOWUP_METHODS,
        string='Method',
        required=True,
        help="Taken from the activity type when the follow-up came from an "
             "activity, otherwise read from the wording of the Log note. "
             "Correct it here if it was read wrong.",
    )
    response = fields.Text(string='Client Response')
    # Stamped with whoever writes the line and never selectable: the log is
    # an audit trail of who chased the client, so it must not be attributable
    # to another user. Kept out of the client's reach in the view (readonly)
    # and re-forced here so an import, Studio tweak or raw RPC call cannot
    # rewrite it either.
    user_id = fields.Many2one(
        'res.users',
        string='Logged By',
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Provenance. The chatter message is the record of truth; this row is a
    # reporting projection of it. ondelete='cascade' so deleting the note
    # deletes the follow-up rather than leaving the AR report quoting a
    # message nobody can find.
    # ------------------------------------------------------------------
    message_id = fields.Many2one(
        'mail.message',
        string='Chatter Message',
        ondelete='cascade',
        index=True,
        readonly=True,
    )
    source = fields.Selection(
        FOLLOWUP_SOURCES,
        string='Source',
        default='manual',
        required=True,
        readonly=True,
    )
    activity_type_id = fields.Many2one(
        'mail.activity.type',
        string='Activity Type',
        readonly=True,
        help="The activity that was marked done, when the follow-up came "
             "from one. Blank for a typed Log note.",
    )

    # ------------------------------------------------------------------
    # Reporting handles. Stored so the AR export can group and filter on
    # them; a follow-up never moves to another invoice, so they are written
    # once and never recomputed in anger.
    # ------------------------------------------------------------------
    partner_id = fields.Many2one(
        related='move_id.partner_id', string='Client', store=True, index=True)
    ar_responsible_id = fields.Many2one(
        related='move_id.ar_responsible_id', string='AR Responsible', store=True)
    invoice_date_due = fields.Date(
        related='move_id.invoice_date_due', string='Due Date', store=True)
    aging_bucket = fields.Selection(
        related='move_id.aging_bucket', string='Aging Bucket', store=True)
    amount_residual = fields.Monetary(
        related='move_id.amount_residual', string='Amount Due',
        currency_field='currency_id')
    currency_id = fields.Many2one(related='move_id.currency_id')
    move_state = fields.Selection(related='move_id.state', string='Invoice Status')

    _sql_constraints = [
        # One follow-up per chatter message. NULLs do not collide in Postgres,
        # so the legacy hand-entered rows are unaffected.
        ('message_uniq', 'unique(message_id)',
         'This chatter message has already been logged as a follow-up.'),
    ]

    # ------------------------------------------------------------------
    # Method detection
    # ------------------------------------------------------------------
    @api.model
    def _method_from_text(self, text):
        """Best guess at the follow-up method from free text, 'other' if none.

        Never raises and never returns False: `method` is required, and a
        follow-up that cannot be classified must still be counted -- an
        unclassified chase is a chase, and dropping it would put the invoice
        back under the red No Follow-Up Logged banner.
        """
        best_method, best_pos = 'other', None
        for method, pattern in _METHOD_PATTERNS:
            match = pattern.search(text or '')
            if match and (best_pos is None or match.start() < best_pos):
                best_method, best_pos = method, match.start()
        return best_method

    @api.model
    def _prepare_from_message(self, move, message, feedback=None):
        """Follow-up values for a chatter message, or None if it is not one.

        Two kinds of message count, and nothing else does:
          * a Log note somebody typed (message_type 'comment' on an internal
            subtype);
          * the message Odoo posts when an activity is marked done, which
            carries mail_activity_type_id.
        Field-tracking messages share the Note subtype but are message_type
        'notification' with no activity type, so they are excluded -- there
        are over 21,000 of them on account.move and every one would otherwise
        become a phantom follow-up. Messages OdooBot posted, and activity
        types with no AR method mapped, are excluded too.
        """
        activity_type = message.mail_activity_type_id
        is_note = message.message_type == 'comment' and message.subtype_id.internal
        if not activity_type and not is_note:
            return None

        # OdooBot talks to itself in the chatter -- "The invoice already
        # contains lines, it was not updated from the attachment" is posted as
        # a Log note, by the system, on customer invoices. A follow-up is a
        # person chasing a client, so nothing OdooBot says is one.
        odoobot = self.env.ref('base.partner_root', raise_if_not_found=False)
        if odoobot and message.author_id == odoobot:
            return None

        # An activity type with no AR method mapped is not a client follow-up
        # at all -- blank the mapping on an internal type (an approval, an
        # upload reminder) and completing it stops reaching the AR reports.
        if activity_type and not activity_type.ar_followup_method:
            return None

        body_text = ' '.join(html2plaintext(message.body or '').split())
        if activity_type:
            method = activity_type.ar_followup_method
            # The posted body is a rendered template ("Call done: ... Feedback:
            # ..."). The feedback the user typed is the client response; fall
            # back to the whole rendered body when they marked it done without
            # saying anything.
            response = ' '.join((feedback or '').split()) or body_text
        else:
            method = self._method_from_text(body_text)
            response = body_text

        return {
            'move_id': move.id,
            'message_id': message.id,
            'source': 'activity' if activity_type else 'note',
            'activity_type_id': activity_type.id or False,
            'date': fields.Date.context_today(move, message.date),
            'method': method,
            'response': response or False,
            'user_id': self._author_user(message).id,
        }

    @api.model
    def _author_user(self, message):
        """The internal user behind a message's author partner.

        Falls back to the acting user: a message posted with no author at all
        (an inbound mail route, say) still needs someone in Logged By because
        the field is required.
        """
        if message.author_id:
            user = self.env['res.users'].sudo().search(
                [('partner_id', '=', message.author_id.id)],
                order='share, id', limit=1)
            if user:
                return user
        return self.env.user

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # sudo() is left an escape hatch for data migrations and for
            # server code that logs a follow-up on someone else's behalf --
            # which is now the normal path, since a note is materialised into
            # a log row under sudo on behalf of whoever typed it.
            if not (self.env.su and vals.get('user_id')):
                vals['user_id'] = self.env.user.id
        return super().create(vals_list)

    def write(self, vals):
        if 'user_id' in vals and not self.env.su:
            vals = {k: v for k, v in vals.items() if k != 'user_id'}
        return super().write(vals)
