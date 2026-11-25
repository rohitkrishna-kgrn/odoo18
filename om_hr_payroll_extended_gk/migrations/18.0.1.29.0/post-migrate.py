import logging
import re

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Highest payslip number of the payslips removed on 2026-11-24 for testing
# (/root/kgrn_backups/payslips_only_20261124_0555.dump, restored with their own numbers).
REMOVED_MAX_NUMBER = 1206


def migrate(cr, version):
    """PAYROLL/<country>/<year>/<month> references, gap-free payslip numbers given at
    approval, and a Payroll > Payslip Batches entry per approved country payroll."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Batch = env['payroll.country.batch'].with_context(active_test=False)
    # 1. references
    batches = Batch.search([], order='id')
    for batch in batches:
        old = batch.name
        batch._system_write({'name': batch._reference_name()})
        _logger.info("payroll reference %s -> %s", old, batch.name)
    # 2. approved payslips renumbered continuously, in approval then payroll order
    Payslip = env['hr.payslip']
    others = Payslip.search([('country_line_id', '=', False), ('number', '=like', 'SLIP/%')])
    numbers = [int(m.group(1)) for m in (re.match(r'SLIP/(\d+)$', n or '') for n in others.mapped('number')) if m]
    nxt = max(numbers + [REMOVED_MAX_NUMBER]) + 1
    approved = batches.filtered(lambda b: b.state == 'approved').sorted(lambda b: (b.approved_date or b.create_date, b.id))
    for batch in approved:
        slips = batch.line_ids.sorted(lambda l: (l.company_name or '', l.employee_name or '', l.id)).payslip_id
        for slip in slips:
            slip.write({'number': 'SLIP/%s' % nxt})
            nxt += 1
        batch._create_payslip_run(slips)
        _logger.info("%s: %s payslips numbered, payslip batch %s", batch.name, len(slips), batch.payslip_run_id.id)
    # drafts give their number back: numbers are taken at confirmation only
    Payslip.search([('state', 'in', ('draft', 'verify')), ('number', '!=', False)]).write({'number': False})
    # 3. gap-free sequence continuing after the last number
    seq = env['ir.sequence'].search([('code', '=', 'salary.slip')], limit=1)
    seq.write({'implementation': 'no_gap', 'number_next': nxt})
    _logger.info("salary.slip sequence: no_gap, next %s", nxt)
