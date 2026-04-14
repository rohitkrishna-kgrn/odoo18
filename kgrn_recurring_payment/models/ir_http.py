from odoo import models
from odoo.http import request

# Public URL prefixes specific to this module.
# ALSO patched into website_extended_rk's _PUBLIC_PREFIXES tuple so that
# the login-redirect in that module is bypassed for these paths.
_KGRN_RECURRING_PUBLIC = (
    '/kgrn/recurring/',
)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _dispatch(cls, endpoint):
        # For KGRN recurring portal URLs we must NOT redirect to login even
        # when there is no session uid.  We achieve this by calling
        # super()._dispatch() which eventually reaches website_extended_rk's
        # override; that override already has '/kgrn/recurring/' in its
        # _PUBLIC_PREFIXES so it skips the redirect and delegates to the base
        # ir.http._dispatch, which runs _authenticate('public') and sets up
        # the proper public-user environment before invoking the endpoint.
        #
        # Calling endpoint() directly (the previous approach) was wrong
        # because it bypasses _authenticate, leaving request.uid unset for
        # unauthenticated visitors.
        return super()._dispatch(endpoint)
