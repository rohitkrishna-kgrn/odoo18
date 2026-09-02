# Ad-hoc replay of AP deliveries that were dismissed against an AR invoice.
#
# The module upgrade (migrations/1.0.1) already does this for every affected
# document, so this script is only for replaying a chosen subset afterwards:
#
#   /opt/odoo18/venv/bin/python3 /opt/odoo18/odoo/odoo-bin shell \
#       -c /etc/odoo18.conf -d live --http-port=8199 --gevent-port=8299 \
#       < /opt/odoo18/custom-addons/einvoicing_extended_rk/backfill_ap_swallowed.py
#
# Set LOG_IDS to limit it, e.g. [178] for INV/26-27/0061; empty = all remaining.
LOG_IDS = []

recovered = env['account.move']._einv_replay_swallowed_ap(log_ids=LOG_IDS or None)
for move in recovered:
    print('  recovered %-18s bill id=%-5s vendor=%-24r total=%-10s %s'
          % (move.ref, move.id, move.partner_id.name, move.amount_total, move.state))
print('recovered %s document(s)' % len(recovered))
env.cr.commit()
print('committed')
