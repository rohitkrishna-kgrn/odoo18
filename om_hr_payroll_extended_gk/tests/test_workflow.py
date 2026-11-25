from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CountryPayrollCase


@tagged('post_install', '-at_install', 'country_payroll')
class TestApprovalAndDistribution(CountryPayrollCase):
    """F. Approval, G. payslip distribution, H. employee self-service."""

    def _mails_to(self, email):
        return self.env['mail.mail'].sudo().search([('email_to', 'ilike', email)])

    # ---------------------------------------------------------------- F
    def test_f1_bank_details_not_validated(self):
        nobank = self._employee('PC No Bank', 'dubai', self.co_ae, wage=5000, basic_salary=5000, bank=False)
        batch = self._calculated(self.cfg_ae)
        line = self._line(batch, nobank)
        self.assertFalse(line.bank_iban)
        self.assertNotIn('Bank', line.validation_message or '', "missing bank details are not checked")
        self.assertNotEqual(line.validation_status, 'error')

    def test_f2_submit_needs_a_payroll_admin(self):
        admin_group = self.env.ref('om_hr_payroll_extended_gk.group_payroll_admin')
        admin_group.users = [(5, 0, 0)]                     # nobody is Payroll Admin (rolled back)
        batch = self._calculated(self.cfg_in)
        res = batch.action_submit()
        self.assertEqual(batch.state, 'calculated')
        self.assertIn('Payroll Admin', res['params']['message'])

    def test_f3_submit_notifies_payroll_admins_only(self):
        batch = self._calculated(self.cfg_ae)
        with self.fake_attendance():
            res = batch.action_submit()
        self.assertEqual(batch.state, 'submitted', res['params']['message'])
        self.assertEqual(batch.submitted_by, self.officer_ae)
        admins = self.env['res.users']._payroll_approvers()
        self.assertEqual(batch.approver_user_ids, admins)
        self.assertTrue(self.approver | self.approver_in <= batch.approver_user_ids)
        logs = batch.sudo().notify_log_ids.filtered(lambda l: l.kind == 'submitted')
        self.assertEqual(logs.user_id, admins, "the approval request goes to the Payroll Admins only")
        log = logs.filtered(lambda l: l.user_id == self.approver)
        self.assertTrue(log.mail_id)
        self.assertIn(batch.name, log.mail_id.subject)
        self.assertIn('model=payroll.country.batch', log.mail_id.body_html, "direct link to the batch")
        self.assertNotIn('Generate Report', log.mail_id.body_html)
        for label in ('Gross', 'Deductions', 'Net Salary', batch.currency_id.format(batch.total_net)):
            self.assertNotIn(label, log.mail_id.body_html, "no salary figures in emails")
        self.assertTrue(batch.sudo().activity_ids.filtered(lambda a: a.user_id == self.approver))
        self.assertFalse(log.mail_id.model, "the email is not posted in the batch chatter")
        self.assertFalse(batch.sudo().message_ids.filtered(lambda m: m.message_type == 'email_outgoing'))
        # chatter: no Send message, no attachments; Log note works
        with self.assertRaises(UserError):
            batch.with_user(self.officer_ae).message_post(body='hi', message_type='comment',
                                                          subtype_xmlid='mail.mt_comment')
        with self.assertRaises(UserError):
            self.env['ir.attachment'].create({'name': 'x.txt', 'raw': b'x', 'res_model': batch._name,
                                              'res_id': batch.id})
        batch.with_user(self.officer_ae).message_post(body='internal', message_type='comment',
                                                      subtype_xmlid='mail.mt_note')
        self.assertFalse(self._mails_to(self.payroll_admin.email), "a Manager is not asked to approve")
        # locked after submission
        line = self._line(batch, self.emp_ae)
        self.assertEqual(line.state, 'submitted')
        with self.assertRaises(UserError):
            line.with_user(self.officer_ae).write({'basic': 1.0})
        # the Admin sees the batch and every line of it
        self.assertTrue(self.Batch.with_user(self.approver).search([('id', '=', batch.id)]))
        self.assertEqual(self.env['payroll.country.line'].with_user(self.approver).search_count(
            [('batch_id', '=', batch.id)]), len(batch.sudo().line_ids))
        self.assertTrue(batch.with_user(self.approver).can_approve)
        self.assertFalse(batch.with_user(self.payroll_admin).can_approve)

    def test_f2c_quotation_approver_is_default_payroll_admin(self):
        admin_group = self.env.ref('om_hr_payroll_extended_gk.group_payroll_admin')
        admin_group.users = [(5, 0, 0)]                     # nobody is Payroll Admin (rolled back)
        self.assertFalse(self.payroll_admin._is_payroll_approver())
        self.co_in.approver_user_id = self.payroll_admin
        self.assertTrue(self.payroll_admin._is_payroll_approver(), "Quotation Approver -> Payroll Admin")
        batch = self._calculated(self.cfg_in)
        with self.fake_attendance():
            res = batch.action_submit()
        self.assertEqual(batch.state, 'submitted', res['params']['message'])
        self.assertEqual(batch.approver_user_ids, self.payroll_admin)
        # another approver later: the former one keeps Admin until changed on the user
        self.co_in.approver_user_id = self.approver
        self.assertTrue(self.approver._is_payroll_approver())
        self.assertTrue(self.payroll_admin._is_payroll_approver())
        # archived users are never added
        self.stranger.active = False
        self.co_ae.approver_user_id = self.stranger
        self.assertNotIn(self.stranger, admin_group.with_context(active_test=False).users)

    def test_f2d_reference_numbers_and_payslip_batch(self):
        batch = self._batch(self.cfg_ae)
        self.assertEqual(batch.name, 'PAYROLL/UAE/2039/3', "PAYROLL/<country>/<year>/<month>")
        self.assertEqual(self._batch(self.cfg_in).name, 'PAYROLL/IND/2039/3')
        self.assertEqual(self._batch(self.cfg_ae, companies=self.co_ae).name, 'PAYROLL/UAE/2039/3-2',
                         "a second payroll of the same month")
        approved = self._batch(self.cfg_ae, companies=self.co_ae)
        with self.fake_attendance():
            approved.action_fetch_employees()
            self._keep_only(approved, self.emp_ae | self.emp_ae2)
            approved.action_calculate()
            slips = approved.sudo().line_ids.payslip_id
            self.assertEqual(len(slips), 2)
            self.assertFalse(any(slips.mapped('number')), "drafts take no payslip number")
            approved.action_recalculate()
            self.assertFalse(any(slips.mapped('number')))
            approved.action_submit()
        seq = self.env['ir.sequence'].sudo().search([('code', '=', 'salary.slip')], limit=1)
        seq.implementation = 'no_gap'
        first = seq.number_next_actual
        approved.with_user(self.approver).action_approve()
        ordered = approved.sudo().line_ids.sorted(lambda l: (l.company_name, l.employee_name, l.id)).payslip_id
        self.assertEqual(ordered.mapped('number'), [seq.get_next_char(first), seq.get_next_char(first + 1)],
                         "continuous numbers at approval, in payroll order")
        self.assertEqual(set(slips.mapped('state')), {'done'})
        run = approved.sudo().payslip_run_id
        self.assertEqual((run.name, run.state, run.slip_ids), (approved.name, 'close', slips))
        self.assertEqual((run.date_start, run.date_end), (approved.date_from, approved.date_to))

    def test_f2b_sole_admin_may_approve_own_submission(self):
        admin_group = self.env.ref('om_hr_payroll_extended_gk.group_payroll_admin')
        admin_group.users = [(6, 0, self.approver.ids)]       # the only Payroll Admin (rolled back)
        batch = self._calculated(self.cfg_ae)
        with self.fake_attendance():
            batch.action_submit()
        batch.sudo().submitted_by = self.approver
        batch.with_user(self.approver).action_approve()
        self.assertEqual(batch.state, 'approved', "nobody else could approve it")

    def test_f4_unauthorized_cannot_approve(self):
        batch = self._calculated(self.cfg_ae)
        with self.fake_attendance():
            batch.action_submit()
        # only Payroll Admins: not an Officer, not a Manager, not a plain user
        for user in (self.stranger, self.officer_ae, self.payroll_admin):
            for action in ('action_approve', 'action_open_reject_wizard', 'action_open_resubmit_wizard'):
                with self.assertRaises(AccessError):
                    getattr(batch.with_user(user), action)()
        # an Admin who submitted the batch cannot approve it while another Admin exists
        batch.sudo().submitted_by = self.approver
        with self.assertRaises(AccessError):
            batch.with_user(self.approver).action_approve()
        self.assertEqual(batch.state, 'submitted')
        batch.with_user(self.approver_in).action_approve()
        self.assertEqual(batch.state, 'approved')

    def test_f5_approve_notifies_officers_and_managers_once(self):
        batch = self._approved(self.cfg_in, self.emp_in | self.emp_in_low)
        self.assertEqual(batch.approved_by, self.approver)
        self.assertTrue(batch.approved_date)
        slips = batch.sudo().line_ids.payslip_id
        self.assertEqual(set(slips.mapped('state')), {'done'})
        self.assertEqual(set(batch.sudo().line_ids.mapped('email_status')), {'pending'})
        self.assertFalse(self._mails_to(self.emp_in.work_email), "approval never emails employees by itself")
        notified = batch.sudo().notify_log_ids.filtered(lambda l: l.kind == 'approved_officer').user_id
        self.assertIn(self.officer_in, notified, "the India Payroll Officer")
        self.assertIn(self.payroll_admin, notified, "the Payroll Manager gets the same mail")
        self.assertNotIn(self.officer_ae, notified, "Dubai officers get no India notification")
        self.assertNotIn(self.stranger, notified)
        before = len(batch.sudo().notify_log_ids)
        batch.sudo()._notify_country_officers()
        self.assertEqual(len(batch.sudo().notify_log_ids), before, "no duplicate notification")
        with self.assertRaises(UserError):
            self._line(batch, self.emp_in).with_user(self.officer_in).write({'basic': 5.0})

    def test_f7_resubmission_back_to_the_preparer(self):
        batch = self._calculated(self.cfg_ae)
        with self.fake_attendance():
            batch.action_submit()
        action = batch.with_user(self.approver).action_open_resubmit_wizard()
        self.assertEqual(action['context']['default_mode'], 'resubmit')
        Wizard = self.env['payroll.country.reject.wizard'].with_user(self.approver)
        with self.assertRaises(UserError):
            Wizard.create({'batch_id': batch.id, 'mode': 'resubmit', 'reason': '  '}).action_confirm()
        Wizard.create({'batch_id': batch.id, 'mode': 'resubmit',
                       'reason': 'Check PC Dubai Two overtime'}).action_confirm()
        self.assertEqual(batch.state, 'resubmit')
        self.assertEqual((batch.resubmit_reason, batch.resubmit_by), ('Check PC Dubai Two overtime', self.approver))
        self.assertTrue(batch.sudo().message_ids.filtered(lambda m: 'Check PC Dubai Two overtime' in (m.body or '')),
                        "the reason is in the chatter")
        logs = batch.sudo().notify_log_ids.filtered(lambda l: l.kind == 'resubmit')
        self.assertEqual(logs.user_id, self.officer_ae, "mailed to the preparer only")
        self.assertIn('Check PC Dubai Two overtime', logs.mail_id.body_html)
        self.assertFalse(batch.sudo().notify_log_ids.filtered(lambda l: l.kind in ('rejected', 'approved_officer')))
        # the preparer checks / edits and submits again
        with self.fake_attendance():
            self._line(batch, self.emp_ae).with_user(self.officer_ae).write({'hra': 3400.0})
            # Submit straight from Resubmission Requested: recalculated first, then submitted
            res = batch.with_user(self.officer_ae).action_submit()
        self.assertEqual(batch.state, 'submitted', res['params']['message'])
        self.assertEqual(batch.submission_round, 2)
        self.assertEqual(self._line(batch, self.emp_ae).hra, 3400.0, "the correction is kept")
        self.assertTrue(batch.sudo().message_ids.filtered(lambda m: 'Payroll calculated' in (m.body or '')),
                        "recalculated before the new submission")

    def test_f6_reject_needs_reason_and_allows_resubmit(self):
        batch = self._calculated(self.cfg_ae)
        with self.fake_attendance():
            batch.action_submit()
        wizard = self.env['payroll.country.reject.wizard'].with_user(self.approver)
        with self.assertRaises(UserError):
            batch.with_user(self.approver)._do_reject('   ')
        wizard.create({'batch_id': batch.id, 'reason': 'HRA wrong for PC Dubai One'}).action_confirm()
        self.assertEqual(batch.state, 'rejected')
        self.assertEqual(batch.rejection_reason, 'HRA wrong for PC Dubai One')
        self.assertEqual(batch.rejected_by, self.approver)
        rejected_to = batch.sudo().notify_log_ids.filtered(lambda l: l.kind == 'rejected').user_id
        self.assertIn(self.officer_ae, rejected_to, "the Dubai Payroll Officer")
        self.assertIn(self.payroll_admin, rejected_to, "and the Payroll Manager")
        self.assertNotIn(self.officer_in, rejected_to)
        # correct + recalculate + resubmit
        with self.fake_attendance():
            self._line(batch, self.emp_ae).with_user(self.officer_ae).write({'hra': 3500.0})
            res = batch.action_submit()                               # straight from Rejected
        self.assertEqual(batch.state, 'submitted', res['params']['message'])
        self.assertEqual(batch.submission_round, 2)

    # ---------------------------------------------------------------- G
    def test_g1_send_requires_selection_or_send_all(self):
        batch = self._approved(self.cfg_ae, self.emp_ae | self.emp_ae2)
        officer_batch = batch.with_user(self.officer_ae)
        mails_before = self.env['mail.mail'].sudo().search_count([])
        wizard = self.env['payroll.country.send.wizard'].browse(officer_batch.action_send_selected()['res_id'])
        with self.assertRaises(UserError):
            wizard.with_user(self.officer_ae).action_send()
        with self.assertRaises(UserError):
            self.env['payroll.country.line'].with_user(self.officer_ae).action_send_payslips()
        self.assertEqual(self.env['mail.mail'].sudo().search_count([]), mails_before, "nothing sent")

    def test_g2_send_selected_only(self):
        batch = self._approved(self.cfg_ae, self.emp_ae | self.emp_ae2)
        one = self._line(batch, self.emp_ae)
        two = self._line(batch, self.emp_ae2)
        # Send Selected = popup listing every employee of the batch, each with a Select tick
        action = batch.with_user(self.officer_ae).action_send_selected()
        wizard = self.env['payroll.country.send.wizard'].with_user(self.officer_ae).browse(action['res_id'])
        self.assertEqual(wizard.line_ids.payroll_line_id, one | two, "all employees listed")
        self.assertFalse(wizard.line_ids.filtered('selected'), "nobody pre-selected")
        wizard.action_select_unsent()
        self.assertEqual(wizard.selected_count, 2)
        wizard.action_clear()
        wizard.line_ids.filtered(lambda r: r.payroll_line_id == one).selected = True
        wizard.action_send()
        self.assertEqual(one.email_status, 'queued')
        self.assertEqual(two.email_status, 'pending', "unselected stays pending / unsent")
        self.assertFalse(one.send_selected)
        mail = one.send_log_ids.mail_id
        self.assertEqual(mail.email_to, self.emp_ae.work_email)
        self.assertIn('Your Payslip for March 2039', mail.subject)
        self.assertIn(self.co_ae.name, mail.subject)
        self.assertEqual(len(mail.attachment_ids), 1, "the payslip PDF is attached to this email")
        self.assertIn('attached', mail.body_html)
        self.assertFalse(mail.model, "not posted in the chatter")
        self.assertNotIn('%.2f' % one.net, mail.body_html.replace(',', ''), "no salary figures in the email")
        self.assertFalse(self._mails_to(self.emp_ae2.work_email))
        unsent = self.env['payroll.country.line'].with_user(self.officer_ae).search(
            [('batch_id', '=', batch.id), ('email_status', '!=', 'sent')])
        self.assertIn(two, unsent)

    def test_g3_send_all_and_no_duplicates(self):
        noemail = self._employee('PC No Email', 'dubai', self.co_ae, wage=5000, basic_salary=5000, email=False)
        batch = self._approved(self.cfg_ae, self.emp_ae | self.emp_ae2 | noemail)
        self.assertEqual(self._line(batch, noemail).email_status, 'no_email')
        batch.with_user(self.officer_ae).action_send_all()
        self.assertEqual(self._line(batch, self.emp_ae).email_status, 'queued')
        self.assertEqual(self._line(batch, self.emp_ae2).email_status, 'queued')
        self.assertEqual(self._line(batch, noemail).email_status, 'no_email')
        count = len(self._mails_to(self.emp_ae.work_email))
        # second Send All: only the no-email one is left and it still has no email
        batch.with_user(self.officer_ae).action_send_all()
        self.assertEqual(len(self._mails_to(self.emp_ae.work_email)), count, "already queued: not resent")
        # explicit selection of an already sent one is skipped too
        line = self._line(batch, self.emp_ae)
        line.with_user(self.officer_ae).action_send_payslips()
        self.assertEqual(len(self._mails_to(self.emp_ae.work_email)), count)

    def test_g4_real_mail_state_tracked_and_resend(self):
        batch = self._approved(self.cfg_ae, self.emp_ae | self.emp_ae2)
        line = self._line(batch, self.emp_ae)
        line.with_user(self.officer_ae).action_send_payslips()
        mail = line.send_log_ids.mail_id
        mail.write({'state': 'exception', 'failure_reason': 'SMTP 535 auth failed'})
        self.assertEqual(line.email_status, 'failed')
        self.assertIn('535', line.email_error)
        line.with_user(self.officer_ae).action_send_payslips()        # failed -> retried
        self.assertEqual(line.email_status, 'queued')
        self.assertEqual(len(line.send_log_ids), 2)
        latest = line.send_log_ids.sorted('id', reverse=True)[0]
        self.assertEqual(latest.attempt, 2)
        latest.mail_id.write({'state': 'sent'})
        self.assertEqual(line.email_status, 'sent')
        self.assertTrue(line.email_sent_date)
        line.with_user(self.officer_ae).action_resend_payslip()
        self.assertEqual(len(line.send_log_ids), 3)

    def test_g5_cannot_send_before_approval_or_other_country(self):
        batch = self._calculated(self.cfg_ae)
        line = self._line(batch, self.emp_ae)
        with self.assertRaises(UserError):
            line.with_user(self.officer_ae).action_send_payslips()
        approved = self._approved(self.cfg_in, self.emp_in | self.emp_in_low)
        with self.assertRaises(AccessError):
            self._line(approved, self.emp_in).with_user(self.officer_ae).action_send_payslips()

    # ---------------------------------------------------------------- H
    def test_h1_self_service_sees_own_approved_only(self):
        approved = self._approved(self.cfg_in, self.emp_in | self.emp_in_low)
        draft = self._calculated(self.cfg_ae)
        Payslip = self.env['hr.payslip']
        me = self.emp_in.user_id
        mine = Payslip.with_user(me).search([])
        self.assertEqual(mine, self._line(approved, self.emp_in).payslip_id)
        self.assertFalse(Payslip.with_user(self.emp_ae.user_id).search([]), "draft payslips are hidden")
        other = self._line(approved, self.emp_in_low).payslip_id
        with self.assertRaises(AccessError):
            other.with_user(me).read(['number'])
        with self.assertRaises(AccessError):
            other.with_user(me).action_download_my_payslip()
        res = mine.with_user(me).action_download_my_payslip()
        self.assertEqual(res['url'], '/payroll/my-payslip/%s/download' % mine.id)
        self.assertEqual(mine.with_user(me).payroll_month, '3')
        self.assertEqual(mine.with_user(me).payroll_year, '2039')
        # employees cannot change payroll
        with self.assertRaises(AccessError):
            mine.with_user(me).write({'name': 'x'})
        self.assertFalse(self.env['payroll.country.line'].with_user(me).search([]))
        with self.assertRaises(AccessError):
            self.Batch.with_user(me).create({'payroll_country_id': self.cfg_in.id})
        self.assertFalse(draft.sudo().line_ids.payslip_id.with_user(self.emp_ae.user_id)._filtered_access('read'))

    def test_h2_rejected_and_submitted_hidden(self):
        batch = self._calculated(self.cfg_ae)
        with self.fake_attendance():
            batch.action_submit()
        user = self.emp_ae.user_id
        self.assertFalse(self.env['hr.payslip'].with_user(user).search([]), "submitted payslip hidden")
        batch.with_user(self.approver)._do_reject('no')
        self.assertFalse(self.env['hr.payslip'].with_user(user).search([]), "rejected payslip hidden")

    def test_h3_report_respects_rights(self):
        batch = self._calculated(self.cfg_ae)
        wiz = self.env['payroll.country.report.wizard'].with_user(self.officer_ae).create({
            'payroll_country_id': self.cfg_ae.id, 'month': '3', 'year': '2039', 'output': 'xlsx'})
        self.assertIn(self._line(batch, self.emp_ae), wiz._get_lines())
        res = wiz.action_generate()
        self.assertEqual(res['type'], 'ir.actions.act_url')
        self.assertTrue(wiz.file_data)
        stranger_wiz = self.env['payroll.country.report.wizard'].with_user(self.stranger).create({
            'payroll_country_id': self.cfg_ae.id, 'month': '3', 'year': '2039'})
        self.assertFalse(stranger_wiz._get_lines())
        pdf_wiz = self.env['payroll.country.report.wizard'].with_user(self.officer_ae).create({
            'payroll_country_id': self.cfg_ae.id, 'month': '3', 'year': '2039', 'output': 'pdf'})
        html, _fmt = self.env['ir.actions.report'].with_user(self.officer_ae)._render_qweb_html(
            'om_hr_payroll_extended_gk.report_payroll_register', pdf_wiz.ids)
        self.assertIn(b'PC Dubai One', html)

    def test_g9_report_companies_default_to_the_batch(self):
        """Generate Report from a batch: Companies = the batch's companies (removable)."""
        batch = self._calculated(self.cfg_ae)
        companies = batch.sudo().company_ids
        action = batch.with_user(self.officer_ae).action_generate_report()
        wizard = self.env['payroll.country.report.wizard'].browse(action['res_id'])
        self.assertEqual(wizard.company_ids, companies)
        self.assertTrue(companies <= wizard.allowed_company_ids)
        # opened from the menu: picking the period fills the companies of that period's batches
        from odoo.tests import Form
        f = Form(self.env['payroll.country.report.wizard'].with_user(self.officer_ae))
        f.payroll_country_id = self.cfg_ae
        f.month = batch.month
        f.year = batch.year
        self.assertEqual(f.save().company_ids, companies)

    def test_g10_download_payslip_and_reference(self):
        batch = self._approved(self.cfg_ae, self.emp_ae | self.emp_ae2)
        line = self._line(batch, self.emp_ae)
        self.assertEqual(line.payslip_ref, line.payslip_id.number, "the reference is the payslip's number")
        line.payslip_id.sudo().number = 'SLIP/TEST-1'
        self.assertEqual(line.payslip_ref, 'SLIP/TEST-1', "follows the payslip")
        lines = batch.sudo().line_ids
        res = lines.with_user(self.officer_ae).action_download_payslip()
        self.assertEqual(res['report_name'], 'om_hr_payroll.report_payslip')
        self.assertEqual(set(res['context']['active_ids']), set(lines.payslip_id.ids))
        pdf, _fmt = self.env['ir.actions.report'].with_user(self.officer_ae)._render_qweb_pdf(
            'om_hr_payroll.report_payslip', lines.payslip_id.ids)
        self.assertTrue(pdf, "the officer can render the payslip (HTML in test mode, PDF live)")
        with self.assertRaises(AccessError):
            lines.with_user(self.officer_in).action_download_payslip()        # another country's officer
        action = self.env.ref('om_hr_payroll_extended_gk.action_server_download_payslip')
        self.assertEqual(action.binding_model_id.model, 'payroll.country.line', "in the gear (Actions) menu")
