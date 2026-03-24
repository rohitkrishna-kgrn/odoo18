{
    'name': 'Attendance Extended RK',
    'version': '1.0',
    'summary': 'Check-in/out with location validation',
    'depends': ['hr_attendance', 'hr_timesheet'],
    'data': ["security/ir.model.access.csv", 'views/hr_attendance_views.xml', 'data/ir_cron_auto_checkout.xml', "views/forgot_logout_wizard_view.xml",],
    'installable': True,
    'application': False,
}
