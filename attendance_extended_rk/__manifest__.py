{
    'name': 'Attendance Extended RK',
    'version': '1.0',
    'summary': 'Check-in/out with location validation',
    'depends': ['hr_attendance', 'hr_timesheet'],
    'data': ["security/ir.model.access.csv", 'views/hr_attendance_views.xml', 'data/ir_cron_auto_checkout.xml', "views/forgot_logout_wizard_view.xml",],
    'assets': {
        'web.assets_backend': [
            'attendance_extended_rk/static/src/js/check_in_out_confirm.js',
            'attendance_extended_rk/static/src/js/attendance_menu_confirm.js',
        ],
    },
    'installable': True,
    'application': False,
}
