import base64
from datetime import date, timedelta
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDuplicateProposal(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'CRM Validation Test Co', 'is_company': True})
        cls.contact = cls.env['res.partner'].create({
            'name': 'CRM Validation Test Contact', 'parent_id': cls.customer.id})
        cls.other_customer = cls.env['res.partner'].create({
            'name': 'CRM Validation Other Co', 'is_company': True})
        cls.service = cls.env['product.product'].create({
            'name': 'CRM Validation Service A', 'type': 'service', 'list_price': 100})
        cls.other_service = cls.env['product.product'].create({
            'name': 'CRM Validation Service B', 'type': 'service', 'list_price': 100})
        # crm_extended_rk: an order line needs a "Dedicated Project Manager".
        cls.line_pm = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'CRM Validation Test PM', 'login': 'crm_validation_gk_pm',
            'email': 'pm@crm-validation-gk.test', 'is_dedicated_manager': True,
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])]})
        cls.salesperson_a = cls._salesperson('a')
        cls.salesperson_b = cls._salesperson('b')
        cls.start = date(2031, 1, 1)
        cls.end = date(2031, 12, 31)
        cls.existing = cls._order(cls.customer, cls.service, cls.start, cls.end,
                                  salesperson=cls.salesperson_a)

    @classmethod
    def _salesperson(cls, key):
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': f'CRM Validation Salesperson {key}',
            'login': f'crm_validation_gk_sales_{key}',
            'email': f'{key}@crm-validation-gk.test',
            'groups_id': [(6, 0, [cls.env.ref('sales_team.group_sale_salesman').id])]})

    @classmethod
    def _order(cls, partner, product, start, end, salesperson=None):
        """A quotation; by default raised by salesperson B, a colleague of
        the existing proposal's salesperson A."""
        order = cls.env['sale.order'].with_context(skip_sales_team_check=True).create({
            'partner_id': partner.id,
            'user_id': (salesperson or cls.salesperson_b).id,
            'einvoicing_service': True,
            'crm_link_override': True,
            'crm_link_override_reason': 'crm_validation_gk test',
        })
        cls.env['sale.order.line'].create({
            'order_id': order.id, 'product_id': product.id, 'product_uom_qty': 1,
            'price_unit': 100, 'manager_id': cls.line_pm.id, 'estimated_hours': 1,
            'engagement_start': start, 'engagement_end': end, 'deadline': end,
        })
        return order

    def _confirm(self, order):
        # Straight to SQL: confirming through write() trips the AML/KYC gate.
        self.env.cr.execute(
            "UPDATE sale_order SET state = 'sale' WHERE id = %s", [order.id])
        order.invalidate_recordset(['state'])

    def _set_approval(self, order, approval_state):
        # SQL as well: Approve renames the order and books follow-up steps.
        self.env.cr.execute(
            "UPDATE sale_order SET approval_state = %s WHERE id = %s",
            [approval_state, order.id])
        order.invalidate_recordset(['approval_state'])

    def _download(self, order):
        """Run Download Proposal with the PDF API stubbed out."""
        SaleOrder = type(self.env['sale.order'])
        pdf = base64.b64encode(b'%PDF-1.4 test')
        with patch.object(SaleOrder, '_pdf_api_proposal_payload', return_value={}), \
                patch.object(SaleOrder, '_pdf_api_render', return_value=pdf) as render:
            result = order.action_download_proposal()
        return result, render

    def test_same_customer_service_period_is_blocked(self):
        order = self._order(self.customer, self.service, self.start, self.end)
        with self.assertRaisesRegex(UserError, 'Duplicate proposal') as caught:
            self._download(order)
        self.assertIn(self.existing.name, str(caught.exception))
        self.assertFalse(order.proposal_generated_on)

    def test_api_is_not_called_for_a_duplicate(self):
        order = self._order(self.customer, self.service, self.start, self.end)
        SaleOrder = type(self.env['sale.order'])
        with patch.object(SaleOrder, '_pdf_api_render') as render, \
                self.assertRaises(UserError):
            order.action_download_proposal()
        render.assert_not_called()

    def test_overlapping_period_is_blocked(self):
        order = self._order(self.customer, self.service,
                            date(2031, 12, 31), date(2032, 6, 30))
        with self.assertRaisesRegex(UserError, 'Duplicate proposal'):
            self._download(order)

    def test_contact_of_same_company_is_blocked(self):
        order = self._order(self.contact, self.service, self.start, self.end)
        with self.assertRaisesRegex(UserError, 'Duplicate proposal'):
            self._download(order)

    def test_different_customer_is_allowed(self):
        order = self._order(self.other_customer, self.service, self.start, self.end)
        result, render = self._download(order)
        render.assert_called_once()
        self.assertEqual(result['type'], 'ir.actions.act_url')
        self.assertTrue(order.proposal_generated_on)

    def test_different_service_is_allowed(self):
        order = self._order(self.customer, self.other_service, self.start, self.end)
        result, render = self._download(order)
        render.assert_called_once()

    def test_next_period_after_a_confirmed_order_is_allowed(self):
        self._confirm(self.existing)
        order = self._order(self.customer, self.service,
                            date(2032, 1, 1), date(2032, 12, 31))
        result, render = self._download(order)
        render.assert_called_once()

    def test_cancelled_proposal_does_not_block(self):
        self.existing._action_cancel()
        order = self._order(self.customer, self.service, self.start, self.end)
        result, render = self._download(order)
        render.assert_called_once()

    def test_confirmed_order_does_not_block(self):
        self._confirm(self.existing)
        order = self._order(self.customer, self.service, self.start, self.end)
        result, render = self._download(order)
        render.assert_called_once()

    def test_approved_quotation_does_not_block(self):
        self._set_approval(self.existing, 'approved')
        order = self._create(self._create_vals(self.customer, [
            self._line_cmd(self.service, self.start, self.end)]))
        self.assertFalse(order._find_duplicate_proposal_lines())
        self._submit(order)
        self.assertEqual(order.approval_state, 'to_approve')

    def test_quotation_awaiting_approval_blocks(self):
        self._set_approval(self.existing, 'to_approve')
        with self.assertRaisesRegex(UserError, 'cannot be created'), \
                self.env.cr.savepoint():
            self._create(self._create_vals(self.customer, [
                self._line_cmd(self.service, self.start, self.end)]))

    def test_regenerating_the_same_proposal_is_allowed(self):
        result, render = self._download(self.existing)
        render.assert_called_once()

    def test_same_salesperson_is_blocked(self):
        order = self._order(self.customer, self.service, self.start, self.end,
                            salesperson=self.salesperson_a)
        with self.assertRaisesRegex(UserError, 'Duplicate proposal'):
            self._download(order)

    def test_first_proposal_is_not_blocked_by_a_later_copy(self):
        self._order(self.customer, self.service, self.start, self.end)
        result, render = self._download(self.existing)
        render.assert_called_once()

    def test_existing_without_salesperson_blocks(self):
        self.existing.user_id = False
        order = self._order(self.customer, self.service, self.start, self.end)
        with self.assertRaisesRegex(UserError, 'Duplicate proposal'):
            self._download(order)

    # ── Submit for Approval ───────────────────────────────────────────────
    def _submit(self, order):
        self.env.company.approver_user_id = self.salesperson_a
        return order.action_submit_for_approval()

    def test_submit_duplicate_is_blocked(self):
        order = self._order(self.customer, self.service,
                            date(2031, 3, 1), date(2031, 3, 31),
                            salesperson=self.salesperson_a)
        with self.assertRaisesRegex(UserError, 'cannot be submitted for approval'):
            self._submit(order)
        self.assertEqual(order.approval_state, 'draft')

    def test_submit_allowed_once_first_is_cancelled(self):
        order = self._order(self.customer, self.service, self.start, self.end)
        self.existing._action_cancel()
        self._submit(order)
        self.assertEqual(order.approval_state, 'to_approve')

    def test_submit_without_duplicate_is_allowed(self):
        order = self._order(self.customer, self.other_service, self.start, self.end)
        self._submit(order)
        self.assertEqual(order.approval_state, 'to_approve')

    def test_submit_first_proposal_is_allowed(self):
        self._order(self.customer, self.service, self.start, self.end)
        self._submit(self.existing)
        self.assertEqual(self.existing.approval_state, 'to_approve')

    # ── Create / save ─────────────────────────────────────────────────────
    def _line_cmd(self, product, start, end):
        return (0, 0, {
            'product_id': product.id, 'product_uom_qty': 1, 'price_unit': 100,
            'manager_id': self.line_pm.id, 'estimated_hours': 1,
            'engagement_start': start, 'engagement_end': end, 'deadline': end,
        })

    def _create_vals(self, partner, lines, **extra):
        return dict({
            'partner_id': partner.id,
            'user_id': self.salesperson_b.id,
            'crm_link_override': True,
            'crm_link_override_reason': 'crm_validation_gk test',
            'order_line': lines,
        }, **extra)

    def _create(self, vals):
        return self.env['sale.order'].with_context(skip_sales_team_check=True).create(vals)

    def test_create_duplicate_is_blocked(self):
        SaleOrder = self.env['sale.order']
        count = SaleOrder.search_count([('partner_id', '=', self.customer.id)])
        with self.assertRaisesRegex(UserError, 'cannot be created'), \
                self.env.cr.savepoint():
            self._create(self._create_vals(self.customer, [
                self._line_cmd(self.service, date(2031, 6, 1), date(2031, 6, 30))]))
        self.assertEqual(
            SaleOrder.search_count([('partner_id', '=', self.customer.id)]), count)

    def test_create_without_duplicate_is_allowed(self):
        self._confirm(self.existing)
        order = self._create(self._create_vals(self.customer, [
            self._line_cmd(self.service, date(2032, 1, 1), date(2032, 12, 31)),
            self._line_cmd(self.other_service, self.start, self.end)]))
        self.assertEqual(len(order.order_line), 2)

    def test_duplicate_button_is_blocked(self):
        with self.assertRaisesRegex(UserError, 'cannot be created'):
            # The pipeline link is not copied (copy=False), so give the copy one.
            self.existing.with_context(skip_sales_team_check=True).copy({
                'crm_link_override': True,
                'crm_link_override_reason': 'crm_validation_gk test'})

    def test_renewal_is_not_blocked(self):
        order = self._create(self._create_vals(
            self.customer, [self._line_cmd(self.service, self.start, self.end)],
            new_renewed='renewed'))
        self.env.company.approver_user_id = self.salesperson_a
        order.action_submit_for_approval()
        self.assertEqual(order.approval_state, 'to_approve')

    def test_adding_a_duplicate_line_later_is_blocked(self):
        order = self._create(self._create_vals(self.customer, []))
        with self.assertRaisesRegex(UserError, 'This change cannot be saved'):
            order.write({'order_line': [
                self._line_cmd(self.service, self.start, self.end)]})

    def test_switching_to_a_duplicate_customer_is_blocked(self):
        order = self._create(self._create_vals(self.other_customer, [
            self._line_cmd(self.service, self.start, self.end)]))
        with self.assertRaisesRegex(UserError, 'This change cannot be saved'):
            order.write({'partner_id': self.customer.id})

    def test_existing_duplicate_stays_editable(self):
        # Built line by line, like quotations raised before this module.
        order = self._order(self.customer, self.service, self.start, self.end)
        line = order.order_line
        order.write({'order_line': [(1, line.id, {'price_unit': 250})]})
        self.assertEqual(line.price_unit, 250)
        order.write({'order_line': [
            self._line_cmd(self.other_service, self.start, self.end)]})
        self.assertEqual(len(order.order_line), 2)

    # ── Open quotations block whatever the dates ──────────────────────────
    def test_open_quotation_blocks_a_different_period(self):
        # Quotation A is still open; B for the same customer and service is
        # raised later for another period - B is refused.
        with self.assertRaisesRegex(UserError, 'cannot be created'), \
                self.env.cr.savepoint():
            self._create(self._create_vals(self.customer, [
                self._line_cmd(self.service, date(2033, 1, 1), date(2033, 12, 31))]))

    def test_open_quotation_whose_period_ended_does_not_block(self):
        old = self._order(self.other_customer, self.service,
                          date(2020, 1, 1), date(2020, 12, 31))
        order = self._create(self._create_vals(self.other_customer, [
            self._line_cmd(self.service, date(2031, 1, 1), date(2031, 12, 31))]))
        self.assertFalse(order._find_duplicate_proposal_lines())
        self.assertEqual(old.state, 'draft')

    def test_popup_has_no_cancel_advice(self):
        order = self._order(self.customer, self.service, self.start, self.end)
        with self.assertRaises(UserError) as caught:
            self._download(order)
        self.assertNotIn('Cancel the existing proposal', str(caught.exception))
