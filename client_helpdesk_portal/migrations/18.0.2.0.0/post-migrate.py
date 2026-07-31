def migrate(cr, version):
    # Ticket sequence: switch to yearly-reset CHT/<year>/#### numbering.
    # Parameterized so the '%' in '%(year)s' is stored literally, matching
    # the same pitfall documented in recruitment_gk's migration.
    cr.execute(
        """
        UPDATE ir_sequence
           SET prefix         = %s,
               padding        = %s,
               use_date_range = %s
         WHERE code = %s
        """,
        ('CHT/%(year)s/', 4, True, 'client.helpdesk.ticket'),
    )
    cr.execute(
        """
        UPDATE ir_model_data
           SET noupdate = false
         WHERE module = %s
           AND name   = %s
        """,
        ('client_helpdesk_portal', 'seq_client_helpdesk_ticket'),
    )

    # Manager ticket visibility: restrict from "sees all" to "sees their
    # reporting hierarchy" now that a separate Helpdesk Admin role has
    # unrestricted access.
    cr.execute(
        """
        UPDATE ir_rule
           SET domain_force = %s
         WHERE id = (
            SELECT res_id FROM ir_model_data
             WHERE module = %s AND name = %s
         )
        """,
        ("[('manager_user_ids', 'in', user.id)]", 'client_helpdesk_portal', 'rule_ticket_manager_all'),
    )
    cr.execute(
        """
        UPDATE ir_model_data
           SET noupdate = false
         WHERE module = %s
           AND name   = %s
        """,
        ('client_helpdesk_portal', 'rule_ticket_manager_all'),
    )
