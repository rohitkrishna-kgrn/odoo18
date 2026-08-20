c = env['res.company'].browse(1)
print('base url:', c.einv_api_base_url, '| token set:', bool(c.einv_api_token))
status, body, err = env['einvoice.api']._request(
    'GET', c._einv_api_url('external/outbound/whoami'), token=c.einv_api_token, timeout=10)
print('whoami ->', status, err or body)
