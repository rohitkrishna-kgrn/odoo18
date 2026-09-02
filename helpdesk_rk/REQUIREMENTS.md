# Helpdesk RK — Requirements & Enhancements

**Module:** `helpdesk_rk`
**Odoo Compatibility:** 18.0

---

## Enhancement 1 – Ticket Conversation (Chat)

### Chat Interface Design

**Requirement**
The conversation section must use an interface similar to the Odoo Discuss / Direct Message chat window to provide a familiar messaging experience.

### Ticket-Specific Internal Chat

The chat must be embedded directly inside the Helpdesk Ticket form and function as a ticket-specific conversation thread.

**Requirements:**
- The chat area must appear inside the ticket form view.
- The interface should resemble the Odoo Discuss direct message layout.
- Messages should be displayed in a conversational/chat format instead of a simple list or table.
- Each message should display:
  - Sender Name
  - Sender Role
  - Message Content
  - Date & Time
  - Attachment (if available)
- Messages should appear in chronological order.
- New messages should appear at the bottom.
- Users should be able to scroll through previous messages within the ticket.

### Ticket-Level Conversation Only

The conversation must remain strictly linked to the individual ticket.
- Each ticket has its own separate chat thread.
- Messages posted in one ticket must never appear in another ticket.
- The chat is not a global Discuss channel.
- The chat is not a mail thread shared across multiple records.
- The chat exists only within the specific Helpdesk Ticket where it was created.

### Message Composer

At the bottom of the chat section, display a message composer similar to Odoo Discuss:
- Message input box
- Attachment upload button
- Send button

Only the following users can use the composer while the ticket is active:
- Ticket Creator (Helpdesk User)
- Helpdesk Support Team

Other users:
- Can view the conversation history.
- Cannot type messages.
- Cannot upload attachments.
- Cannot send replies.

### Closed Ticket Behavior

When the ticket status becomes Done or Rejected:
- Hide or disable the message composer.
- Disable attachment uploads.
- Prevent sending new messages.
- Keep the entire conversation history visible.
- Display: *"This ticket has been closed. Conversation is now read-only."*

### UI Placement

The Helpdesk Ticket form should display fields in the following order:
1. Subject
2. Ticket Number
3. Ticket Creation Date
4. Deadline Date
5. Description
6. Ticket Attachment
7. Conversation (Discuss-style Ticket Chat)
8. Status

The Conversation (Discuss-style Ticket Chat) section should be embedded inside the ticket form itself and should visually behave like an internal direct-message chat thread dedicated to that ticket.

---

## Enhancement 2 – Conversation: notifications, editing, attachments, folding

### Message Notifications

A new chat message raises a toast in the corner of whatever backend page the
recipient is on, with an **Open Ticket** button, exactly once per message.

- Written by the **Helpdesk Support Team** → announced to the **ticket creator**.
- Written by the **ticket creator** → announced to the **assigned user** only.
  While the ticket is unassigned nobody is notified.
- Never to the author, and never broadcast to the whole support team.
- Suppressed for a recipient who already has that ticket's chat panel open and
  unfolded, since the message lands in front of them anyway.

Delivered over the recipient's own bus partner channel, so it works from any
screen in the backend. It is live only: a user who is logged out when the
message is sent sees it in the unread bell/badge instead, not as a toast.

### No Call Option

The call button and its Discuss/RTC wiring are removed from the conversation.

### Editing and Deleting Own Messages

The author of a message may edit or delete it for **10 minutes** after sending
(`CHAT_EDIT_WINDOW_MINUTES`), after which the controls disappear.

- Only the author, only on a New / In Progress ticket.
- Editing covers the text and the attached files (drop existing ones, add new).
- Deleting removes the message and the files sent with it.
- An edited message is marked *edited*.
- The remaining time is shown as a live countdown next to the message.
- The window is measured on the **server** on every edit and delete, so a stale
  tab or a wrong client clock cannot reopen it.

### Attachments

- Uploads are created as the acting user rather than through `sudo()`, and the
  ids handed back are re-validated server-side before a message adopts them
  (`_link_pending_chat_attachments`): still parked on the composer, unposted,
  and created by the person posting. `message_post()` applies the same
  `create_uid` test, so anything else is silently dropped.
- Sending was verified end to end over real HTTP against `live` (upload →
  post → the other party downloads). Note that the `sudo()` create was **not**
  itself the defect: since Odoo 16 `sudo()` keeps `env.uid` and only sets
  `su`, so `create_uid` was already the acting user. No send-side failure
  could be reproduced, and no such request appears in the log — the chat has
  never carried a message in production.
- The download side *was* fragile and is the substantive fix: files used to be
  linked as `/web/content/<id>?download=true`, which authorises through
  `ir.attachment` ACLs and therefore through whatever record rules apply to
  the attachment and to the ticket behind it. `live` already carries four
  `ir.attachment` record rules (from recruitment; currently no members), and
  this module ships `security/helpdesk_record_rules.xml` restricting tickets
  to their creator — unused today only because it is absent from the manifest.
  Under either, the opposite party's download breaks.
- Sent files render with name, size, a download button, and an inline preview
  for images.
- Both parties download through `/helpdesk_rk/chat/attachment/<id>`, which
  authorises against the ticket (creator, assigned agent, support/admin)
  instead of relying on attachment ACLs following the record.
- A file attached and then removed before sending is deleted again.

### Foldable, Draggable Chat Dock

The conversation is no longer a block in the sheet; it is a floating dock over
the ticket form.

- Folded, it is a small round chat icon carrying an unread badge.
- Open, it is a panel with a title bar carrying a minimise button.
- Both states can be dragged anywhere over the form and stay inside the
  viewport; the position and folded state are remembered per browser.
- On a phone the open panel becomes a bottom sheet.
- A folded panel does **not** mark the conversation read — the bell keeps
  ringing until the user actually opens it.
