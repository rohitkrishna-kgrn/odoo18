order = env['sale.order'].browse(5976)
open('/tmp/claude-0/-/7f606cef-5ab5-4f96-acc8-14c5d8d9d5b2/scratchpad/se.pdf','wb').write(order._build_se_pdf())
print("regenerated")
