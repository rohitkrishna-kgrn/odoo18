import base64
import io
import zipfile

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase

FILE = base64.b64encode(b'%PDF-1.4 test')


@tagged('post_install', '-at_install', 'hr_dms')
class TestHrDms(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)

        def mk(login, groups=()):
            user = Users.create({
                'name': login, 'login': login, 'email': f'{login}@example.com',
                'groups_id': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('hr_dms.group_hr_dms_employee').id] +
                               [cls.env.ref(g).id for g in groups])],
            })
            emp = cls.env['hr.employee'].create({'name': login, 'user_id': user.id})
            return user, emp

        cls.alice, cls.alice_emp = mk('hrdms_alice')
        cls.bob, cls.bob_emp = mk('hrdms_bob')
        cls.officer, cls.officer_emp = mk('hrdms_officer', ['hr_dms.group_hr_dms_manager'])
        cls.manager, cls.manager_emp = mk('hrdms_manager', ['hr_dms.group_hr_dms_manager'])
        cls.conf, cls.conf_emp = mk('hrdms_conf', ['hr_dms.group_hr_dms_confidential',
                                                   'hr_dms.group_hr_dms_manager'])
        cls.admin, cls.admin_emp = mk('hrdms_admin', ['hr_dms.group_hr_dms_admin'])
        cls.cat_id = cls.env.ref('hr_dms.cat_personal_id')
        cls.cat_contract = cls.env.ref('hr_dms.cat_contract')
        cls.cat_salary = cls.env.ref('hr_dms.cat_salary')
        # live admins may have retuned the category; pin the fixture
        cls.cat_salary.sudo().write({'confidential': True, 'employee_can_view': False,
                                     'employee_can_upload': False, 'employee_can_edit': False,
                                     'employee_can_download': False})
        cls.cat_contract.sudo().write({'confidential': False, 'employee_can_view': True,
                                       'employee_can_upload': False, 'employee_can_edit': False,
                                       'employee_can_download': True})
        cls.cat_id.sudo().write({'employee_can_view': True,
                                 'employee_can_upload': True, 'employee_can_edit': True,
                                 'employee_can_download': True})

    def _upload(self, user, doc=None, name='doc.pdf'):
        # what /web/binary/upload_attachment does for the Files widget (res_id 0 on an unsaved form)
        return self.env['ir.attachment'].with_user(user).create({
            'name': name, 'raw': base64.b64decode(FILE), 'res_model': 'hr.dms.document',
            'res_id': doc.id if doc else 0})

    def _doc(self, user, emp, cat, filename='doc.pdf', submit=True, **kw):
        vals = {'name': 'Doc', 'employee_id': emp.id, 'category_id': cat.id,
                'attachment_ids': [(4, self._upload(user, name=filename).id)]}
        vals.update(kw)
        doc = self.env['hr.dms.document'].with_user(user).create(vals)
        if submit:
            doc.with_user(user).action_submit()
        return doc

    def _add(self, user, doc, name='more.pdf'):
        att = self._upload(user, doc, name)
        doc.with_user(user).write({'attachment_ids': [(4, att.id)]})
        return att

    # ---------------------------------------------------------------- 1. employee
    def test_employee_sees_only_own(self):
        a = self._doc(self.alice, self.alice_emp, self.cat_id)
        b = self._doc(self.bob, self.bob_emp, self.cat_id)
        Doc = self.env['hr.dms.document']
        self.assertEqual(Doc.with_user(self.alice).search([('id', 'in', (a | b).ids)]), a)
        with self.assertRaises(AccessError):
            b.with_user(self.alice).read(['name'])
        with self.assertRaises(AccessError):
            b.with_user(self.alice).write({'name': 'hack'})

    def test_employee_cannot_upload_for_someone_else(self):
        doc = self._doc(self.alice, self.bob_emp, self.cat_id)
        self.assertEqual(doc.employee_id, self.alice_emp)   # forced to own profile

    def test_employee_category_permissions(self):
        # contracts: view/download only
        with self.assertRaises(AccessError):
            self._doc(self.alice, self.alice_emp, self.cat_contract)
        contract = self._doc(self.officer, self.alice_emp, self.cat_contract)
        got = contract.with_user(self.alice)
        self.assertEqual(got.name, 'Doc')
        with self.assertRaises(AccessError):
            got.write({'name': 'edited'})
        self.assertTrue(got.can_download)

    def test_employee_edits_only_in_draft(self):
        doc = self._doc(self.alice, self.alice_emp, self.cat_id, submit=False)
        doc.with_user(self.alice).write({'notes': 'updated'})
        doc.with_user(self.alice).action_submit()
        # Submitted, Rejected and Approved are all read-only for the employee
        for step in (None, lambda: doc.with_user(self.manager).action_reject('blurry'),
                     lambda: doc.with_user(self.manager).action_approve()):
            if step:
                step()
            with self.subTest(state=doc.state):
                self.assertFalse(doc.with_user(self.alice).can_edit)
                self.assertFalse(doc.with_user(self.alice).can_add_files)
                with self.assertRaises(AccessError):
                    doc.with_user(self.alice).write({'notes': 'again'})
                with self.assertRaises(AccessError):
                    self._add(self.alice, doc, 'later.pdf')
                self.assertEqual(doc.notes, 'updated')

    def test_employee_cannot_touch_protected_fields(self):
        doc = self._doc(self.alice, self.alice_emp, self.cat_id)
        for vals in ({'state': 'approved'}, {'category_id': self.cat_salary.id},
                     {'employee_id': self.bob_emp.id}, {'approved_by': self.alice.id}):
            with self.assertRaises(AccessError):
                doc.with_user(self.alice).write(vals)

    def test_download_flag(self):
        self.cat_id.employee_can_download = False
        doc = self._doc(self.alice, self.alice_emp, self.cat_id)
        att = doc.attachment_ids
        self.assertEqual((att.res_id, att.name), (doc.id, 'doc.pdf'))
        # the Files widget still lists name and type ...
        self.assertEqual(att.with_user(self.alice).read(['name', 'mimetype'])[0]['name'], 'doc.pdf')
        self.assertEqual(doc.with_user(self.alice).web_read({'attachment_ids': {'fields': {'name': {}}}})
                         [0]['attachment_ids'][0]['name'], 'doc.pdf')
        # ... but every content path is blocked
        A = att.with_user(self.alice)
        for call in (lambda: A.read(['datas']), lambda: A.read(['raw']), lambda: A.read(),
                     lambda: A.search_read([('id', '=', att.id)], ['datas']),
                     lambda: doc.with_user(self.alice).export_data(['attachment_ids/datas']),
                     lambda: A.check('read'),
                     lambda: self.env['ir.binary'].with_user(self.alice)._get_stream_from(A)):
            with self.subTest(call=call), self.assertRaises(UserError):   # AccessError or no export right
                call()
        # the Download button follows the same rule
        with self.assertRaises(AccessError):
            doc.with_user(self.alice).action_download_files()
        # HR can fetch it, and the download is logged (streaming itself needs an HTTP request)
        att.with_user(self.officer).check('read')
        self.assertTrue(self.env['hr.dms.audit.log'].search(
            [('document_id', '=', doc.id), ('action', '=', 'download'), ('user_id', '=', self.officer.id)]))
        self.assertTrue(att.with_user(self.officer).read(['datas'])[0]['datas'])

    # ------------------------------------------------------------------- 2. HR
    def test_hr_manages_any_employee_document(self):
        a = self._doc(self.alice, self.alice_emp, self.cat_id)
        b = self._doc(self.officer, self.bob_emp, self.cat_id)
        Doc = self.env['hr.dms.document'].with_user(self.officer)
        self.assertEqual(Doc.search([('id', 'in', (a | b).ids)]), a | b)
        a.with_user(self.officer).write({'name': 'renamed',
                                         'attachment_ids': [(1, a.attachment_ids.id, {'hr_dms_expiry_date': '2030-01-01'})]})
        self.assertEqual(str(a.expiry_date), '2030-01-01')
        self.assertEqual(a.name, 'renamed')
        a.with_user(self.officer).action_approve()
        self.assertEqual(a.state, 'approved')
        a.with_user(self.officer).unlink()
        self.assertFalse(a.exists())

    def test_employee_edits_and_adds_files_in_draft(self):
        a = self._doc(self.alice, self.alice_emp, self.cat_id, submit=False)
        a.with_user(self.alice).write({'name': 'mine', 'notes': 'n'})
        self.assertEqual(a.name, 'mine')
        self._add(self.alice, a, 'x.pdf')
        self.assertEqual(sorted(a.attachment_ids.mapped('name')), ['doc.pdf', 'x.pdf'])
        self.assertTrue(a.with_user(self.alice).can_add_files)
        self.assertTrue(a.with_user(self.alice).can_edit)
        a.with_user(self.alice).action_submit()
        with self.assertRaises(AccessError):
            self._add(self.alice, a, 'y.pdf')
        self.assertFalse(a.with_user(self.alice).can_add_files)

    def test_several_files_in_one_upload(self):
        atts = self._upload(self.alice, name='a.pdf') | self._upload(self.alice, name='b.png') \
            | self._upload(self.alice, name='c.docx')
        doc = self.env['hr.dms.document'].with_user(self.alice).create({
            'name': 'Degree', 'category_id': self.cat_id.id, 'attachment_ids': [(6, 0, atts.ids)]})
        self.assertEqual(doc.file_count, 3)
        self.assertEqual(set(atts.mapped('res_id')), {doc.id})

    def test_upload_only_locked_after_submit(self):
        self.cat_id.sudo().write({'employee_can_edit': False})
        a = self._doc(self.alice, self.alice_emp, self.cat_id, submit=False)
        # more files while in Draft: yes
        self._add(self.alice, a, 'second.pdf')
        self.assertEqual(a.file_count, 2)
        a.with_user(self.alice).action_submit()
        self.assertFalse(a.with_user(self.alice).can_edit)
        self.assertFalse(a.with_user(self.alice).can_remove_files)
        # after Submit: no fields, no files in or out
        first = a.attachment_ids.filtered(lambda x: x.name == 'doc.pdf')
        for vals in ({'name': 'x'}, {'attachment_ids': [(3, first.id)]}, {'attachment_ids': [(6, 0, [])]},
                     {'attachment_ids': [(4, self._upload(self.alice).id)], 'notes': 'n'}):
            with self.assertRaises(AccessError):
                a.with_user(self.alice).write(vals)
        for call in (lambda: first.with_user(self.alice).unlink(),
                     lambda: first.with_user(self.alice).write({'raw': b'swapped'}),
                     lambda: first.with_user(self.alice).write({'res_id': 0})):
            with self.assertRaises(AccessError):
                call()
        # HR removes it, and the file goes with it
        a.with_user(self.manager).write({'attachment_ids': [(3, first.id)]})
        self.assertEqual(a.attachment_ids.mapped('name'), ['second.pdf'])
        self.assertFalse(first.exists())

    def test_update_never_removes_file(self):
        a = self._doc(self.alice, self.alice_emp, self.cat_id)
        with self.assertRaises(AccessError):
            a.with_user(self.alice).write({'attachment_ids': [(5, 0, 0)]})
        self.assertEqual(a.file_count, 1)

    def test_cannot_link_foreign_attachment(self):
        mine = self._doc(self.alice, self.alice_emp, self.cat_id, submit=False)
        sal = self._doc(self.conf, self.bob_emp, self.cat_salary)
        # bob's confidential file, an unsaved upload by someone else, and an unrelated attachment
        stray = self._upload(self.bob, name='bob.pdf')
        other = self.env['ir.attachment'].create({'name': 'x.pdf', 'raw': b'x', 'res_model': 'res.partner',
                                                  'res_id': self.alice.partner_id.id})
        for att in (sal.attachment_ids, stray, other):
            with self.subTest(att=att.name), self.assertRaises(AccessError):
                mine.with_user(self.alice).write({'attachment_ids': [(4, att.id)]})
        self.assertEqual(sal.attachment_ids.res_id, sal.id)

    def test_every_category_goes_through_approval(self):
        # employee upload, HR upload, and a confidential category alike
        docs = (self._doc(self.alice, self.alice_emp, self.cat_id)
                | self._doc(self.manager, self.alice_emp, self.cat_contract)
                | self._doc(self.conf, self.alice_emp, self.cat_salary))
        self.assertEqual(set(docs.mapped('state')), {'submitted'})
        self.assertTrue(all(docs.with_user(self.admin).mapped('can_approve')))
        self.assertEqual(self.env['hr.dms.document'].with_user(self.admin).search(
            [('id', 'in', docs.ids), ('state', '=', 'submitted')]), docs)
        docs.with_user(self.admin).action_approve()
        self.assertEqual(set(docs.mapped('state')), {'approved'})
        self.assertFalse(any(docs.with_user(self.admin).mapped('can_approve')))

    def test_draft_then_submit(self):
        self.cat_id.sudo().write({'employee_can_edit': False})   # upload-only
        doc = self._doc(self.alice, self.alice_emp, self.cat_id, submit=False)
        self.assertEqual(doc.state, 'draft')
        self.assertFalse(doc.with_user(self.manager).can_approve)
        with self.assertRaises(UserError):
            doc.with_user(self.manager).action_approve()
        # a draft is editable even without "Employee can update"
        doc.with_user(self.alice).write({'name': 'Passport'})
        with self.assertRaises(AccessError):
            doc.with_user(self.bob).action_submit()
        # ... files included: a wrong upload can be taken off before submitting
        extra = self._add(self.alice, doc, 'wrong.pdf')
        self.assertTrue(doc.with_user(self.alice).can_remove_files)
        doc.with_user(self.alice).write({'attachment_ids': [(3, extra.id)]})
        self.assertEqual(doc.attachment_ids.mapped('name'), ['doc.pdf'])
        self.assertFalse(extra.exists())
        doc.with_user(self.alice).action_submit()
        self.assertEqual(doc.state, 'submitted')
        self.assertFalse(doc.with_user(self.alice).can_remove_files)
        with self.assertRaises(AccessError):
            doc.with_user(self.alice).write({'attachment_ids': [(3, doc.attachment_ids.id)]})
        with self.assertRaises(AccessError):
            doc.with_user(self.alice).write({'name': 'again'})
        empty = self.env['hr.dms.document'].with_user(self.alice).create(
            {'name': 'No file', 'category_id': self.cat_id.id})
        with self.assertRaises(UserError):
            empty.with_user(self.alice).action_submit()

    def test_move_to_draft_mails_employee_only(self):
        self.alice_emp.sudo().work_email = 'alice.work@example.com'
        doc = self._doc(self.alice, self.alice_emp, self.cat_id)
        doc.sudo().message_subscribe(partner_ids=self.bob.partner_id.ids)
        with self.assertRaises(AccessError):
            doc.with_user(self.alice).action_open_draft_wizard()
        Mail = self.env['mail.mail'].sudo()
        before = Mail.search([]).ids
        wiz = self.env['hr.dms.draft.wizard'].with_user(self.manager).with_context(
            doc.with_user(self.manager).action_open_draft_wizard()['context']).create({'reason': 'Scan is blurry'})
        wiz.action_confirm()
        self.assertEqual((doc.state, doc.correction_reason), ('draft', 'Scan is blurry'))
        note = doc.message_ids.filtered(lambda m: 'Scan is blurry' in (m.body or ''))
        self.assertEqual(len(note), 1)
        self.assertIn('<b>', note.body)
        self.assertEqual(note.subtype_id, self.env.ref('mail.mt_note'))
        mails = Mail.search([('id', 'not in', before)])
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails.email_to, 'alice.work@example.com')
        self.assertFalse(mails.recipient_ids)
        self.assertIn('Scan is blurry', mails.body_html)
        self.assertFalse(mails.auto_delete)
        self.assertTrue(self.env['hr.dms.audit.log'].search([('document_id', '=', doc.id), ('action', '=', 'draft')]))
        # the employee corrects it and submits again; a Draft cannot be moved to Draft again
        doc.with_user(self.alice).write({'notes': 'rescanned'})
        self._add(self.alice, doc, 'clear.pdf')
        with self.assertRaises(AccessError):
            doc.with_user(self.manager).action_move_to_draft('again')
        doc.with_user(self.alice).action_submit()
        self.assertEqual(doc.state, 'submitted')
        # a Rejected document can go back to Draft too, which clears the rejection
        doc.with_user(self.manager).action_reject('wrong file')
        self.assertTrue(doc.with_user(self.manager).can_reset_draft)
        doc.with_user(self.manager).action_move_to_draft('upload the signed copy')
        self.assertEqual(doc.state, 'draft')
        self.assertFalse(doc.reject_reason)
        doc.with_user(self.alice).action_submit()
        doc.with_user(self.manager).action_approve()
        self.assertFalse(doc.correction_reason)
        # an Approved document cannot
        with self.assertRaises(AccessError):
            doc.with_user(self.manager).action_move_to_draft('again')

    def test_expiry_per_file(self):
        # what the Files widget sends: link the new upload and set its date in the same save
        new = self._upload(self.alice, name='visa.pdf')
        doc = self.env['hr.dms.document'].with_user(self.alice).create({
            'name': 'Visa', 'category_id': self.cat_id.id,
            'attachment_ids': [(4, new.id), (1, new.id, {'hr_dms_expiry_date': '2030-06-30'})]})
        other = self._upload(self.alice, doc, 'emirates_id.pdf')
        doc.with_user(self.alice).write({'attachment_ids': [(4, other.id), (1, other.id, {'hr_dms_expiry_date': '2029-01-31'})]})
        self.assertEqual(str(new.hr_dms_expiry_date), '2030-06-30')
        self.assertEqual(str(doc.expiry_date), '2029-01-31')    # the earliest file wins
        self.assertIn('emirates_id.pdf (expires 2029-01-31)', self.env['hr.dms.audit.log'].search(
            [('document_id', '=', doc.id), ('action', '=', 'modify')], limit=1).details)
        doc.with_user(self.alice).write({'attachment_ids': [(1, other.id, {'hr_dms_expiry_date': False})]})
        self.assertEqual(str(doc.expiry_date), '2030-06-30')
        # the expiry date is the only file field an employee may touch
        with self.assertRaises(AccessError):
            doc.with_user(self.alice).write({'attachment_ids': [(1, other.id, {'name': 'renamed.pdf'})]})
        with self.assertRaises(AccessError):
            doc.with_user(self.bob).write({'attachment_ids': [(1, other.id, {'hr_dms_expiry_date': '2031-01-01'})]})
        # after approval it is locked for the employee, HR can still change it
        doc.with_user(self.alice).action_submit()
        doc.with_user(self.manager).action_approve()
        with self.assertRaises(AccessError):
            doc.with_user(self.alice).write({'attachment_ids': [(1, new.id, {'hr_dms_expiry_date': '2031-01-01'})]})
        doc.with_user(self.manager).write({'attachment_ids': [(1, new.id, {'hr_dms_expiry_date': '2031-01-01'})]})
        self.assertEqual(str(doc.expiry_date), '2031-01-01')

    def test_upload_only_dates_files_while_draft(self):
        self.cat_id.sudo().write({'employee_can_edit': False})
        doc = self._doc(self.alice, self.alice_emp, self.cat_id, submit=False)
        added = self._upload(self.alice, doc, 'renewed.pdf')
        doc.with_user(self.alice).write({'attachment_ids': [(4, added.id), (1, added.id, {'hr_dms_expiry_date': '2030-01-01'})]})
        self.assertEqual(str(added.hr_dms_expiry_date), '2030-01-01')
        hr_file = self._upload(self.manager, doc, 'hr.pdf')
        doc.with_user(self.manager).write({'attachment_ids': [(4, hr_file.id)]})
        # a Draft is the employee's to correct, including the date on a file HR added
        doc.with_user(self.alice).write({'attachment_ids': [(1, hr_file.id, {'hr_dms_expiry_date': '2030-01-01'})]})
        # after Submit no file can be dated, not even their own
        doc.with_user(self.alice).action_submit()
        for att in (added, hr_file):
            with self.assertRaises(AccessError):
                doc.with_user(self.alice).write({'attachment_ids': [(1, att.id, {'hr_dms_expiry_date': '2031-01-01'})]})

    # ------------------------------------------------------------ 3. confidential
    def test_confidential_hidden(self):
        sal = self._doc(self.conf, self.alice_emp, self.cat_salary, name='Salary')
        for user in (self.alice, self.bob):
            Doc = self.env['hr.dms.document'].with_user(user)
            self.assertFalse(Doc.search([('id', '=', sal.id)]), user.login)
            with self.assertRaises(AccessError):
                sal.with_user(user).read(['name'])
        # HR Manager implies Confidential Records Access, and Administrator implies HR Manager
        for user in (self.conf, self.officer, self.manager, self.admin):
            self.assertEqual(self.env['hr.dms.document'].with_user(user).search([('id', '=', sal.id)]), sal,
                             user.login)
        # employees cannot even see the category
        self.assertFalse(self.env['hr.dms.category'].with_user(self.alice).search(
            [('id', '=', self.cat_salary.id)]))
        # nor upload into it
        with self.assertRaises(AccessError):
            self._doc(self.alice, self.alice_emp, self.cat_salary)

    def test_category_toggled_confidential_hides_existing(self):
        doc = self._doc(self.alice, self.alice_emp, self.cat_id)
        self.assertTrue(doc.with_user(self.alice).read(['name']))
        self.cat_id.with_user(self.admin).write({
            'confidential': True, 'employee_can_view': False, 'employee_can_upload': False,
            'employee_can_edit': False, 'employee_can_download': False})
        self.assertFalse(self.env['hr.dms.document'].with_user(self.alice).search([('id', '=', doc.id)]))

    def test_confidential_category_has_no_employee_access(self):
        for flag in ('employee_can_view', 'employee_can_edit', 'employee_can_download'):
            with self.subTest(flag=flag), self.assertRaises(ValidationError):
                self.cat_salary.with_user(self.admin).write({flag: True})
        with self.assertRaises(ValidationError):        # contract gives employees view/download
            self.cat_contract.with_user(self.admin).write({'confidential': True})
        # unticking confidential first lets employees in
        self.cat_salary.with_user(self.admin).write({'confidential': False, 'employee_can_view': True})
        self.assertTrue(self.cat_salary.employee_can_view)

    # ------------------------------------------------------------------- 4. RBAC
    def test_only_admin_edits_categories(self):
        for user in (self.alice, self.officer, self.manager, self.conf):
            with self.assertRaises(AccessError, msg=user.login):
                self.cat_id.with_user(user).write({'employee_can_upload': False})
        self.cat_id.with_user(self.admin).write({'employee_can_upload': False})
        self.assertFalse(self.cat_id.employee_can_upload)

    def test_delete_requires_manager_and_is_logged(self):
        doc = self._doc(self.alice, self.alice_emp, self.cat_id)
        with self.assertRaises(AccessError):
            doc.with_user(self.alice).unlink()
        doc_id = doc.id
        doc.with_user(self.manager).unlink()
        log = self.env['hr.dms.audit.log'].search([('action', '=', 'delete'), ('document_name', '=', 'Doc')],
                                                  order='id desc', limit=1)
        self.assertTrue(log)
        self.assertEqual(log.user_id, self.manager)
        self.assertFalse(self.env['hr.dms.document'].browse(doc_id).exists())

    def test_approval_rules(self):
        doc = self._doc(self.alice, self.alice_emp, self.cat_id)
        with self.assertRaises(AccessError):
            doc.with_user(self.alice).action_approve()
        # a manager cannot approve their own document
        own = self._doc(self.manager, self.manager_emp, self.cat_id)
        with self.assertRaises(AccessError):
            own.with_user(self.manager).action_approve()
        doc.with_user(self.manager).action_open_reject_wizard()
        doc.with_user(self.manager).action_reject('blurry')
        self.assertEqual((doc.state, doc.reject_reason), ('rejected', 'blurry'))
        note = doc.message_ids.filtered(lambda m: 'blurry' in (m.body or ''))
        self.assertEqual(note.subtype_id, self.env.ref('mail.mt_note'))
        self.assertFalse(doc.with_user(self.manager).can_reject)
        with self.assertRaises(UserError):
            doc.with_user(self.manager).action_reject('again')
        # an Approved document can be rejected afterwards, with its own reason
        doc.with_user(self.manager).action_approve()
        self.assertTrue(doc.with_user(self.manager).can_reject)
        doc.with_user(self.manager).action_reject('expired passport')
        self.assertEqual((doc.state, doc.reject_reason), ('rejected', 'expired passport'))
        self.assertTrue(doc.message_ids.filtered(lambda m: 'expired passport' in (m.body or '')))
        # a Draft cannot be rejected
        draft = self._doc(self.alice, self.alice_emp, self.cat_id, submit=False)
        with self.assertRaises(UserError):
            draft.with_user(self.manager).action_reject('no')
        # the employee can't touch a rejected document, and nothing moves its stage but the buttons
        with self.assertRaises(AccessError):
            self._add(self.alice, doc, 'better.pdf')
        doc.with_user(self.manager).write({'notes': 'HR note'})
        self.assertEqual(doc.state, 'rejected')

    # ---------------------------------------------------------------- 5. security
    def test_no_share_links(self):
        doc = self._doc(self.alice, self.alice_emp, self.cat_id)
        att = doc.attachment_ids
        self.assertTrue(att)
        with self.assertRaises(AccessError):
            att.generate_access_token()
        with self.assertRaises(AccessError):
            att.with_user(self.alice).write({'public': True})
        # uploading to someone else's document is refused
        with self.assertRaises(AccessError):
            self.env['ir.attachment'].with_user(self.bob).create({
                'name': 'x', 'raw': b'x', 'res_model': 'hr.dms.document', 'res_id': doc.id})
        with self.assertRaises(AccessError):
            self.env['ir.attachment'].create({
                'name': 'x', 'raw': b'x', 'res_model': 'hr.dms.document', 'res_id': doc.id,
                'access_token': 'abc'})

    def test_other_employee_cannot_fetch_attachment(self):
        doc = self._doc(self.alice, self.alice_emp, self.cat_id)
        att = doc.attachment_ids
        att.with_user(self.alice).check('read')
        with self.assertRaises(AccessError):
            att.with_user(self.bob).check('read')
        self.assertFalse(self.env['ir.attachment'].with_user(self.bob).search([('id', '=', att.id)]))

    def test_file_validation(self):
        with self.assertRaises(ValidationError):
            self._doc(self.alice, self.alice_emp, self.cat_id, filename='evil.exe')
        self.env['ir.config_parameter'].sudo().set_param('hr_dms.max_file_mb', '0')
        with self.assertRaises(ValidationError):
            self._doc(self.alice, self.alice_emp, self.cat_id)

    def test_audit_trail(self):
        Log = self.env['hr.dms.audit.log']
        doc = self._doc(self.alice, self.alice_emp, self.cat_id, submit=False)
        self.assertTrue(Log.search([('document_id', '=', doc.id), ('action', '=', 'upload')]))
        doc.with_user(self.alice).write({'notes': 'n'})
        self.assertTrue(Log.search([('document_id', '=', doc.id), ('action', '=', 'modify')]))
        doc.with_user(self.officer).write({'active': False})
        self.assertTrue(Log.search([('document_id', '=', doc.id), ('action', '=', 'archive')]))
        # permission changes
        n = Log.search_count([('action', '=', 'access_change')])
        self.cat_id.with_user(self.admin).write({'employee_can_download': False})
        self.assertEqual(Log.search_count([('action', '=', 'access_change')]), n + 1)
        grp = self.env.ref('hr_dms.group_hr_dms_confidential')
        self.alice.sudo().write({'groups_id': [(4, grp.id)]})
        self.assertEqual(Log.search_count([('action', '=', 'access_change')]), n + 2)
        # immutable, and unreadable below manager
        entry = Log.search([], limit=1)
        with self.assertRaises(UserError):
            entry.sudo().unlink()
        with self.assertRaises(UserError):
            entry.sudo().write({'details': 'x'})
        with self.assertRaises(AccessError):
            Log.with_user(self.bob).search([])

    def test_audit_confidential_entries_hr_only(self):
        sal = self._doc(self.conf, self.alice_emp, self.cat_salary)
        Log = self.env['hr.dms.audit.log']
        self.assertTrue(Log.with_user(self.conf).search([('document_id', '=', sal.id)]))
        # every audit reader is an HR Manager, and HR Manager implies confidential access
        self.assertTrue(Log.with_user(self.manager).search([('document_id', '=', sal.id)]))
        with self.assertRaises(AccessError):
            Log.with_user(self.alice).search([('document_id', '=', sal.id)])

    # ----------------------------------------------------------- 6. personal details
    def test_personal_details_flow(self):
        Details = self.env['hr.dms.personal.details']
        action = Details.with_user(self.alice).action_open_my_details()
        form = Details.browse(action['res_id'])
        self.assertEqual(form.employee_id, self.alice_emp)
        form.with_user(self.alice).write({'birthday': '1990-05-05', 'personal_mobile': '+91 99999'})
        # Bob can't see it, HR can
        self.assertFalse(Details.with_user(self.bob).search([('id', '=', form.id)]))
        self.assertTrue(Details.with_user(self.officer).search([('id', '=', form.id)]))
        with self.assertRaises(AccessError):
            form.with_user(self.alice).write({'state': 'verified'})
        with self.assertRaises(AccessError):
            form.with_user(self.bob).action_submit()
        form.with_user(self.alice).action_submit()
        self.assertEqual(form.state, 'submitted')
        with self.assertRaises(AccessError):      # locked after submission
            form.with_user(self.alice).write({'personal_mobile': 'x'})
        with self.assertRaises(AccessError):
            form.with_user(self.alice).action_verify()
        self.alice_emp.sudo().work_email = 'alice.work@example.com'
        Mail = self.env['mail.mail'].sudo()
        before = Mail.search([]).ids
        self.assertEqual(form.with_user(self.officer).action_open_return_wizard()['context']['default_mode'], 'return')
        wizard = self.env['hr.dms.return.wizard'].with_user(self.officer).create(
            {'details_id': form.id, 'mode': 'return', 'reason': 'fix mobile'})
        wizard.action_confirm()
        # back in Draft (there is no "returned" stage), reason logged and mailed to the employee
        self.assertEqual((form.state, form.return_reason), ('draft', 'fix mobile'))
        self.assertIn('fix mobile', form.message_ids[0].body)
        mails = Mail.search([('id', 'not in', before)])
        self.assertEqual((len(mails), mails.email_to), (1, 'alice.work@example.com'))
        self.assertIn('fix mobile', mails.body_html)
        self.assertIn('/logo.png?company=', mails.body_html)
        form.with_user(self.alice).write({'personal_mobile': '+91 88888'})
        form.with_user(self.alice).action_submit()
        self.assertFalse(form.return_reason)
        form.with_user(self.officer).action_verify()
        with self.assertRaises(UserError):
            Details.with_user(self.officer).browse(form.id).action_submit()
        # verified = read-only for everyone, HR included; only Update Employee Profile acts on it
        self.assertFalse(form.with_user(self.officer).can_edit_details)
        with self.assertRaises(UserError):
            form.with_user(self.officer).write({'personal_mobile': 'x'})
        with self.assertRaises(UserError):
            form.with_user(self.officer).action_return('x')      # Return is for submitted forms
        form.with_user(self.officer).action_apply_to_profile()
        self.assertEqual(str(self.alice_emp.sudo().birthday), '1990-05-05')
        self.assertEqual(self.alice_emp.sudo().private_phone, '+91 88888')
        self.assertTrue(self.env['hr.dms.audit.log'].search([('action', '=', 'details'),
                                                              ('employee_id', '=', self.alice_emp.id)]))
        # Reopen asks a reason, logs it and mails the employee
        before = Mail.search([]).ids
        self.env['hr.dms.return.wizard'].with_user(self.officer).create(
            {'details_id': form.id, 'mode': 'reopen', 'reason': 'passport renewed'}).action_confirm()
        self.assertEqual((form.state, form.return_reason), ('draft', 'passport renewed'))
        self.assertIn('passport renewed', form.message_ids[0].body)
        self.assertIn('passport renewed', Mail.search([('id', 'not in', before)]).body_html)
        form.with_user(self.alice).write({'personal_mobile': '+91 77777'})

    def test_personal_details_new_form(self):
        Details = self.env['hr.dms.personal.details'].with_user(self.alice)
        first = Details.browse(Details.action_open_my_details()['res_id'])
        first.write({'emirates_id_no': '784-1', 'personal_mobile': '+91 11111'})
        # a new form can be started whatever state the earlier ones are in
        Details.create({'full_name': 'x'}).sudo().unlink()
        first.action_submit()
        Details.create({'full_name': 'x'}).sudo().unlink()
        first.with_user(self.officer).action_verify()
        # New starts empty, stays empty where nothing was typed, and is editable by the employee
        defaults = Details.default_get(['employee_id', 'emirates_id_no', 'personal_mobile', 'state'])
        self.assertFalse(defaults.get('emirates_id_no') or defaults.get('personal_mobile'))
        self.assertEqual(defaults['state'], 'draft')
        second = Details.create(dict(defaults, personal_mobile='+91 22222'))
        self.assertTrue(second.can_edit_details)
        self.assertEqual(second.personal_mobile, '+91 22222')
        Details.action_open_my_details()        # reopening doesn't fill it from the employee form
        self.assertFalse(second.emirates_id_no or second.current_country_id)
        self.assertEqual(second.full_name, self.alice_emp.sudo().name)   # read-only, from the employee
        self.assertEqual(self.alice_emp.sudo().private_phone, '+91 22222')
        self.assertEqual(Details.action_open_my_details()['res_id'], second.id)
        self.assertEqual(self.alice_emp.with_user(self.officer).dms_details_state, 'draft')

    def test_update_profile_opens_verified_form_once(self):
        Details = self.env['hr.dms.personal.details']
        form = Details.browse(Details.with_user(self.alice).action_open_my_details()['res_id'])
        form.with_user(self.alice).action_submit()
        form.with_user(self.officer).action_verify()
        self.assertFalse(form.with_user(self.officer).can_edit_details)
        form.with_user(self.officer).action_apply_to_profile()
        self.assertTrue(form.with_user(self.officer).can_edit_details)
        self.assertFalse(form.with_user(self.alice).can_edit_details)      # HR only
        with self.assertRaises(UserError):
            form.with_user(self.alice).write({'personal_mobile': '+91 1'})
        form.with_user(self.officer).write({'personal_mobile': '+91 33333'})
        self.assertEqual(self.alice_emp.sudo().private_phone, '+91 33333')  # reached the profile
        self.assertFalse(form.profile_edit_open)                              # locked again
        with self.assertRaises(UserError):
            form.with_user(self.officer).write({'personal_mobile': '+91 44444'})
        form.with_user(self.officer).action_apply_to_profile()
        form.with_user(self.officer).action_lock_form()
        self.assertFalse(form.with_user(self.officer).can_edit_details)

    # ------------------------------------------- 7. live refresh, reporting, dashboard, menus
    def test_live_refresh_notifies_owner_and_hr(self):
        doc = self._doc(self.alice, self.alice_emp, self.cat_id, submit=False)
        self.env.cr.precommit.run()             # what commit does: queues the bus messages
        last = self.env['bus.bus'].sudo().search([], order='id desc', limit=1).id
        doc.with_user(self.officer).write({'notes': 'checked'})
        live = self.env.cr.precommit.data['hr_dms.live']
        self.assertIn(doc.id, live['models']['hr.dms.document'])
        self.assertTrue({self.alice.id, self.officer.id} <= live['users'])   # owner + writer; HR added on send
        self.env.cr.precommit.run()
        rows = self.env['bus.bus'].sudo().search([('id', '>', last), ('message', 'like', 'hr_dms/changed')])
        channels = ' '.join(rows.mapped('channel'))
        for user in (self.alice, self.officer, self.manager):
            self.assertIn(f'"res.partner",{user.partner_id.id}]', channels)
        self.assertNotIn(f'"res.partner",{self.bob.partner_id.id}]', channels)   # not his record

    def test_excel_export_admin_only(self):
        import io
        import openpyxl
        doc = self._doc(self.alice, self.alice_emp, self.cat_id, filename='passport.pdf')
        details = self.env['hr.dms.personal.details'].with_user(self.alice).browse(
            self.env['hr.dms.personal.details'].with_user(self.alice).action_open_my_details()['res_id'])
        details.write({'passport_no': 'P123'})
        for user in (self.alice, self.officer, self.manager):
            with self.assertRaises(AccessError, msg=user.login):
                doc.with_user(user).action_export_xlsx()
        action = doc.with_user(self.admin).action_export_xlsx()
        self.assertEqual(action['url'], f'/hr_dms/export/hr.dms.document?ids={doc.id}')
        Export = self.env['hr.dms.excel.export'].with_user(self.admin)

        def sheet(records):
            rows = list(openpyxl.load_workbook(io.BytesIO(Export._build_xlsx(records))).active.values)
            return dict(zip(rows[0], rows[1]))
        row = sheet(doc.with_user(self.admin))
        self.assertEqual(row['Employee'], self.alice_emp.name)
        self.assertEqual(row['Files'], 'passport.pdf')            # the file name, not its content
        self.assertEqual(row['Status'], 'Submitted')       # _doc submits it
        row = sheet(details.with_user(self.admin))
        self.assertEqual(row['Passport No'], 'P123')
        self.assertIn('Work Permit (file name)', row)

    def test_dashboard_scopes_hr_and_employee(self):
        mine = self._doc(self.alice, self.alice_emp, self.cat_id)
        self._doc(self.bob, self.bob_emp, self.cat_id)
        Dash = self.env['hr.dms.dashboard']
        own = Dash.with_user(self.alice).get_dashboard_data()
        self.assertFalse(own['is_hr'])
        self.assertEqual([r['id'] for r in own['employees']], [self.alice_emp.id])   # only herself
        self.assertEqual(own['doc_total'], 1)
        self.assertEqual(own['employees'][0]['cells'][self.cat_id.id]['state'], mine.state)
        self.assertNotIn(self.cat_salary.id, [c['id'] for c in own['categories']])  # hidden category
        hr = Dash.with_user(self.manager).get_dashboard_data()
        self.assertTrue(hr['is_hr'])
        self.assertFalse(hr['is_admin'])
        ids = {r['id'] for r in hr['employees']}
        self.assertTrue({self.alice_emp.id, self.bob_emp.id} <= ids)
        bob = next(r for r in hr['employees'] if r['id'] == self.bob_emp.id)
        self.assertEqual(bob['details_state'], 'not_started')
        self.assertTrue(Dash.with_user(self.admin).get_dashboard_data()['is_admin'])

    def test_menus_by_role(self):
        Menu = self.env['ir.ui.menu']
        config = self.env.ref('hr_dms.menu_hr_dms_config')
        cats = self.env.ref('hr_dms.menu_hr_dms_categories')
        export = self.env.ref('hr_dms.menu_hr_dms_export')
        root = self.env.ref('hr_dms.menu_hr_dms_root')
        self.assertEqual(export.parent_id, root)                                      # its own top menu
        self.assertEqual((export.name, root.action), ('Reporting', self.env.ref('hr_dms.action_hr_dms_dashboard')))
        self.assertEqual(Menu.search([('parent_id', '=', config.id)]), cats)          # only categories left
        for user, seen in ((self.alice, set()), (self.manager, {config, cats}),
                           (self.admin, {config, cats, export})):
            visible = Menu.with_user(user).search([('id', 'in', (config + cats + export).ids)])
            self.assertEqual(set(visible), seen, user.login)

    def test_hr_assigns_details_form_to_employee_user(self):
        Details = self.env['hr.dms.personal.details'].with_user(self.officer)
        form = Details.with_context(default_employee_id=False).create({'employee_id': self.alice_emp.id})
        self.assertEqual(form.user_id, self.alice)
        self.assertEqual(form.full_name, self.alice_emp.name)
        no_login = self.env['hr.employee'].create({'name': 'No Login'})
        with self.assertRaises(UserError):
            Details.create({'employee_id': no_login.id})
        with self.assertRaises(UserError):
            Details.with_context(default_employee_id=False).create({})

    def test_download_button(self):
        doc = self._doc(self.alice, self.alice_emp, self.cat_id)
        att = doc.attachment_ids
        # one file downloads as it is ...
        action = doc.with_user(self.alice).action_download_files()
        self.assertEqual(action['url'], f'/web/content/{att.id}?download=true')
        # ... several come as one zip
        self._add(self.officer, doc, 'second.pdf')
        self.assertEqual(doc.with_user(self.alice).action_download_files()['url'],
                         f'/hr_dms/document/{doc.id}/download')
        self.assertTrue(doc.with_user(self.alice).can_download)

    def test_archived_category_hides_documents_for_everyone(self):
        doc = self._doc(self.alice, self.alice_emp, self.cat_id)
        hr_archived = self._doc(self.alice, self.alice_emp, self.cat_id)
        hr_archived.sudo().active = False      # archived by HR on its own, before the category
        self.cat_id.with_user(self.admin).action_archive()
        Doc = self.env['hr.dms.document']
        for user in (self.alice, self.officer, self.manager):
            self.assertFalse(Doc.with_user(user).search([('id', 'in', (doc + hr_archived).ids)]), user.login)
        self.cat_id.with_user(self.admin).action_unarchive()
        self.assertTrue(doc.active)
        self.assertFalse(hr_archived.active)    # stays archived: it wasn't hidden by the category
        self.assertTrue(Doc.with_user(self.alice).search([('id', '=', doc.id)]))

    def test_employee_profile_counters(self):
        self._doc(self.alice, self.alice_emp, self.cat_id)
        emp = self.alice_emp.with_user(self.officer)
        self.assertEqual(emp.dms_document_count, 1)
        self.assertEqual(emp.action_open_dms_documents()['res_model'], 'hr.dms.document')
        self.assertEqual(emp.action_open_dms_details()['res_model'], 'hr.dms.personal.details')

    # --------------------------------------------------------- 8. added in 18.0.1.33.1
    def test_category_upload_needs_view(self):
        Cat = self.env['hr.dms.category'].with_user(self.admin)
        cat = Cat.create({'name': 'Hidden upload', 'code': 'HUP', 'employee_can_view': False,
                          'employee_can_upload': True})
        self.assertFalse(cat.employee_can_upload)       # cleared: you can't upload what you can't see
        cat.write({'employee_can_view': True, 'employee_can_upload': True})
        cat.write({'employee_can_view': False})
        self.assertFalse(cat.employee_can_upload)
        with self.assertRaises(ValidationError):       # ticking upload alone, with view still off
            cat.write({'employee_can_upload': True})

    def test_reject_wizard(self):
        doc = self._doc(self.alice, self.alice_emp, self.cat_id)
        ctx = doc.with_user(self.manager).action_open_reject_wizard()['context']
        wiz = self.env['hr.dms.reject.wizard'].with_user(self.manager).with_context(ctx).create(
            {'reason': 'Expired'})
        wiz.action_confirm()
        self.assertEqual((doc.state, doc.reject_reason, doc.approved_by), ('rejected', 'Expired', self.manager))
        self.assertTrue(self.env['hr.dms.audit.log'].search([('document_id', '=', doc.id), ('action', '=', 'reject')]))
        with self.assertRaises(AccessError):
            doc.with_user(self.alice).action_open_reject_wizard()

    def test_fill_from_document(self):
        lines = ['EMPLOYEE PERSONAL DETAILS', 'PRIVATE CONTACT', 'Private Phone: +91 55555',
                 'City: Coimbatore', 'CITIZENSHIP', 'Passport No: Z1234567', 'Gender: Male',
                 'Date of Birth: 05/02/1990', 'FAMILY STATUS', 'Number of Dependent Children: 2']
        body = ''.join(f'<w:p><w:r><w:t>{line}</w:t></w:r></w:p>' for line in lines)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as docx:
            docx.writestr('word/document.xml',
                          '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                          f'<w:body>{body}</w:body></w:document>')
        Details = self.env['hr.dms.personal.details'].with_user(self.alice)
        form = Details.browse(Details.action_open_my_details()['res_id'])
        form.write({'current_city': 'Chennai', 'source_file': base64.b64encode(buffer.getvalue()),
                    'source_filename': 'details.docx'})
        result = form.action_fill_from_document()
        self.assertEqual(result['params']['type'], 'success')
        self.assertEqual((form.personal_mobile, form.passport_no, form.gender, str(form.birthday), form.children),
                         ('+91 55555', 'Z1234567', 'male', '1990-02-05', 2))
        self.assertEqual(form.current_city, 'Chennai')                  # typed values are never overwritten
        self.assertIn('City', result['params']['message'])
        form.write({'source_file': base64.b64encode(b'not a document'), 'source_filename': 'scan.png'})
        with self.assertRaises(UserError):                                # only PDF and Word can be read
            form.action_fill_from_document()
        form.action_submit()
        with self.assertRaises(UserError):                                # nor once submitted
            form.action_fill_from_document()


@tagged('post_install', '-at_install', 'hr_dms')
class TestHrDmsHttp(HttpCase):
    """The two download routes, through a real HTTP request and login."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)

        def mk(login, groups):
            user = Users.create({'name': login, 'login': login, 'password': login + '_pw1',
                                 'groups_id': [(6, 0, [cls.env.ref(g).id for g in ('base.group_user', *groups)])]})
            return user, cls.env['hr.employee'].create({'name': login, 'user_id': user.id})
        cls.emp_user, cls.emp = mk('hrdms_http_emp', ['hr_dms.group_hr_dms_employee'])
        cls.hr_user, _ = mk('hrdms_http_hr', ['hr_dms.group_hr_dms_manager'])
        cls.admin_user, _ = mk('hrdms_http_admin', ['hr_dms.group_hr_dms_admin'])
        cls.cat = cls.env.ref('hr_dms.cat_contract')
        cls.cat.sudo().write({'confidential': False, 'employee_can_view': True, 'employee_can_upload': False,
                              'employee_can_edit': False, 'employee_can_download': False})
        atts = cls.env['ir.attachment'].create([
            {'name': n, 'raw': b'%PDF-1.4 ' + n.encode(), 'res_model': 'hr.dms.document', 'res_id': 0}
            for n in ('contract.pdf', 'annex.pdf')])
        cls.doc = cls.env['hr.dms.document'].create({
            'name': 'Contract', 'employee_id': cls.emp.id, 'category_id': cls.cat.id,
            'attachment_ids': [(6, 0, atts.ids)]})

    def test_zip_download(self):
        url = f'/hr_dms/document/{self.doc.id}/download'
        self.authenticate('hrdms_http_emp', 'hrdms_http_emp_pw1')      # view only, no download
        self.assertEqual(self.url_open(url).status_code, 403)
        self.authenticate('hrdms_http_hr', 'hrdms_http_hr_pw1')
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers['Content-Type'], 'application/zip')
        names = zipfile.ZipFile(io.BytesIO(res.content)).namelist()
        self.assertEqual(sorted(names), ['annex.pdf', 'contract.pdf'])
        log = self.env['hr.dms.audit.log'].search([('document_id', '=', self.doc.id), ('action', '=', 'download')])
        self.assertEqual(len(log), 1)                                       # one entry for the whole zip
        self.assertEqual(log.user_id, self.hr_user)

    def test_excel_export_route(self):
        url = f'/hr_dms/export/hr.dms.document?ids={self.doc.id}'
        self.authenticate('hrdms_http_hr', 'hrdms_http_hr_pw1')          # HR Manager: not an administrator
        self.assertEqual(self.url_open(url).status_code, 403)
        self.authenticate('hrdms_http_admin', 'hrdms_http_admin_pw1')
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.content.startswith(b'PK'))                     # an .xlsx is a zip
        self.assertEqual(self.url_open('/hr_dms/export/res.partner?ids=1').status_code, 404)
        self.assertTrue(self.env['hr.dms.audit.log'].search([('action', '=', 'export'),
                                                             ('user_id', '=', self.admin_user.id)]))
