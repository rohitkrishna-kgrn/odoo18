"""Read an uploaded copy of the HR "Employee Personal Details" paper form (PDF or Word) and return the
text written after each label, so the personal details form can be filled from it.

Only text is read: a scanned image has no text to read (there is no OCR engine installed)."""
import io
import re
import zipfile

from lxml import etree

from odoo.exceptions import UserError

MAX_BYTES = 10 * 1024 * 1024
W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

# (details field or None to ignore, label regex). Longest / most specific labels first is not
# required: the scan always takes the leftmost match, so "Nationality (Country):" beats "Country:".
LABELS = [
    (None, r'Name\s*:'), (None, r'Designation\s*:'), (None, r'Department\s*:'),
    ('current_street', r'Private\s+Address\s*[^\w\s:]{0,3}\s*Street\s*:'),
    ('private_street2', r'Street\s*:'),
    ('current_city', r'City\s*:'),
    ('private_state_id', r'State\s*:'),
    ('current_zip', r'(?:ZIP|Postal\s+Code)\s*:'),
    ('current_country_id', r'Country\s*:'),
    ('personal_email', r'(?:Private\s+)?E-?mail\s*:'),
    ('personal_mobile', r'Private\s+(?:Phone|Mobile)\s*:'),
    ('bank_account_no', r'Bank\s+Account\s*:'),
    ('km_home_work', r'Home\s*-?\s*Work\s+Distance\s*:'),
    ('private_car_plate', r'Private\s+Car\s+Plate\s*:'),
    ('country_id', r'Nationality\s*(?:\(\s*Country\s*\))?\s*:'),
    ('uid_aadhar_no', r'UID\s+No\s*/\s*Aadha?ar\s+No\s*:'),
    ('emirates_id_no', r'Emirates\s+ID\s+No\s*:'),
    ('passport_no', r'Passport\s+No\s*:'),
    ('gender', r'Gender\s*:'),
    ('birthday', r'Date\s+of\s+Birth\s*:'),
    ('place_of_birth', r'Place\s+of\s+Birth\s*:'),
    ('country_of_birth_id', r'Country\s+of\s+Birth\s*:'),
    ('emergency_name', r'Contact\s+Name\s*:'),
    ('emergency_phone', r'Contact\s+Phone\s*:'),
    ('highest_qualification', r'Qualification\s*:'),
    ('field_of_study', r'Field\s+of\s+Study\s*:'),
    ('school', r'School\s*:'),
    ('marital', r'Marital\s+Status\s*:'),
    ('children', r'Number\s+of\s+Dependent\s+Children\s*:'),
    ('visa_no', r'Visa\s+No\s*:'),
    ('work_permit_no', r'Work\s+Permit\s+No\s*:'),
    ('visa_expiry', r'Visa\s+Expiration\s+Date\s*:'),
    ('work_permit_expiry', r'Work\s+Permit\s+Expiration\s+Date\s*:'),
    (None, r'Work\s+Permit\s*:'),
    # section headings end the previous value (upper case only)
    (None, r'(?-i:PRIVATE\s+CONTACT|CITIZENSHIP|EMERGENCY\s+CONTACT|EDUCATION|FAMILY\s+STATUS|'
           r'WORK\s+PERMIT|EMPLOYEE\s+PERSONAL\s+DETAILS)'),
]
_PATTERN = re.compile('|'.join(f'(?P<g{i}>{rx})' for i, (_f, rx) in enumerate(LABELS)), re.I)


def extract_text(filename, content):
    if len(content) > MAX_BYTES:
        raise UserError("The file is larger than 10 MB.")
    ext = (filename or '').rsplit('.', 1)[-1].lower()
    if ext == 'pdf':
        return _pdf_text(content)
    if ext == 'docx':
        return _docx_text(content)
    raise UserError("Only PDF and Word (.docx) files can be read. Scanned images cannot be read.")


def _pdf_text(content):
    import fitz  # PyMuPDF
    try:
        doc = fitz.open(stream=content, filetype='pdf')
    except Exception:
        raise UserError("This PDF could not be opened.")
    parts = []
    for page in doc:
        parts.append(page.get_text('text'))
        # typed-in fillable form fields: "<field name>: <value>"
        for widget in (page.widgets() or []):
            if widget.field_value and isinstance(widget.field_value, str):
                parts.append(f"\n{widget.field_name}: {widget.field_value}\n")
    return '\n'.join(parts)


def _docx_text(content):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            xml = zf.read('word/document.xml')
    except Exception:
        raise UserError("This Word file could not be opened.")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    root = etree.fromstring(xml, parser)
    lines = []
    for para in root.iter(W_NS + 'p'):
        text = ''.join(t.text or '' for t in para.iter(W_NS + 't'))
        if text.strip():
            lines.append(text)
    return '\n'.join(lines)


def parse(text):
    """{details field: raw text written after its label}"""
    text = (text or '').replace('–', '-').replace('—', '-').replace('\xa0', ' ')
    hits = [(m.start(), m.end(), LABELS[int(m.lastgroup[1:])][0]) for m in _PATTERN.finditer(text)]
    out = {}
    for i, (_start, end, field) in enumerate(hits):
        if not field:
            continue
        stop = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        value = re.sub(r'\s+', ' ', text[end:stop]).strip(' :-_|')
        if value and len(value) <= 200 and field not in out:
            out[field] = value
    return out
