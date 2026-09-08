# -*- coding: utf-8 -*-
"""Work out who the *real*, external sender of an incoming mail is.

Mail reaching the CRM inboxes is very often a forward: a KGRN colleague picks
up an enquiry and pushes it on. Taken at face value the ``From`` header then
names the colleague, so the Mail Lead — and the pipeline record built from it —
ends up pointing at internal staff instead of at the client.

This module reads such a mail the way a person would: the ``From`` header
first, and when that turns out to be one of ours, the forwarded header block
in the body, then the headers a forwarding mailbox leaves behind, then the
body itself. It hands back the first *external* address it can defend, plus a
``source`` saying how it got there so the decision stays auditable.

Deliberately free of any ORM dependency beyond ``odoo.tools`` so the rules can
be reasoned about (and exercised in a shell) on their own.
"""
import re

from collections import namedtuple

from odoo import tools

# Comma/space separated. An entry containing "@" is matched as a whole
# address, anything else as a domain (subdomains included).
INTERNAL_DOMAINS_PARAM = 'crm_mail_lead_rk.internal_domains'
DEFAULT_INTERNAL_DOMAINS = 'kgrnaudit.com'

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+")

# "---------- Forwarded message ---------", "-----Original Message-----",
# "Begin forwarded message:". Dashes (or the "Begin"/colon) are required on
# purpose: the bare words turn up in ordinary prose all the time.
FORWARD_MARKER_RE = re.compile(
    r"-{2,}\s*(?:forwarded|original)\s+message\s*-{2,}"
    r"|begin\s+forwarded\s+message\s*:", re.I)

# "Fwd: ...", "FW: ...", "[Mailing list] Fwd: ..."
FORWARD_SUBJECT_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(?:fwd?|fw)\s*[:.]", re.I)

# A quoted/forwarded "From:" line. Leading ">" (quoting) and "*" (what
# html2plaintext makes of <strong>) are the usual decoration.
FROM_LINE_RE = re.compile(r"^[ \t>*|_-]*from[ \t*_]*:[ \t]*(.+)$", re.I | re.M)

# Where the next header starts, for forwards whose header block collapsed onto
# a single line (Outlook renders it as a table, and a table row is one line).
NEXT_HEADER_RE = re.compile(
    r"[ \t>*|_-]*(?:sent|date|to|cc|bcc|subject|reply[- ]?to)[ \t*_]*:", re.I)

# Robots, not clients. Only applied to the loosest tier — an address printed
# on an explicit "From:" line is the original sender whatever it is called.
NON_CLIENT_LOCALPART_RE = re.compile(
    r"^(?:no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer[-_.]?daemon|postmaster"
    r"|bounces?|unsubscribe|notifications?|alerts?|auto[-_.]?reply"
    r"|support|admin|webmaster|abuse)(?:[-_.+].*)?$", re.I)

# Headers a forwarding mailbox (or a list) leaves the original sender in.
FORWARD_HEADERS = ('X-Original-From', 'X-Original-Sender', 'X-Forwarded-Sender',
                   'X-Forwarded-For', 'Reply-To')

#: ``source`` values, from most to least trustworthy.
#:   ``header``    the From header was already external — nothing was rewritten
#:   ``forwarded`` a "From:" line in the forwarded header block
#:   ``headers``   a forwarding header (X-Original-From / Reply-To / ...)
#:   ``body``      first plausible external address in the body of a forward
#:   ``unknown``   a forward whose original sender could not be identified
#:   ``internal``  internal mail that is not a forward at all — not a lead
Sender = namedtuple('Sender', 'name email source')


class InternalDirectory(object):
    """Which addresses count as "us" rather than as a prospective client."""

    __slots__ = ('domains', 'addresses')

    def __init__(self, domains=(), addresses=()):
        self.domains = tuple(d.lower().lstrip('@') for d in domains if d)
        self.addresses = frozenset(a.lower().strip() for a in addresses if a)

    def matches(self, address):
        if not address:
            return False
        address = address.strip().strip('<>').lower()
        if address in self.addresses:
            return True
        domain = address.rpartition('@')[2]
        if not domain:
            return False
        return any(domain == known or domain.endswith('.' + known)
                   for known in self.domains)


def build_internal_directory(env, extra_addresses=()):
    """Read the configured internal domains/addresses into a directory.

    ``extra_addresses`` is for the mailbox's own address: mail *from* the
    inbox we are polling is never an incoming lead either.
    """
    raw = env['ir.config_parameter'].sudo().get_param(
        INTERNAL_DOMAINS_PARAM, DEFAULT_INTERNAL_DOMAINS) or ''
    domains, addresses = [], [a for a in extra_addresses if a]
    for entry in re.split(r'[,;\s]+', raw):
        entry = entry.strip().lower().lstrip('@')
        if not entry:
            continue
        (addresses if '@' in entry else domains).append(entry)
    return InternalDirectory(domains, addresses)


# ----------------------------------------------------------------------
# Address scraping
# ----------------------------------------------------------------------
def addresses_in(text):
    """Every syntactically valid address in ``text``, in order, deduplicated."""
    seen, found = set(), []
    for match in EMAIL_RE.finditer(text or ''):
        address = match.group(0).strip(" .,;:<>()[]'\"").lower()
        if address and '@' in address and address not in seen:
            seen.add(address)
            found.append(address)
    return found


def _first_external(addresses, internal, plausible_only=False):
    for address in addresses:
        if internal.matches(address):
            continue
        if plausible_only and NON_CLIENT_LOCALPART_RE.match(address.partition('@')[0]):
            continue
        return address
    return None


def _clean_name(value):
    """Tidy whatever sat in front of the address into a display name."""
    name = re.sub(r'\[\d+\]', ' ', value or '')          # html2plaintext link refs
    name = re.sub(r'(?i)\bmailto\s*:', ' ', name)
    name = re.sub(r'[<>"“”]', ' ', name)
    name = name.strip(" \t*_-,;:|()[]'")
    name = re.sub(r'\s{2,}', ' ', name).strip()
    if not name or len(name) > 80 or '://' in name:
        return ''
    # A bare repeat of the address, or leftover header noise, is not a name.
    if '@' in name or ':' in name:
        return ''
    return name


def _split_from_line(line, internal):
    """``Name <a@b.com> Sent: ...`` -> ``('Name', 'a@b.com')`` if external."""
    cut = NEXT_HEADER_RE.search(line)
    if cut:
        line = line[:cut.start()]
    address = _first_external(addresses_in(line), internal)
    if not address:
        return None
    index = line.lower().find(address)
    return _clean_name(line[:index] if index > 0 else ''), address


def _name_beside(text, address):
    """Best-effort display name for an address found loose in the body.

    Unlike a "From:" line, the words in front of a bare address are ordinary
    prose ("FYI - please contact Ravi Shankar ravi@..."), so only the run of
    capitalised words immediately before it is taken, and never more than a
    full name's worth.
    """
    index = text.lower().find(address)
    if index <= 0:
        return ''
    line_start = text.rfind('\n', 0, index) + 1
    prefix = _clean_name(text[line_start:index])
    words = []
    for word in reversed(prefix.split()):
        stripped = word.strip(".,;'\u2019-")
        # Title-case only: "Ravi" yes, "contact" no, and "FYI"/"KGRN" no
        # either — shouted acronyms are not what a client is called.
        if (len(words) == 3 or not stripped or not stripped[:1].isupper()
                or stripped.isupper() or not stripped.replace("'", '').replace('-', '').isalpha()):
            break
        words.append(stripped)
    return ' '.join(reversed(words))


def looks_forwarded(subject, text):
    return bool(FORWARD_SUBJECT_RE.match(subject or '')
                or FORWARD_MARKER_RE.search(text or ''))


def _to_text(body_html):
    if not body_html:
        return ''
    try:
        return tools.html2plaintext(body_html, include_references=False)
    except Exception:  # noqa: BLE001 - malformed html must not lose the mail
        return re.sub(r'<[^>]+>', ' ', body_html)


def _sender_from_forward_block(text, internal):
    """First external ``From:`` line, preferring the ones after a forward
    marker — a reply chain can carry several, and the block introduced by
    "---------- Forwarded message ----------" is the authoritative one."""
    marker = FORWARD_MARKER_RE.search(text)
    for segment in ([text[marker.end():]] if marker else []) + [text]:
        for match in FROM_LINE_RE.finditer(segment):
            found = _split_from_line(match.group(1), internal)
            if found:
                return Sender(found[0], found[1], 'forwarded')
    return None


# ----------------------------------------------------------------------
# The one entry point
# ----------------------------------------------------------------------
def resolve_sender(header_from, message, body_html, subject, internal):
    """Attribute one incoming mail to an external sender.

    :param str header_from: the raw ``From`` header.
    :param message: the parsed ``email.message.Message`` (read for the
        forwarding headers only).
    :param str body_html: the mail body, as ``message_parse`` returned it.
    :param str subject: the mail subject.
    :param InternalDirectory internal: who counts as staff.
    :rtype: Sender
    """
    header_name, header_address = tools.mail.parse_contact_from_email(header_from or '')
    if not header_address:
        candidates = addresses_in(header_from)
        header_address = candidates[0] if candidates else ''

    if not internal.matches(header_address):
        # Not one of ours: the header stands, exactly as before.
        return Sender(header_name or '',
                      header_address or (header_from or '').strip(),
                      'header')

    text = _to_text(body_html)

    # 1. The forwarded header block — the sender written down in full.
    found = _sender_from_forward_block(text, internal)
    if found:
        return found

    # 2. Headers a forwarding mailbox leaves behind.
    if message is not None:
        for header in FORWARD_HEADERS:
            for raw in message.get_all(header) or []:
                raw = str(raw)
                address = _first_external(addresses_in(raw), internal)
                if address:
                    index = raw.lower().find(address)
                    return Sender(_clean_name(raw[:index] if index > 0 else ''),
                                  address, 'headers')

    # 3. Loose addresses in the body — only when the mail really is a forward,
    #    otherwise every signature and unsubscribe link becomes a "client".
    if looks_forwarded(subject, text):
        address = _first_external(addresses_in(text), internal, plausible_only=True)
        if address:
            return Sender(_name_beside(text, address), address, 'body')
        return Sender('', '', 'unknown')

    # Internal mail that is not a forward at all: colleagues talking to each
    # other. Never a lead.
    return Sender('', '', 'internal')
