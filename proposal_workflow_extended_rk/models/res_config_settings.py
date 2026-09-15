# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    einvoicing_status_api_url = fields.Char(
        string='Project Status Tracker URL',
        config_parameter='proposal_workflow_extended_rk.status_api_url',
        help="Base URL of the project status tracker, e.g. "
             "https://tracker.example.com — no trailing slash. "
             "/api/v1/project-status is added automatically.")
    einvoicing_status_api_token = fields.Char(
        string='Project Status Tracker Token',
        config_parameter='proposal_workflow_extended_rk.status_api_token',
        groups='base.group_system',
        help="The tracker's PROJECT_API_TOKEN shared secret, sent as a "
             "Bearer token. Leave either field blank to switch the "
             "eInvoicing Dashboard's Project Status / UAT AR-AP / Live "
             "AR-AP columns off — they read NA instead of calling out.")
