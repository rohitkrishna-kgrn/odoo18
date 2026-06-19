from odoo import models
from odoo.exceptions import AccessError, UserError


class RecruitmentGkBase(models.AbstractModel):
    _name = 'recruitment.gk.base'
    _description = 'Recruitment GK Access Warning Mixin'

    def check_access_rights(self, operation, raise_exception=True):
        try:
            return super().check_access_rights(operation, raise_exception)
        except AccessError as e:
            raise UserError(str(e)) from None

    def check_access_rule(self, operation):
        try:
            return super().check_access_rule(operation)
        except AccessError as e:
            raise UserError(str(e)) from None
