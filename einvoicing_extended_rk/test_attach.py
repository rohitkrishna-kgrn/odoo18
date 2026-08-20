import base64, json
c = env['res.company'].browse(1)
c.write({'einv_enabled': True, 'einv_attach_pdf': True,
         'einv_api_base_url':'http://127.0.0.1:9911/api/v1',
         'einv_api_token':'kgrn_out_TESTTOKEN'})
journal = env['account.journal'].search([('type','=','sale'),('company_id','=',1)], limit=1)
tax = env['account.tax'].search([('type_tax_use','=','sale'),('company_id','=',1),('amount','=',5)], limit=1)
eng = env['project.project'].search([('company_id','=',1)], limit=1)
p = env['res.partner'].create({'name':'Attach Test LLC','company_type':'company',
    'vat':'100041283700003','country_id':env.ref('base.ae').id,
    'einv_peppol_id':'1010101012'})
prod = env['product.product'].create({'name':'Advisory','type':'service','einv_sac_code':'9983'})
inv = env['account.move'].create({'move_type':'out_invoice','company_id':1,
    'journal_id':journal.id,'partner_id':p.id,'invoice_date':'2026-08-18',
    'ar_responsible_id':env.ref('base.user_admin').id,
    'service_engagement_id':eng.id if eng else False,
    'invoice_type_classification':'completion',
    'invoice_line_ids':[(0,0,{'product_id':prod.id,'name':'Advisory work',
        'quantity':1,'price_unit':1000,'tax_ids':[(6,0,tax.ids)]})]})
inv.action_post()

# A supporting document dropped into the chatter, as a user would.
env['ir.attachment'].create({'name':'engagement-letter.pdf','mimetype':'application/pdf',
    'res_model':'account.move','res_id':inv.id,
    'datas': base64.b64encode(b'%PDF-1.7\n% engagement letter\n%%EOF')})
# One the platform will not accept, to prove it is skipped not fatal.
env['ir.attachment'].create({'name':'notes.txt','mimetype':'text/plain',
    'res_model':'account.move','res_id':inv.id,'datas': base64.b64encode(b'internal notes')})
# One picked explicitly in the Additional documents field.
extra = env['ir.attachment'].create({'name':'timesheet.xlsx',
    'mimetype':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'datas': base64.b64encode(b'PK\x03\x04 fake xlsx')})
inv.einv_attachment_ids = [(6,0,extra.ids)]
inv.invalidate_recordset(['einv_attachment_count'])
print('attach pdf:', inv.einv_attach_pdf, '| attach documents:', inv.einv_attach_documents,
      '| count shown in UI:', inv.einv_attachment_count)

atts = inv._einv_attachments_payload()
print('--- attachments[] built ---')
for a in atts:
    raw = base64.b64decode(a['base64'], validate=True)
    print('  %-28s %-70s %6d bytes -> %d b64 chars | decodes: OK | starts %r'
          % (a['fileName'], a['mimeCode'], len(raw), len(a['base64']), raw[:8]))
print('text/plain excluded:', not any(x['fileName']=='notes.txt' for x in atts))

print('--- submit ---')
inv.einv_push_state = 'submit'
inv._einv_push()
print(' state:', inv.einv_state, '| peppol:', inv.einv_peppol_status)
log = env['einvoice.log'].search([('move_id','=',inv.id),('operation','=','push')],
                                 order='id desc', limit=1)
sent = json.loads(log.request_body)['data']['attachments']
print(' attachments actually transmitted:', [(a['fileName'], a['mimeCode']) for a in sent])
print(' every base64 decodes:', all(base64.b64decode(a['base64'], validate=True) for a in sent))
print(' no data: prefix:', all(not a['base64'].startswith('data:') for a in sent))
env.cr.rollback()
