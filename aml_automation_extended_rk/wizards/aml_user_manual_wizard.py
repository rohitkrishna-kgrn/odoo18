from odoo import models, api


class AmlUserManualWizard(models.TransientModel):
    _name = 'aml.user.manual.wizard'
    _description = 'AML User Manual'

    # =========================================================================
    # Branding helpers used by the PDF template
    # =========================================================================
    def get_logo_white_jpeg(self):
        """KGRN logo composited onto white and returned as base64 JPEG.

        Reuses the helper on ``aml.request`` so the manual, the KYC report and
        the notification emails all render the same logo. The company logo is
        stored as WebP here, which wkhtmltopdf cannot draw, hence the
        conversion. Returns False when Pillow / the logo is unavailable so the
        template can fall back to the raw logo.
        """
        company = self.env.company
        return self.env['aml.request']._compute_logo_white_jpeg(company)

    # =========================================================================
    # Actions
    # =========================================================================
    def action_print_manual(self):
        """Render the role-based user manual as a PDF."""
        # The wizard is opened from a menu, so ``self`` may be an empty
        # recordset until the form is saved; create a record on the fly so the
        # report always has a document to render against.
        wizard = self or self.create({})
        return self.env.ref(
            'aml_automation_extended_rk.action_report_aml_user_manual'
        ).report_action(wizard)

    @api.model
    def action_print_manual_from_menu(self):
        """Menu entry point: go straight to the PDF without opening the form."""
        return self.create({}).action_print_manual()
