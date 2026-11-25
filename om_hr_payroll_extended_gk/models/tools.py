"""Pure helpers (no env): month / year lists, masking, bank number clean-up.
Do not call _() here - there is no env to pick a language from."""
import calendar
import re

MONTHS = [(str(m), calendar.month_name[m]) for m in range(1, 13)]
YEARS = [(str(y), str(y)) for y in range(2024, 2041)]

GENERIC_IBAN_RE = re.compile(r'^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$')


def month_label(month):
    return calendar.month_name[int(month)] if month else ''


def clean(value):
    return re.sub(r'\s+', '', value or '').upper()


def mask(value, keep=4):
    value = clean(value)
    if not value:
        return ''
    if len(value) <= keep:
        return value
    return 'X' * (len(value) - keep) + value[-keep:]
