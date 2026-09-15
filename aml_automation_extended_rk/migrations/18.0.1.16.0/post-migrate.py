from odoo import api, SUPERUSER_ID


def _classify_source(env, doc):
    """Best-effort classification of a pre-existing aml.hit.document row that
    predates the 'source' field, using the chatter trail on its aml.request.

    Both aml.hit.wizard (HIT flow) and aml.additional.docs.wizard (Additional
    Info flow) post an identical "Additional document request sent to
    client (...). Documents requested: X, Y" message when they create these
    rows, so the message text alone can't tell the two apart. But only the
    HIT flow's action_hit_detected() posts "HIT Detected! Opening wizard to
    request additional documents." immediately beforehand (same button
    click) - so whichever chatter message names this document, the message
    directly preceding it settles which flow created it.
    """
    messages = env['mail.message'].sudo().search([
        ('model', '=', 'aml.request'),
        ('res_id', '=', doc.request_id.id),
    ], order='id asc')

    marker = 'Documents requested:'
    doc_name = (doc.document_name or '').strip()
    for i, msg in enumerate(messages):
        body = (msg.body or '')
        if marker not in body:
            continue
        names = [n.strip() for n in body.split(marker, 1)[1].split(',')]
        # Strip the closing </p> (or similar trailing markup) off the last name.
        names = [n.split('<')[0].strip() for n in names]
        if doc_name not in names:
            continue
        for prev in reversed(messages[:i]):
            prev_body = (prev.body or '').strip()
            if not prev_body:
                continue
            return 'hit' if 'Opening wizard to request additional documents' in prev_body else 'additional_info'
        break
    # No matching chatter (e.g. the message was deleted) - fall back to the
    # field's own default rather than guessing further.
    return doc.source


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for doc in env['aml.hit.document'].search([]):
        source = _classify_source(env, doc)
        if source != doc.source:
            doc.write({'source': source})
