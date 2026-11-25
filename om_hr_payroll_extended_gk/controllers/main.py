from werkzeug.exceptions import Forbidden, NotFound

from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import content_disposition, request


class MyPayslipController(http.Controller):

    @http.route('/payroll/my-payslip/<int:payslip_id>/download', type='http', auth='user')
    def download_my_payslip(self, payslip_id, **kwargs):
        """Self-service download. The payslip is identified from the URL but the
        owner is always the logged-in user: record rules first, then ownership +
        approval re-checked here, and only then rendered (sudo, because the
        payslip layout reads contract / bank fields employees cannot read)."""
        slip = request.env['hr.payslip'].browse(payslip_id)
        try:
            slip.check_access('read')
            if not slip.exists():
                raise NotFound()
        except (AccessError, MissingError):
            raise NotFound()
        if not slip._is_my_approved_payslip():
            raise Forbidden()
        report = request.env.ref('om_hr_payroll.action_report_payslip').sudo()
        pdf, _fmt = request.env['ir.actions.report'].sudo()._render_qweb_pdf(report.report_name, [slip.id])
        name = 'Payslip_%s.pdf' % ((slip.sudo().number or slip.sudo().name or str(slip.id)).replace('/', '_'))
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf)),
            ('Content-Disposition', content_disposition(name)),
        ])
