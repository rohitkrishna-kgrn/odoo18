from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """(Re-)classify every pre-existing aml.hit.document row's 'source' using
    the chatter trail on its aml.request, replacing the 18.0.1.16.0 attempt.

    Both aml.hit.wizard (HIT flow) and aml.additional.docs.wizard (Additional
    Info flow) post an identical "Additional document request sent to
    client (...). Documents requested: X, Y" message when they create these
    rows, so message text alone can't tell the two apart - but only the HIT
    flow's action_hit_detected() posts "HIT Detected! Opening wizard to
    request additional documents." immediately beforehand (same button
    click), so the message directly preceding a "Documents requested" one
    settles which flow produced that batch.

    18.0.1.16.0 matched batches to rows by document_name, which misclassified
    any request where two different-flow batches reused the same document
    name (e.g. "test" requested twice) - both rows collapsed onto whichever
    batch the name matched first. Row creation order mirrors chatter order
    (each wizard call creates its lines then immediately posts its
    "Documents requested" message in the same transaction), so matching
    batches to rows positionally - Nth surviving row gets the Nth batch's
    source, in id order - disambiguates same-named batches correctly.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    docs_by_request = {}
    for doc in env['aml.hit.document'].search([], order='request_id, id'):
        docs_by_request.setdefault(doc.request_id.id, []).append(doc)

    marker = 'Documents requested:'
    for request_id, docs in docs_by_request.items():
        messages = env['mail.message'].sudo().search([
            ('model', '=', 'aml.request'),
            ('res_id', '=', request_id),
        ], order='id asc')

        batches = []
        for i, msg in enumerate(messages):
            body = msg.body or ''
            if marker not in body:
                continue
            names = [n.split('<')[0].strip() for n in body.split(marker, 1)[1].split(',')]
            names = [n for n in names if n]
            source = 'additional_info'
            for prev in reversed(messages[:i]):
                prev_body = (prev.body or '').strip()
                if not prev_body:
                    continue
                if 'Opening wizard to request additional documents' in prev_body:
                    source = 'hit'
                break
            batches.append((source, len(names)))

        pos = 0
        for source, count in batches:
            for doc in docs[pos:pos + count]:
                if doc.source != source:
                    doc.write({'source': source})
            pos += count
