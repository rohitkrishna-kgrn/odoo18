from odoo import http
from odoo.addons.web.controllers.home import Home
from odoo.http import request


class CustomLoginController(Home):

    @http.route('/web/login', type='http', auth='none', sitemap=False)
    def web_login(self, redirect=None, **kw):
        """Override default login to use custom company login template."""
        response = super().web_login(redirect=redirect, **kw)
        # If it's a Response object with a template, swap to our custom template
        if hasattr(response, 'qcontext'):
            response.template = 'website_extended_rk.login'
        return response

    @http.route('/', type='http', auth='none', sitemap=False)
    def home(self, **kw):
        """Redirect root URL to custom login page."""
        if request.session.uid:
            return request.redirect('/odoo')
        return request.redirect('/web/login')
