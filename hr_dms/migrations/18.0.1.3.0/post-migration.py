LABELS = {'single': 'Single', 'married': 'Married', 'cohabitant': 'Legal Cohabitant',
          'widower': 'Widower', 'divorced': 'Divorced'}


def migrate(cr, version):
    # marital became free text: turn the stored selection keys into readable labels
    for key, label in LABELS.items():
        cr.execute("UPDATE hr_dms_personal_details SET marital = %s WHERE marital = %s", (label, key))
