# einvoicing_extended_rk

KGRN eInvoicing Platform integration for Odoo 18 — UAE FTA Phase 2, PINT-AE,
5-corner model.

Odoo only ever speaks JSON over HTTPS. The platform does the PINT-AE mapping,
validation, signing, clearance and Peppol delivery.

## Document type mapping

| PINT-AE | Name | Direction | Odoo document |
|---|---|---|---|
| `380` | Tax Invoice | AR outbound | Customer Invoice (`out_invoice`) |
| `389` | Self-Billed Invoice | AR outbound | Customer Invoice with **Self-Billed** ticked |
| `381` | Credit Note | AR outbound | Customer Credit Note (`out_refund`) |
| `261` | Self-Billed Credit Note | AR outbound | Customer Credit Note with **Self-Billed** ticked |
| `380` / `389` | Invoice received | AP inbound | Vendor Bill (`in_invoice`) |
| `381` / `261` | Credit Note received | AP inbound | Vendor Credit Note (`in_refund`) |

The type code is computed from the Odoo document type plus the **Self-Billed**
flag, and can be overridden per document. Inbound, the *event* decides invoice
vs credit note (`ap.invoice.received` / `ap.credit_note.received`) — not the
numeric code, because `380`/`389` are both UBL `Invoice` and `381`/`261` are
both UBL `CreditNote`.

## Setup — AR outbound

**Settings ▸ Accounting ▸ KGRN eInvoicing — AR outbound**, per company.

1. **Enable eInvoicing** and set the **API Base URL** for the environment
   (`https://uat.kgrnaudit.com/api/v1` for UAT). UAT and production differ —
   never point a UAT token at production.
2. Get a token, either way round:
   - Paste one issued in the portal under *Settings ▸ Active tokens* (prefix
     `kgrn_out_`, shown once and never recoverable), or
   - press **Generate Token** and give the portal credentials of an entity
     administrator. The password is used for that one call and never stored.
3. Press **Test Connection** — it calls `whoami` and fills in the entity, TRN,
   Peppol sender id and location. Do this before mapping anything else.
4. Choose the **Default Push Mode**: `draft` while proving the mapping, `submit`
   in production. **Push on Post** makes every posted AR document go out
   automatically; a failure never blocks posting.
5. Fill the **Seller defaults**. The platform overrides the seller block from the
   entity profile, but *Transaction Type* (rule `BTUAE-002`) and *Payment Means*
   (rule `AE-PMC`) are genuinely enforced.

### The field map on the document

The **eInvoicing** tab carries every key the API accepts, in the order the
documentation groups them — including the **Seller**, **Buyer** and
**Deliver-To** party blocks, the document allowances, the attachments and the
totals. Nothing is transmitted that the form does not show.

The party blocks auto-fill from the customer, the delivery address and the
company, and stay editable per document, so a one-off detail (a passport on a
walk-in sale, a different accounts-payable contact, a corrected emirate code)
goes on the invoice rather than in the address book. **Reload Parties from
Customer / Company** pulls the current master data back in and discards those
edits. Line-level keys — item name, classification, VAT category, gross price,
line object, line allowances — are on each invoice line; the four most-used sit
in the line grid as optional columns, the rest in the line dialog.

Totals are shown but never sent as given: the platform derives them from the
lines and allowances on submit.

### Attachments

Everything in `attachments[]` is base64-encoded at push time, as a bare string
with no `data:` prefix. Three sources, all controlled on the invoice under
**eInvoicing > Attachments**:

| Source | Control |
|---|---|
| The rendered invoice PDF | *Attach Invoice PDF* - defaults to the company setting, overridable per document |
| Files attached to the invoice, chatter included | *Attach Documents on this Invoice* (on by default) |
| Anything else you pick | the *Additional documents to send* field |

*Files to Send* shows how many the next push will carry. PDF, Word and Excel are
the accepted types; anything else, and any file over 10 MB, is skipped and noted
in the log rather than failing the push - an attachment is never the point of the
transmission. Odoo's own stored copy of the invoice report is filtered out so it
cannot go twice.

### Master data the rules require

| Where | Field | Why |
|---|---|---|
| Customer ▸ eInvoicing | Peppol scheme + electronic address | the transmission receiver — **not** the TRN |
| Customer | Tax ID (TRN), address, emirate | `BuyerVatIdentifier` and the address block |
| Product ▸ Accounting | Item Type, SAC code, HS classification | `VAL-ITEM-SAC` on services, `VAL-ITEM-CLASS` on goods |
| Tax ▸ Advanced Options | eInvoice VAT Category | S / Z / E / AE / O / N; VAT is computed for S and N only |
| Unit of Measure | UN/ECE Rec 20 code | the `unit` on each line; seeded on install, `C62` by default |
| Contacts ▸ States | PINT-AE emirate code | seeded on install — `DU`→`DXB`, `AZ`→`AUH`, etc. |

### Pushing

On a posted customer invoice or credit note:

- **Check eInvoice** — runs the mandatory-field checks locally, no API call.
- **Send to ASP** / **Resend to ASP** — pushes under the Unique Invoice Number.
- **Submit to FTA** — pushes with `PushState: submit` whatever the default is.
- **Preview JSON** — stores the exact payload in the log without sending it.

Select several invoices in the list and use the **Send to ASP** action to push a
batch (the platform caps a batch at 200; larger selections are split).

### Correction loop

A document that fails PINT-AE validation is stored on the platform as a
correctable draft and is **never** submitted. The errors appear in a red banner
on the invoice with the offending *field* and the suggested *fix*. Correct them
and push again — the Unique Invoice Number is unchanged, so the same platform
record is updated and no duplicate is created.

A cleared document is locked: it cannot be reset to draft in Odoo, and a further
push is answered with `ALREADY_SUBMITTED`, which is treated as success.

## Setup — AP inbound

**Settings ▸ Accounting ▸ KGRN eInvoicing — AP inbound**, per company.

1. **Enable the AP webhook** and copy the **Webhook URL** shown
   (`https://<host>/einvoicing/ap/webhook`) into the KGRN portal under
   *Connectors / ERP webhook* (`apErpWebhook.url`).
2. Pick the **authentication** matching `apErpWebhook.authType` and press
   **Generate Webhook Token** for bearer / API key. Set the same value on the
   KGRN side.
3. Set the **AP Journal** and the fallbacks used when a received item, tax or
   account matches nothing in Odoo.
4. Set the **KGRN Entity ID** when more than one company receives documents —
   it is how a payload is routed to the right company. With a single AP-enabled
   company it is optional.
5. Use the portal's **Test webhook** action; `erp.webhook.test` is answered with
   `200` and nothing is written.

Received documents land in **Accounting ▸ eInvoicing ▸ AP — Received** as drafts
so the accounts and taxes can be checked before posting. Turn on
**Auto-post Inbound Documents** only once the mapping is proven.

### Webhook semantics

| Situation | Answer | Platform behaviour |
|---|---|---|
| Document stored | `200` `{"ok": true, "received": "<id>"}` | done |
| Bad / missing credentials | `401` | permanent — no retry |
| Malformed body, unknown event, no AP journal | `400` | permanent — no retry |
| Unexpected failure on our side | `500` | **one** retry |

Delivery is idempotency-keyed on `document.instanceId`: a repeat updates the
same draft. A document already posted in Odoo is never rewritten.

## Operations

- **Accounting ▸ eInvoicing ▸ Transmissions** — every exchange in both
  directions, with the full request and response bodies. Quote the **Request ID**
  in a support ticket.
- **AR — To Send** — posted documents the platform has not yet accepted.
- **Validation Errors** — the correction worklist.
- Cron *push pending AR documents* (hourly, **disabled by default**) retries
  everything still `not_sent` / `error` for companies with Push on Post.
- Cron *warn about expiring API tokens* (daily) raises an activity 14 days
  before a token expires. Rotate in this order: issue the new token, switch Odoo
  over, then revoke the old one.

## Security

`eInvoicing / User` may push and read the log. `eInvoicing / Manager` may
configure tokens and the webhook, preview payloads and reset a stuck document.
Tokens and passwords are stored on `res.company` behind `base.group_system`, and
the token is redacted in every log entry.
