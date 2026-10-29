from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSimilarCustomer(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env['res.partner']
        cls.existing = cls.Partner.create({'name': 'ZQX VALIDATION ROCK L L C'})

    def _ui_create(self, vals):
        """Save a new contact the way the form view does."""
        return self.Partner.web_save(vals, {'name': {}})

    def test_same_name_other_case_is_blocked(self):
        with self.assertRaisesRegex(UserError, 'Customer already exists'):
            self._ui_create({'name': 'Zqx Validation Rock'})

    def test_punctuation_and_legal_form_are_ignored(self):
        with self.assertRaisesRegex(UserError, 'ZQX VALIDATION ROCK L L C'):
            self._ui_create({'name': 'zqx-validation  rock, L.L.C.', 'is_company': True})

    def test_quick_create_is_blocked(self):
        with self.assertRaisesRegex(UserError, 'Customer already exists'):
            self.Partner.name_create('ZQX Validation Rock')

    def test_different_name_is_allowed(self):
        self._ui_create({'name': 'ZQX Validation Rock Group'})

    def test_contact_person_under_a_company_is_allowed(self):
        company = self.Partner.create({'name': 'ZQX Other Holding', 'is_company': True})
        self._ui_create({'name': 'Zqx Validation Rock', 'parent_id': company.id})

    def test_server_flows_are_not_blocked(self):
        # Website leads, referrals and imports call create() directly.
        self.Partner.create({'name': 'Zqx Validation Rock'})

    def test_archived_customer_does_not_block(self):
        self.existing.active = False
        self._ui_create({'name': 'Zqx Validation Rock'})

    def test_rename_to_a_similar_name_is_blocked(self):
        other = self.Partner.create({'name': 'ZQX Something Else'})
        with self.assertRaisesRegex(UserError, 'cannot be used'):
            other.web_save({'name': 'Zqx Validation Rock'}, {'name': {}})

    def test_fixing_the_case_of_an_existing_duplicate_is_allowed(self):
        twin = self.Partner.create({'name': 'ZQX VALIDATION ROCK'})
        twin.web_save({'name': 'Zqx Validation Rock'}, {'name': {}})
        self.assertEqual(twin.name, 'Zqx Validation Rock')

    def test_lead_conversion_new_customer_is_blocked(self):
        lead = self.env['crm.lead'].create({
            'name': 'ZQX lead', 'partner_name': 'Zqx Validation Rock', 'type': 'lead'})
        with self.assertRaisesRegex(UserError, 'Customer already exists'):
            lead._create_customer()
