from odoo import fields
from odoo.tools import format_datetime


def queue_correction_mail(record, employee, *, title, intro, rows, reason, url, button, action_text):
    """Queue the 'correction needed' mail to the employee alone (Settings > Technical > Emails).
    Returns the mail.mail, or an empty recordset when the employee has no email address."""
    env = record.env
    emp = employee.sudo()
    email = emp.work_email or emp.user_id.email
    if not email:
        return env['mail.mail']
    company = emp.company_id or env.company
    base_url = record.get_base_url()
    now = format_datetime(env, fields.Datetime.now(), tz=env.user.tz or 'UTC', dt_format='medium')
    body = env['ir.qweb']._render('hr_dms.mail_correction', {
        'title': title,
        'subtitle': env._("Employee Documents · %s", now),
        'logo_url': f"{base_url}/logo.png?company={company.id}",
        'employee_name': emp.name,
        'intro': intro,
        'rows': rows + [(env._("Requested by"), env.user.name), (env._("Date"), now)],
        'reason_lines': (reason or '-').splitlines() or ['-'],
        'action_text': action_text,
        'url': base_url + url,
        'button': button,
        'sender_name': env.user.name,
        'company_name': company.name,
    })
    return env['mail.mail'].sudo().create({
        'subject': title,
        'email_from': env.user.email_formatted or company.email_formatted,
        'email_to': email,
        'body_html': body,
        'auto_delete': False,
    })
