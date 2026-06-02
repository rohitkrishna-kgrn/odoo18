def migrate(cr, version):
    # Delete the stale search view and its external ID so the upgrade
    # recreates it cleanly from XML (without the old completed_date field).
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
