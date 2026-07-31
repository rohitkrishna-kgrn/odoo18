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
