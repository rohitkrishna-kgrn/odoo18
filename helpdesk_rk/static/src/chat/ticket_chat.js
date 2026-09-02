/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { Component, useState, useRef, onWillStart, onWillUpdateProps, onMounted, onWillUnmount, useEffect } from "@odoo/owl";
import { ignoreDestroyedComponentError } from "../utils/silence_destroyed_error";

const DOCK_STORAGE_KEY = "helpdesk_rk.chat_dock";
const DOCK_MARGIN = 16;
const DRAG_THRESHOLD = 4;

export class TicketChat extends Component {
    static template = "helpdesk_rk.TicketChat";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.busService = useService("bus_service");
        // Shared with the global toast service: while this panel is open on a
        // ticket, its messages must not also pop a notification in the corner.
        this.chatNotification = useService("helpdesk_rk.chat_notification");
        this.rootRef = useRef("root");
        this.messagesRef = useRef("messages");
        this.fileInputRef = useRef("fileInput");
        this.state = useState({
            messages: [],
            canPost: false,
            isClosed: false,
            isUnsaved: false,
            loading: true,
            sending: false,
            draft: "",
            pendingAttachments: [],
            otherParty: null,
            // Fold / drag
            folded: true,
            unseen: 0,
            position: null,
            dragging: false,
            // Inline edit of one of my own messages
            editingId: null,
            editDraft: "",
            editAttachments: [],
            editSaving: false,
            // Bumped by the ticker so the edit countdown re-renders
            now: Date.now(),
        });
        // The server tells us how many seconds are left on each message's
        // edit window at the moment the thread is loaded; the countdown then
        // runs against elapsed time since that load, so a browser clock that
        // is minutes off cannot re-open a closed window.
        this.loadedAt = Date.now();
        this.editWindowEndsAt = 0;
        this.busChannel = null;
        this.presenceChannel = null;
        this.uploadTarget = "composer";
        this.drag = null;
        this.suppressClick = false;

        this.onBusNotification = this.onBusNotification.bind(this);
        this.onTicketUpdated = this.onTicketUpdated.bind(this);
        this.onImStatusUpdated = this.onImStatusUpdated.bind(this);
        this.onDragMove = this.onDragMove.bind(this);
        this.onDragEnd = this.onDragEnd.bind(this);
        this.onWindowResize = this.onWindowResize.bind(this);

        this.restoreDockState();

        onWillStart(() => this.loadChat());

        onMounted(() => {
            this.subscribeToBus(this.resId);
            this.clampToViewport();
            browser.addEventListener("resize", this.onWindowResize);
            this.ticker = browser.setInterval(() => this.onTick(), 1000);
        });

        onWillUpdateProps((nextProps) => {
            const stageChanged = nextProps.record.data.stage_id !== this.props.record.data.stage_id;
            const recordChanged = nextProps.record.resId !== this.props.record.resId;
            if (recordChanged || stageChanged) {
                this.loadChat(nextProps.record.resId);
            }
            if (recordChanged) {
                this.cancelEdit();
                this.subscribeToBus(nextProps.record.resId);
            }
        });

        onWillUnmount(() => {
            this.busService.unsubscribe("helpdesk_rk_chat_message", this.onBusNotification);
            this.busService.unsubscribe("helpdesk_rk_ticket_updated", this.onTicketUpdated);
            this.busService.unsubscribe("bus.bus/im_status_updated", this.onImStatusUpdated);
            if (this.busChannel) {
                this.busService.deleteChannel(this.busChannel);
            }
            if (this.presenceChannel) {
                this.busService.deleteChannel(this.presenceChannel);
            }
            this.stopDragListeners();
            browser.removeEventListener("resize", this.onWindowResize);
            browser.clearInterval(this.ticker);
            if (this.chatNotification.activeTicketId === this.resId) {
                this.chatNotification.activeTicketId = null;
            }
        });

        this.busService.subscribe("helpdesk_rk_chat_message", this.onBusNotification);
        this.busService.subscribe("helpdesk_rk_ticket_updated", this.onTicketUpdated);
        this.busService.subscribe("bus.bus/im_status_updated", this.onImStatusUpdated);

        useEffect(
            () => this.scrollToBottom(),
            () => [this.state.messages.length, this.state.folded]
        );

        // Tell the toast service which ticket the user is actually watching,
        // so a message that lands in front of their eyes is not also
        // announced in the corner.
        useEffect(
            () => {
                this.chatNotification.activeTicketId = this.state.folded ? null : this.resId;
                // Opening turns a 52px button into a 380px panel: whatever
                // corner the dock was parked in, keep it fully on screen.
                this.clampToViewport();
            },
            () => [this.state.folded, this.resId]
        );
    }

    get resId() {
        return this.props.record.resId;
    }

    // ------------------------------------------------------------
    // Bus
    // ------------------------------------------------------------

    subscribeToBus(resId) {
        if (this.busChannel) {
            this.busService.deleteChannel(this.busChannel);
            this.busChannel = null;
        }
        if (resId) {
            this.busChannel = `helpdesk_rk.ticket_chat_${resId}`;
            this.busService.addChannel(this.busChannel);
        }
    }

    // Odoo's own presence system: every user's online/away/offline status
    // is pushed on "odoo-presence-res.partner_<id>" the moment it changes.
    // Subscribing to the other party's channel keeps the Present/Absent
    // badge live with no polling.
    subscribeToPresence(partnerId) {
        if (this.presenceChannel) {
            this.busService.deleteChannel(this.presenceChannel);
            this.presenceChannel = null;
        }
        if (partnerId) {
            this.presenceChannel = `odoo-presence-res.partner_${partnerId}`;
            this.busService.addChannel(this.presenceChannel);
        }
    }

    onImStatusUpdated(payload) {
        if (this.state.otherParty && payload.partner_id === this.state.otherParty.partner_id) {
            this.state.otherParty.im_status = payload.im_status;
        }
    }

    onBusNotification(payload) {
        if (payload.ticket_id === this.resId) {
            ignoreDestroyedComponentError(this.loadChat());
        }
    }

    onTicketUpdated(payload) {
        // Someone (this user or the other party) changed the ticket's
        // stage elsewhere. Reload the whole record so the statusbar,
        // buttons and deadline field pick it up live; the resulting
        // onWillUpdateProps stage-change check reloads the chat itself
        // (composer/closed state) the same way a local save already does.
        if (payload.ticket_id === this.resId) {
            ignoreDestroyedComponentError(this.props.record.load());
        }
    }

    // ------------------------------------------------------------
    // Loading
    // ------------------------------------------------------------

    scrollToBottom() {
        const el = this.messagesRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    async loadChat(resId = this.resId) {
        if (!resId) {
            // New/unsaved ticket: never show a previously loaded ticket's chat.
            this.state.messages = [];
            this.state.canPost = false;
            this.state.isClosed = false;
            this.state.isUnsaved = true;
            this.state.loading = false;
            this.state.otherParty = null;
            this.state.unseen = 0;
            this.subscribeToPresence(null);
            return;
        }
        this.state.isUnsaved = false;
        this.state.loading = true;
        try {
            // Folded panel: the user has not actually read anything, so the
            // messages are fetched without clearing the unread bell.
            const markRead = !this.state.folded;
            const data = await this.orm.call("helpdesk_rk.ticket", "get_chat_thread_data", [
                [resId],
                markRead,
            ]);
            this.loadedAt = Date.now();
            this.state.messages = data.messages;
            this.state.canPost = data.can_post;
            this.state.isClosed = data.is_closed;
            this.state.otherParty = data.other_party;
            this.state.unseen = markRead ? 0 : data.unread_count;
            this.editWindowEndsAt = this.loadedAt + 1000 * Math.max(
                0,
                ...data.messages.map((message) => message.editable_seconds_left || 0)
            );
            if (this.state.editingId && !data.messages.some((m) => m.id === this.state.editingId)) {
                this.cancelEdit();
            }
            this.subscribeToPresence(data.other_party?.partner_id || null);
        } finally {
            this.state.loading = false;
        }
    }

    // ------------------------------------------------------------
    // Fold / unfold and dragging
    // ------------------------------------------------------------

    restoreDockState() {
        let stored = null;
        try {
            stored = JSON.parse(browser.localStorage.getItem(DOCK_STORAGE_KEY) || "null");
        } catch {
            stored = null;
        }
        this.state.folded = stored?.folded ?? true;
        this.state.position = stored?.position ?? null;
    }

    saveDockState() {
        try {
            browser.localStorage.setItem(
                DOCK_STORAGE_KEY,
                JSON.stringify({ folded: this.state.folded, position: this.state.position })
            );
        } catch {
            // Private browsing / storage disabled: the dock simply forgets
            // where it was left, which is not worth failing the widget over.
        }
    }

    get dockStyle() {
        const position = this.state.position;
        if (!position) {
            return "";
        }
        return `left:${position.x}px;top:${position.y}px;right:auto;bottom:auto;`;
    }

    clampToViewport() {
        const el = this.rootRef.el;
        if (!el || !this.state.position) {
            return;
        }
        const rect = el.getBoundingClientRect();
        this.setPosition(this.state.position.x, this.state.position.y, rect);
    }

    setPosition(x, y, rect = null) {
        const el = this.rootRef.el;
        const box = rect || el?.getBoundingClientRect();
        const width = box?.width || 0;
        const height = box?.height || 0;
        // window, not browser: browser.innerWidth is a snapshot taken when
        // the module loaded and never follows a resize.
        const maxX = Math.max(DOCK_MARGIN, window.innerWidth - width - DOCK_MARGIN);
        const maxY = Math.max(DOCK_MARGIN, window.innerHeight - height - DOCK_MARGIN);
        this.state.position = {
            x: Math.min(Math.max(x, DOCK_MARGIN), maxX),
            y: Math.min(Math.max(y, DOCK_MARGIN), maxY),
        };
    }

    onWindowResize() {
        this.clampToViewport();
    }

    toggleFold() {
        this.state.folded = !this.state.folded;
        this.saveDockState();
        if (!this.state.folded) {
            // Opening the panel is what counts as reading the conversation.
            ignoreDestroyedComponentError(this.loadChat());
        } else {
            this.cancelEdit();
        }
    }

    onLauncherClick() {
        // A drag that ends on the launcher must not also toggle it open.
        if (this.suppressClick) {
            this.suppressClick = false;
            return;
        }
        this.toggleFold();
    }

    onDragStart(ev) {
        if (ev.button !== 0 || ev.target.closest(".o_helpdesk_chat_no_drag")) {
            return;
        }
        const el = this.rootRef.el;
        if (!el) {
            return;
        }
        const rect = el.getBoundingClientRect();
        this.drag = {
            offsetX: ev.clientX - rect.left,
            offsetY: ev.clientY - rect.top,
            startX: ev.clientX,
            startY: ev.clientY,
            moved: false,
        };
        browser.addEventListener("pointermove", this.onDragMove);
        browser.addEventListener("pointerup", this.onDragEnd);
        browser.addEventListener("pointercancel", this.onDragEnd);
    }

    onDragMove(ev) {
        if (!this.drag) {
            return;
        }
        const travelled =
            Math.abs(ev.clientX - this.drag.startX) + Math.abs(ev.clientY - this.drag.startY);
        if (!this.drag.moved && travelled < DRAG_THRESHOLD) {
            return;
        }
        this.drag.moved = true;
        this.state.dragging = true;
        ev.preventDefault();
        this.setPosition(ev.clientX - this.drag.offsetX, ev.clientY - this.drag.offsetY);
    }

    onDragEnd() {
        const moved = this.drag?.moved;
        this.stopDragListeners();
        this.state.dragging = false;
        this.drag = null;
        if (moved) {
            // Only a drag that ended on the launcher has a click coming after
            // it to swallow; arming this after a titlebar drag would eat the
            // next legitimate click on the launcher instead.
            this.suppressClick = this.state.folded;
            this.saveDockState();
        }
    }

    stopDragListeners() {
        browser.removeEventListener("pointermove", this.onDragMove);
        browser.removeEventListener("pointerup", this.onDragEnd);
        browser.removeEventListener("pointercancel", this.onDragEnd);
    }

    get unseenLabel() {
        return this.state.unseen > 9 ? "9+" : String(this.state.unseen);
    }

    // ------------------------------------------------------------
    // Attachments
    // ------------------------------------------------------------

    onFileButtonClick(target) {
        this.uploadTarget = target;
        this.fileInputRef.el?.click();
    }

    async onFileChange(ev) {
        const files = [...ev.target.files];
        const target = this.uploadTarget;
        ev.target.value = "";
        for (const file of files) {
            await this.uploadFile(file, target);
        }
    }

    async uploadFile(file, target) {
        const formData = new FormData();
        formData.append("csrf_token", odoo.csrf_token);
        formData.append("ufile", file);
        formData.append("ticket_id", this.resId);
        try {
            const response = await browser.fetch("/helpdesk_rk/chat/upload_attachment", {
                method: "POST",
                body: formData,
            });
            const result = await response.json();
            if (result.error || !result.data) {
                this.notification.add(result.error || _t("Upload failed."), { type: "danger" });
                return;
            }
            if (target === "edit") {
                // Flagged unsent so that dropping it - or cancelling the whole
                // edit - deletes the upload again; the files already on the
                // message carry unsent:false and are only removed on save.
                this.state.editAttachments.push({ ...result.data, unsent: true });
            } else {
                this.state.pendingAttachments.push(result.data);
            }
        } catch {
            this.notification.add(_t("Upload failed."), { type: "danger" });
        }
    }

    async removePendingAttachment(id) {
        this.state.pendingAttachments = this.state.pendingAttachments.filter((a) => a.id !== id);
        await this.discardUnsentAttachment(id);
    }

    async removeEditAttachment(id) {
        const attachment = this.state.editAttachments.find((a) => a.id === id);
        this.state.editAttachments = this.state.editAttachments.filter((a) => a.id !== id);
        // Only files uploaded during this edit are unsent; the ones already
        // on the message are removed for good when the edit is saved.
        if (attachment && attachment.unsent) {
            await this.discardUnsentAttachment(id);
        }
    }

    async discardUnsentAttachment(id) {
        try {
            await rpc("/helpdesk_rk/chat/discard_attachment", { attachment_id: id });
        } catch {
            // A leftover unsent upload is harmless; never block the UI on it.
        }
    }

    formatSize(bytes) {
        if (!bytes) {
            return "";
        }
        if (bytes < 1024) {
            return `${bytes} B`;
        }
        if (bytes < 1024 * 1024) {
            return `${Math.round(bytes / 1024)} KB`;
        }
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    // ------------------------------------------------------------
    // Sending
    // ------------------------------------------------------------

    async onSend() {
        const body = this.state.draft.trim();
        const attachmentIds = this.state.pendingAttachments.map((a) => a.id);
        if (!body && !attachmentIds.length) {
            return;
        }
        this.state.sending = true;
        try {
            const data = await this.orm.call("helpdesk_rk.ticket", "post_chat_message", [
                [this.resId],
                body,
                attachmentIds,
            ]);
            this.applyThreadData(data);
            this.state.draft = "";
            this.state.pendingAttachments = [];
        } catch (e) {
            this.notification.add(e.data?.message || _t("Could not send message."), { type: "danger" });
        } finally {
            this.state.sending = false;
        }
    }

    applyThreadData(data) {
        this.loadedAt = Date.now();
        this.state.messages = data.messages;
        this.state.canPost = data.can_post;
        this.state.isClosed = data.is_closed;
        this.state.unseen = 0;
        this.editWindowEndsAt = this.loadedAt + 1000 * Math.max(
            0,
            ...data.messages.map((message) => message.editable_seconds_left || 0)
        );
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.onSend();
        }
    }

    // ------------------------------------------------------------
    // Editing / deleting my own messages
    // ------------------------------------------------------------

    onTick() {
        // Only re-render while a countdown is actually running; one extra
        // tick past the deadline makes the edit/delete buttons disappear.
        if (Date.now() <= this.editWindowEndsAt + 1000) {
            this.state.now = Date.now();
        }
    }

    remainingEditSeconds(message) {
        if (!message.is_own || this.state.isClosed) {
            return 0;
        }
        const elapsed = (this.state.now - this.loadedAt) / 1000;
        return Math.max((message.editable_seconds_left || 0) - elapsed, 0);
    }

    canModify(message) {
        return this.remainingEditSeconds(message) > 0;
    }

    remainingEditLabel(message) {
        const total = Math.ceil(this.remainingEditSeconds(message));
        const minutes = Math.floor(total / 60);
        const seconds = String(total % 60).padStart(2, "0");
        return `${minutes}:${seconds}`;
    }

    onEditStart(message) {
        this.state.editingId = message.id;
        this.state.editDraft = message.body;
        this.state.editAttachments = message.attachments.map((a) => ({ ...a, unsent: false }));
    }

    /** Cancel button / Escape: also bin anything uploaded during this edit. */
    async onEditCancel() {
        const unsent = this.state.editAttachments.filter((a) => a.unsent);
        this.cancelEdit();
        for (const attachment of unsent) {
            await this.discardUnsentAttachment(attachment.id);
        }
    }

    // Plain reset, used after a successful save - by then the files it was
    // holding belong to the message and must NOT be discarded.
    cancelEdit() {
        this.state.editingId = null;
        this.state.editDraft = "";
        this.state.editAttachments = [];
        this.state.editSaving = false;
    }

    onEditKeydown(ev, message) {
        if (ev.key === "Escape") {
            ev.preventDefault();
            this.onEditCancel();
        } else if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.onEditSave(message);
        }
    }

    async onEditSave(message) {
        const body = this.state.editDraft.trim();
        const attachmentIds = this.state.editAttachments.map((a) => a.id);
        if (!body && !attachmentIds.length) {
            this.notification.add(_t("A message cannot be left empty. Delete it instead."), {
                type: "warning",
            });
            return;
        }
        this.state.editSaving = true;
        try {
            const data = await this.orm.call("helpdesk_rk.ticket", "update_chat_message", [
                [this.resId],
                message.id,
                body,
                attachmentIds,
            ]);
            this.applyThreadData(data);
            this.cancelEdit();
        } catch (e) {
            this.notification.add(e.data?.message || _t("Could not update the message."), {
                type: "danger",
            });
        } finally {
            this.state.editSaving = false;
        }
    }

    onDeleteClick(message) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete message"),
            body: _t("This message and the files sent with it will be permanently deleted."),
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            confirm: () => this.deleteMessage(message),
            cancel: () => {},
        });
    }

    async deleteMessage(message) {
        try {
            const data = await this.orm.call("helpdesk_rk.ticket", "delete_chat_message", [
                [this.resId],
                message.id,
            ]);
            this.applyThreadData(data);
            if (this.state.editingId === message.id) {
                this.cancelEdit();
            }
        } catch (e) {
            this.notification.add(e.data?.message || _t("Could not delete the message."), {
                type: "danger",
            });
        }
    }

    // ------------------------------------------------------------
    // Header
    // ------------------------------------------------------------

    get otherPartyAvatarUrl() {
        const userId = this.state.otherParty?.user_id;
        return userId ? `/web/image/res.users/${userId}/avatar_128` : null;
    }

    get isOtherPartyPresent() {
        return ["online", "away"].includes(this.state.otherParty?.im_status);
    }

    get presenceLabel() {
        if (!this.state.otherParty?.user_id) {
            return "";
        }
        return this.isOtherPartyPresent ? _t("Present") : _t("Absent");
    }
}

export const ticketChat = {
    component: TicketChat,
};

registry.category("view_widgets").add("ticket_chat", ticketChat);
