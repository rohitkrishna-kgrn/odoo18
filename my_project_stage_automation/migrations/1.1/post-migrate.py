import logging
import json

logger = logging.getLogger(__name__)


def _col_is_jsonb(cr, table, column):
    cr.execute("""
        SELECT data_type FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table, column))
    row = cr.fetchone()
    return row and row[0] in ('json', 'jsonb')


def _col_exists(cr, table, column):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table, column))
    return bool(cr.fetchone())


def _name_val(cr, table, value):
    """Return the correct Python value for a name field (str or JSON string)."""
    if _col_is_jsonb(cr, table, 'name'):
        return json.dumps({'en_US': value})
    return value


def _name_sql(cr, table):
    """Return the SQL cast fragment for inserting a name value."""
    if _col_is_jsonb(cr, table, 'name'):
        return '%s::jsonb'
    return '%s'


def _name_filter(cr, table, value):
    """Return (sql_fragment, params) to search a name field by value."""
    if _col_is_jsonb(cr, table, 'name'):
        return f"name::text LIKE %s", (f'%"{value}"%',)
    return "name = %s", (value,)


def _get_or_create_project_stage(cr):
    sql_filter, params = _name_filter(cr, 'project_project_stage', 'Cancelled')
    cr.execute(f"SELECT id FROM project_project_stage WHERE {sql_filter} LIMIT 1", params)
    row = cr.fetchone()
    if row:
        return row[0]

    name_cast = _name_sql(cr, 'project_project_stage')
    name_val = _name_val(cr, 'project_project_stage', 'Cancelled')
    cr.execute(
        f"INSERT INTO project_project_stage (name, sequence) VALUES ({name_cast}, 100) RETURNING id",
        (name_val,),
    )
    stage_id = cr.fetchone()[0]
    logger.info("[MIGRATION] Created project stage 'Cancelled' (id=%s)", stage_id)
    return stage_id


def _get_or_create_task_stage(cr, project_id):
    sql_filter, params = _name_filter(cr, 'project_task_type', 'Cancelled')

    # Stage already linked to this project
    cr.execute(f"""
        SELECT pt.id
        FROM project_task_type pt
        JOIN project_task_type_rel rel ON rel.type_id = pt.id
        WHERE pt.{sql_filter} AND rel.project_id = %s
        LIMIT 1
    """, (*params, project_id))
    row = cr.fetchone()
    if row:
        return row[0]

    # Stage exists globally
    cr.execute(f"SELECT id FROM project_task_type WHERE {sql_filter} LIMIT 1", params)
    row = cr.fetchone()
    if row:
        task_stage_id = row[0]
    else:
        # Build INSERT with only the columns that actually exist
        name_cast = _name_sql(cr, 'project_task_type')
        name_val = _name_val(cr, 'project_task_type', 'Cancelled')
        cols = ['name', 'sequence']
        vals = [name_val, 100]
        placeholders = [name_cast, '%s']

        if _col_exists(cr, 'project_task_type', 'fold'):
            cols.append('fold')
            vals.append(False)
            placeholders.append('%s')

        for legend_col in ('legend_normal', 'legend_blocked', 'legend_done'):
            if _col_exists(cr, 'project_task_type', legend_col):
                legend_val = _name_val(cr, 'project_task_type', '')
                legend_cast = _name_sql(cr, 'project_task_type')
                cols.append(legend_col)
                vals.append(legend_val)
                placeholders.append(legend_cast)

        col_str = ', '.join(cols)
        ph_str = ', '.join(placeholders)
        cr.execute(
            f"INSERT INTO project_task_type ({col_str}) VALUES ({ph_str}) RETURNING id",
            vals,
        )
        task_stage_id = cr.fetchone()[0]
        logger.info("[MIGRATION] Created task stage 'Cancelled' (id=%s)", task_stage_id)

    cr.execute("""
        INSERT INTO project_task_type_rel (project_id, type_id)
        VALUES (%s, %s) ON CONFLICT DO NOTHING
    """, (project_id, task_stage_id))
    return task_stage_id


def migrate(cr, version):
    if not _col_exists(cr, 'project_project', 'sale_order_id'):
        logger.warning("[MIGRATION] sale_order_id column not found on project_project — skipping.")
        return

    has_state_additional = _col_exists(cr, 'project_task', 'state_additional')

    cr.execute("""
        SELECT pp.id
        FROM project_project pp
        JOIN sale_order so ON so.id = pp.sale_order_id
        WHERE so.state = 'cancel'
    """)
    project_ids = [r[0] for r in cr.fetchall()]

    if not project_ids:
        logger.info("[MIGRATION] No projects linked to cancelled sale orders — nothing to sync.")
        return

    project_stage_id = _get_or_create_project_stage(cr)
    total_tasks = 0

    for project_id in project_ids:
        cr.execute(
            "UPDATE project_project SET stage_id = %s WHERE id = %s",
            (project_stage_id, project_id),
        )
        task_stage_id = _get_or_create_task_stage(cr, project_id)

        if has_state_additional:
            cr.execute("""
                UPDATE project_task SET stage_id = %s, state_additional = 'cancelled'
                WHERE project_id = %s
            """, (task_stage_id, project_id))
        else:
            cr.execute(
                "UPDATE project_task SET stage_id = %s WHERE project_id = %s",
                (task_stage_id, project_id),
            )
        total_tasks += cr.rowcount

    logger.info(
        "[MIGRATION] Done — %d project(s) and %d task(s) moved to Cancelled.",
        len(project_ids), total_tasks,
    )
