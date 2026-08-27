"""Make the Sale Order Line the engagement link everywhere.

Two backfills, both driven off the project the old "Bill To / Linked Service
Engagement" field already pointed at:

1. `account_move.sale_order_line_id` for documents that carried an engagement
   but no sale order line. It is a stored computed field, and changing its
   @api.depends does not by itself make Odoo recompute it, so the rows are
   filled here.
2. `retainership_contract.sale_order_line_id`, the new field that replaces the
   engagement picker on the contract form.

project_project.sale_line_id is preferred where it is set; otherwise the line
is found through sale_order_line.project_id, which is 1:1 in this database
(2,575 projects, none with more than one line pointing at them). A contract or
invoice whose project has no sale order line at all keeps its engagement and is
left alone -- nothing is blanked out.
"""
import logging

_logger = logging.getLogger(__name__)

# One sale order line per project: the explicit link when the project carries
# one, else the single line that delivers it.
_LINE_FOR_PROJECT = """
    SELECT DISTINCT ON (p.id) p.id AS project_id, COALESCE(p.sale_line_id, sol.id) AS line_id
      FROM project_project p
      LEFT JOIN sale_order_line sol ON sol.project_id = p.id
     WHERE p.sale_line_id IS NOT NULL OR sol.id IS NOT NULL
     ORDER BY p.id, p.sale_line_id NULLS LAST, sol.id
"""


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        WITH line_for_project AS (%s)
        UPDATE account_move am
           SET sale_order_line_id = lfp.line_id
          FROM line_for_project lfp
         WHERE lfp.project_id = am.service_engagement_id
           AND am.sale_order_line_id IS NULL
    """ % _LINE_FOR_PROJECT)
    _logger.info("Sale Order Line backfilled on %s account moves.", cr.rowcount)

    cr.execute("""
        WITH line_for_project AS (%s)
        UPDATE retainership_contract rc
           SET sale_order_line_id = lfp.line_id
          FROM line_for_project lfp
         WHERE lfp.project_id = rc.service_engagement_id
           AND rc.sale_order_line_id IS NULL
    """ % _LINE_FOR_PROJECT)
    _logger.info("Sale Order Line backfilled on %s retainership contracts.", cr.rowcount)
