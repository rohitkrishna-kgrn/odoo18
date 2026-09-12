import base64

from odoo import models
from num2words import num2words

# Signatures of the image formats the PDF renderer (wkhtmltopdf / QtWebKit)
# can actually display. It has no WebP decoder -- a WebP logo shows as a
# broken-image icon, not a missing image, so it's safer to print no logo at
# all than to point <img> at data most viewers can't decode.
_RK_LOGO_SAFE_MAGIC = (
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'\xff\xd8\xff', 'image/jpeg'),
    (b'GIF87a', 'image/gif'),
    (b'GIF89a', 'image/gif'),
    (b'BM', 'image/bmp'),
)


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ------------------------------------------------------------------
    # KGRN UAE tax-invoice report helpers (Template RK)
    #
    # Everything the PDF prints is derived from the move here so the
    # template stays declarative and the same layout works for every
    # invoice / credit note without hard-coded values.
    # ------------------------------------------------------------------
    def _rk_logo_data_uri(self):
        """data: URI for the company logo, or '' if there is none / the
        stored format isn't one the PDF renderer can display (e.g. WebP)."""
        self.ensure_one()
        logo = self.company_id.logo
        if not logo:
            return ''
        try:
            raw = base64.b64decode(logo)
        except Exception:
            return ''
        for magic, mime in _RK_LOGO_SAFE_MAGIC:
            if raw.startswith(magic):
                return 'data:%s;base64,%s' % (mime, logo.decode('utf-8'))
        return ''

    def _rk_report_title(self):
        """FTA-compliant document heading, driven by the move type."""
        self.ensure_one()
        return {
            'out_invoice': 'TAX INVOICE',
            'out_refund': 'TAX CREDIT NOTE',
            'in_invoice': 'VENDOR INVOICE',
            'in_refund': 'VENDOR CREDIT NOTE',
        }.get(self.move_type, 'TAX INVOICE')

    def _rk_fmt(self, amount):
        """Fixed 2-decimal, comma-grouped amount (locale independent)."""
        return '{:,.2f}'.format(amount or 0.0)

    def _rk_date(self, value):
        """dd-MMM-yyyy, e.g. 31-Jul-2026."""
        return value.strftime('%d-%b-%Y') if value else ''

    def _rk_date_of_supply(self):
        self.ensure_one()
        return self._rk_date(self.delivery_date or self.invoice_date)

    def _rk_amount_in_words(self, amount=None):
        """Amount spelled out, prefixed with the currency and suffixed 'Only'.

        6825.00 AED -> "UAE Dirhams Six Thousand Eight Hundred Twenty-Five Only"
        """
        self.ensure_one()
        if amount is None:
            amount = self.amount_total
        amount = amount or 0.0
        currency = self.currency_id
        whole = int(amount)
        frac = int(round((amount - whole) * 100))
        unit_label = 'UAE Dirhams' if currency.name == 'AED' else (
            currency.currency_unit_label or currency.name or '')
        sub_label = currency.currency_subunit_label or 'Fils'
        text = ('%s %s' % (unit_label, self._rk_words(whole))).strip()
        if frac:
            text += ' and %s %s' % (self._rk_words(frac), sub_label)
        return '%s Only' % text

    @staticmethod
    def _rk_words(number):
        """num2words in plain title case, no British 'and' / comma grouping."""
        raw = num2words(int(number), lang='en').replace(',', '').replace(' and ', ' ')
        return raw.title()

    # kept so any old caller / cached template that still references it keeps working
    def amount_to_words(self, amount):
        if not amount:
            return ''
        return num2words(int(amount), lang='en')

    def _rk_payment_term_days(self):
        """Whole days between invoice date and due date, for the T&C line."""
        self.ensure_one()
        if self.invoice_date and self.invoice_date_due:
            return max((self.invoice_date_due - self.invoice_date).days, 0)
        return 30

    def _rk_payment_terms_text(self):
        """First T&C line, phrased for whatever payment terms the invoice has."""
        self.ensure_one()
        if self.invoice_payment_term_id:
            return 'Payment due per agreed terms: %s.' % self.invoice_payment_term_id.name
        days = self._rk_payment_term_days()
        if days > 0:
            return 'Payment due within %s days of invoice date.' % days
        return 'Payment due upon receipt of this invoice.'

    def _rk_invoice_bank_accounts(self):
        """Bank accounts to print for payment: the ones explicitly flagged on
        the company, otherwise every bank account of the company partner."""
        self.ensure_one()
        return self.company_id.invoice_bank_ids or self.company_id.partner_id.bank_ids

    def _rk_report_lines(self):
        """[(serial_or_None, line)] for the invoice table — product lines get a
        running S.No, section / note lines are passed through with None."""
        self.ensure_one()
        rows = []
        serial = 0
        for line in self.invoice_line_ids:
            if line.display_type == 'product':
                serial += 1
                rows.append((serial, line))
            elif line.display_type in ('line_section', 'line_note'):
                rows.append((None, line))
        return rows


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _rk_vat_rate_label(self):
        """"5%", "5%, 0%" or "0%" — the percentage taxes applied to the line."""
        self.ensure_one()
        seen = []
        for tax in self.tax_ids:
            if tax.amount_type == 'percent':
                label = '%g%%' % tax.amount
                if label not in seen:
                    seen.append(label)
        return ', '.join(seen) if seen else '0%'

    def _rk_vat_amount(self):
        self.ensure_one()
        return self.price_total - self.price_subtotal
