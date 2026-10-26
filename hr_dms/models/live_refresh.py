from odoo import api, models


class HrDmsLiveMixin(models.AbstractModel):
    """Tells open hr_dms screens that records changed, so they reload without a browser refresh.

    One bus message per transaction, sent to the record owners and HR; the payload is only
    the model and ids, the screens re-read the data with the viewer's own access rights.
    """
    _name = 'hr.dms.live.mixin'
    _description = 'Employee Documents live refresh'

    def _hr_dms_live_users(self):
        return self.sudo().mapped('user_id') if 'user_id' in self._fields else self.env['res.users']

    def _hr_dms_live_touch(self):
        if not self.ids:
            return
        cr = self.env.cr
        data = cr.precommit.data.get('hr_dms.live')
        if data is None:
            data = cr.precommit.data['hr_dms.live'] = {'models': {}, 'users': set()}
            env = self.env

            @cr.precommit.add
            def notify():
                live = cr.precommit.data.pop('hr_dms.live', None)
                if not live:
                    return
                hr = env.ref('hr_dms.group_hr_dms_manager', raise_if_not_found=False)
                users = env['res.users'].sudo().browse(live['users']) | (hr.sudo().users if hr else env['res.users'])
                payload = {model: sorted(ids) for model, ids in live['models'].items()}
                for partner in users.filtered('active').partner_id:
                    env['bus.bus']._sendone(partner, 'hr_dms/changed', payload)

        data['models'].setdefault(self._name, set()).update(self.ids)
        data['users'].update(self._hr_dms_live_users().ids)
        data['users'].add(self.env.uid)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._hr_dms_live_touch()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._hr_dms_live_touch()
        return res

    def unlink(self):
        self._hr_dms_live_touch()
        return super().unlink()
