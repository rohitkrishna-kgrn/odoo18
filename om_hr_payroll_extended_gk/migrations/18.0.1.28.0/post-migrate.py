import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Email copies already shown in the payroll chatter are detached from the records
    (the mails and their delivery logs are kept)."""
    cr.execute("""
        UPDATE mail_message SET model = NULL, res_id = NULL
         WHERE model IN ('payroll.country.batch', 'payroll.country.line')
           AND message_type = 'email_outgoing'
    """)
    _logger.info("payroll chatter: %s email copies removed", cr.rowcount)
