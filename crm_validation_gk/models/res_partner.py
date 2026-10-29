import re

from odoo import _, api, models
from odoo.exceptions import UserError

# Set by the screens where a person creates or renames a customer. Server
# flows (website leads, referrals, imports) never carry it, so they are not
# interrupted by the check.
CHECK_SIMILAR_NAME = 'crm_validation_check_similar_name'

# Legal-form words dropped from the end of a name before comparing, so
# "SILVER PALM INTERIORS L L C" and "Silver Palm Interiors" are the same customer.
LEGAL_SUFFIXES = {
    'llc', 'fzllc', 'fzco', 'fzc', 'fze', 'fz', 'dmcc', 'ltd', 'limited',
    'inc', 'llp', 'plc', 'pvt', 'private', 'est', 'establishment', 'co',
    'corp', 'corporation', 'company',
}


def _name_tokens(name):
    """Lower-case words of a name, runs of single letters joined (L L C -> llc),
    trailing legal-form words removed."""
    tokens, letters = [], ''
    for word in re.findall(r'[^\W_]+', (name or '').casefold()):
        if len(word) == 1 and word.isalpha():
            letters += word
            continue
        if letters:
            tokens.append(letters)
            letters = ''
        tokens.append(word)
    if letters:
        tokens.append(letters)
    stripped = list(tokens)
    while stripped and stripped[-1] in LEGAL_SUFFIXES:
        stripped.pop()
    return stripped or tokens


def similar_name_key(name):
    """Comparison key: case, spacing, punctuation and legal form ignored."""
    return ''.join(_name_tokens(name))


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def name_create(self, name):
        return super(ResPartner, self.with_context(**{CHECK_SIMILAR_NAME: True})).name_create(name)

    def web_save(self, vals, specification, next_id=None):
        return super(ResPartner, self.with_context(**{CHECK_SIMILAR_NAME: True})).web_save(
            vals, specification, next_id=next_id)

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        if self.env.context.get(CHECK_SIMILAR_NAME):
            partners._check_similar_customer_name(_("cannot be created"))
        return partners

    def write(self, vals):
        if 'name' not in vals or not self.env.context.get(CHECK_SIMILAR_NAME):
            return super().write(vals)
        before = {partner.id: similar_name_key(partner.name) for partner in self}
        res = super().write(vals)
        # A rename that keeps the same key (e.g. fixing the case) is allowed.
        self.filtered(
            lambda p: similar_name_key(p.name) != before[p.id]
        )._check_similar_customer_name(_("cannot be used"))
        return res

    def _find_similar_customers(self):
        """Active top-level contacts whose name matches this one's key."""
        self.ensure_one()
        tokens = _name_tokens(self.name)
        if not tokens:
            return self.browse()
        key = ''.join(tokens)
        # Narrow in SQL on the longest word (punctuation-free, case-blind),
        # then compare full keys in Python.
        self.flush_model(['name', 'active', 'parent_id'])
        self.env.cr.execute("""
            SELECT id, name FROM res_partner
             WHERE parent_id IS NULL AND active AND id != %s AND name IS NOT NULL
               AND lower(regexp_replace(name, '[^[:alnum:]]+', '', 'g')) LIKE %s
        """, [self.id, '%' + max(tokens, key=len) + '%'])
        ids = [pid for pid, name in self.env.cr.fetchall() if similar_name_key(name) == key]
        return self.browse(ids)

    def _check_similar_customer_name(self, blocked):
        """Contact persons under a company are not checked; only customers."""
        for partner in self.filtered(lambda p: not p.parent_id and p.active and p.name):
            similar = partner._find_similar_customers()
            if similar:
                raise UserError(_(
                    "Customer already exists: a customer with a similar name is "
                    "already in the system, so the name \"%(name)s\" %(blocked)s."
                    "\n\n%(rows)s",
                    name=partner.name,
                    blocked=blocked,
                    rows="\n".join("• %s" % p.name for p in similar.sorted('name')),
                ))
