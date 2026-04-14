from odoo import models
from odoo.http import request

# Paths that must remain accessible without login
_PUBLIC_PREFIXES = (
    '/web/login',
    '/web/static/',
    '/web/assets/',
    '/web/image/',
    '/web/content/',
    '/web/font/',
    '/website_extended_rk/static/',
    '/kgrn_recurring_payment/static/',
    '/kgrn/recurring/',          # KGRN Recurring Payment customer portal
    '/favicon.ico',
    '/web/database/',
    '/web/health',
)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _dispatch(cls, endpoint):
        if not request.session.uid:
            path = request.httprequest.path
            if not any(path.startswith(p) for p in _PUBLIC_PREFIXES):
                redirect_to = '/web/login?redirect=' + request.httprequest.full_path
                return request.redirect(redirect_to)
        return super()._dispatch(endpoint)
