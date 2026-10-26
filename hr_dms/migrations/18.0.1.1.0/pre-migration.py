def migrate(cr, version):
    """HR Officer is being removed: its members become HR Managers."""
    cr.execute("""
        INSERT INTO res_groups_users_rel (gid, uid)
        SELECT m.res_id, r.uid
          FROM res_groups_users_rel r
          JOIN ir_model_data o ON o.res_id = r.gid AND o.model = 'res.groups'
                              AND o.module = 'hr_dms' AND o.name = 'group_hr_dms_officer'
          JOIN ir_model_data m ON m.model = 'res.groups'
                              AND m.module = 'hr_dms' AND m.name = 'group_hr_dms_manager'
        ON CONFLICT DO NOTHING
    """)
