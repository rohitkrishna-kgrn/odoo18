/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Component, useState, useRef, onWillStart, onWillUpdateProps, onMounted, onWillUnmount, useEffect } from "@odoo/owl";
import { ignoreDestroyedComponentError } from "../utils/silence_destroyed_error";

export class TicketChat extends Component {
    static template = "helpdesk_rk.TicketChat";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.busService = useService("bus_service");
        // Both come from the "mail" module, already loaded for the chatter;
        // used to place a real call through Odoo's own Discuss/RTC stack
        // instead of reinventing WebRTC signalling here.
        this.mailStore = useService("mail.store");
        this.rtc = useService("discuss.rtc");
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
            calling: false,
        });
        this.busChannel = null;
        this.presenceChannel = null;
        this.onBusNotification = this.onBusNotification.bind(this);
        this.onTicketUpdated = this.onTicketUpdated.bind(this);
        this.onImStatusUpdated = this.onImStatusUpdated.bind(this);

        onWillStart(() => this.loadChat());

        onMounted(() => this.subscribeToBus(this.resId));

        onWillUpdateProps((nextProps) => {
            const stageChanged = nextProps.record.data.stage_id !== this.props.record.data.stage_id;
            const recordChanged = nextProps.record.resId !== this.props.record.resId;
            if (recordChanged || stageChanged) {
                this.loadChat(nextProps.record.resId);
            }
            if (recordChanged) {
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
        });

        this.busService.subscribe("helpdesk_rk_chat_message", this.onBusNotification);
        this.busService.subscribe("helpdesk_rk_ticket_updated", this.onTicketUpdated);
        this.busService.subscribe("bus.bus/im_status_updated", this.onImStatusUpdated);

        useEffect(
            () => this.scrollToBottom(),
            () => [this.state.messages.length]
        );
    }

    get resId() {
        return this.props.record.resId;
    }

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
            this.subscribeToPresence(null);
            return;
        }
        this.state.isUnsaved = false;
        this.state.loading = true;
        try {
            const data = await this.orm.call("helpdesk_rk.ticket", "get_chat_thread_data", [[resId]]);
            this.state.messages = data.messages;
            this.state.canPost = data.can_post;
            this.state.isClosed = data.is_closed;
            this.state.otherParty = data.other_party;
            this.subscribeToPresence(data.other_party?.partner_id || null);
        } finally {
            this.state.loading = false;
        }
    }

    onFileButtonClick() {
        this.fileInputRef.el?.click();
    }

    async onFileChange(ev) {
        const files = [...ev.target.files];
        ev.target.value = "";
        for (const file of files) {
            await this.uploadFile(file);
        }
    }

    async uploadFile(file) {
        const formData = new FormData();
        formData.append("csrf_token", odoo.csrf_token);
        formData.append("ufile", file);
        formData.append("ticket_id", this.resId);
        try {
            const response = await fetch("/helpdesk_rk/chat/upload_attachment", {
                method: "POST",
                body: formData,
            });
            const result = await response.json();
            if (result.error || !result.data) {
                this.notification.add(result.error || _t("Upload failed."), { type: "danger" });
                return;
            }
            this.state.pendingAttachments.push(result.data);
        } catch {
            this.notification.add(_t("Upload failed."), { type: "danger" });
        }
    }

    removePendingAttachment(id) {
        this.state.pendingAttachments = this.state.pendingAttachments.filter((a) => a.id !== id);
    }

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
            this.state.messages = data.messages;
            this.state.canPost = data.can_post;
            this.state.isClosed = data.is_closed;
            this.state.draft = "";
            this.state.pendingAttachments = [];
        } catch (e) {
            this.notification.add(e.data?.message || _t("Could not send message."), { type: "danger" });
        } finally {
            this.state.sending = false;
        }
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.onSend();
        }
    }

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

    async onCallClick() {
        const partnerId = this.state.otherParty?.partner_id;
        if (!partnerId || this.state.calling) {
            return;
        }
        this.state.calling = true;
        try {
            const chat = await this.mailStore.getChat({ partnerId });
            if (!chat) {
                return;
            }
            chat.open();
            await this.rtc.toggleCall(chat, { audio: true });
        } catch {
            this.notification.add(_t("Could not start the call."), { type: "danger" });
        } finally {
            this.state.calling = false;
        }
    }
}

export const ticketChat = {
    component: TicketChat,
};

registry.category("view_widgets").add("ticket_chat", ticketChat);
