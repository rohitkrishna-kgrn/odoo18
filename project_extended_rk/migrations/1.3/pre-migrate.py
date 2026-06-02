def migrate(cr, version):
    # Force-delete the stale search view so the upgrade recreates it cleanly.
    # This is needed because the old record had noupdate=True which prevented
    # normal upgrades from touching it.
    cr.execute("""
        DELETE FROM ir_ui_view
        WHERE id IN (
            SELECT res_id FROM ir_model_data
            WHERE name = 'view_task_search_inherit_custom'
              AND module = 'project_extended_rk'
        )
    """)
    cr.execute("""
        DELETE FROM ir_model_data
        WHERE name = 'view_task_search_inherit_custom'
          AND module = 'project_extended_rk'
    """)
