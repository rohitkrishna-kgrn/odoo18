{
    'name': 'Employee Extended RK',
    'version': '1.0',
    'summary': 'Adds Weightage configuration and field to employee profiles',
    'author': 'KGRN Developer',
    'category': 'Human Resources',
    'depends': ['hr'],
    'data': [
        'security/ir.model.access.csv',
        'views/weightage_view.xml',
        'views/employee_inherit_view.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
