{
    'name': 'Country Payroll (Payroll Extension)',
    'version': '18.0.1.34.0',
    'category': 'Generic Modules/Human Resources',
    'summary': 'Country-wise payroll batches, quotation-approver approval, '
               'payslip distribution and employee self-service payslips inside Payroll',
    'description': """
Country-wise payroll inside the existing Payroll application.

* Dubai Payroll / India Payroll menus generated from Payroll Countries
  (linked to the Leave Management "Country For Leave Model" locations).
* Payroll Officer role restricted to the countries assigned on the user.
* Fetch employees by contract company, attendance + approved leave, and
  calculate through the existing Payroll salary rules (Compute Sheet).
* Editable draft figures with an audit trail, PDF / Excel register.
* Submit to the company's Quotation Approver, approve / reject, notify the
  country's Payroll Officers.
* Send approved payslips (selected or explicit Send All) with delivery
  tracking and an Unsent Payslips list.
* My Payslips: every employee downloads their own approved payslips.
""",
    'author': 'KGRN',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'hr_attendance',
        'om_hr_payroll',
        'leave_management_rk',
        'employee_extended_rk',
        'sale_order_approval',
    ],
    'external_dependencies': {'python': ['xlsxwriter']},
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'data/res_bank_data.xml',
        'data/salary_rule_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron.xml',
        'report/report_actions.xml',
        'report/report_templates.xml',
        'wizard/reject_wizard_views.xml',
        'wizard/report_wizard_views.xml',
        'wizard/send_wizard_views.xml',
        'views/payroll_country_views.xml',
        'views/payroll_line_views.xml',
        'views/payroll_line_actions.xml',
        'views/payroll_batch_views.xml',
        'views/my_payslip_views.xml',
        'views/hr_employee_views.xml',
        'views/res_users_views.xml',
        'views/payroll_core_payslip_views.xml',
        'views/menus.xml',
        'data/payroll_country_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'om_hr_payroll_extended_gk/static/src/payroll_chatter.scss',
        ],
    },
    'installable': True,
    'application': False,
}
