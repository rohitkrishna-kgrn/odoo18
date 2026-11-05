def migrate(cr, version):
    """Referral emails were logged in the chatter as full HTML messages.
    Re-type the existing ones as user_notification, like new sends: still
    listed under Settings > Emails, no longer shown in the chatter."""
    cr.execute("""
        UPDATE mail_message m
           SET message_type = 'user_notification'
         WHERE m.message_type = 'email_outgoing'
           AND EXISTS (SELECT 1 FROM mail_mail mm WHERE mm.mail_message_id = m.id)
           AND (m.model = 'referral.commission'
                OR (m.model = 'crm.lead'
                    AND m.res_id IN (SELECT id FROM crm_lead WHERE x_is_referral)
                    AND split_part(m.subject, ':', 1) IN (
                        'New Referral Submitted', 'Referral Assigned to You',
                        'Referral Converted')))
    """)
