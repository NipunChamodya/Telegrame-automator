import SwiftUI
import AppKit

struct AccountsView: View {
    @ObservedObject var model: AppModel
    @State private var label = ""
    @State private var pending: AccountProfile?
    @State private var action = ""
    @State private var confirmation = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageHeader(title: "Accounts", subtitle: "Each account has its own session, groups, drafts, approvals, and delivery ledger.", symbol: "person.crop.circle.badge.checkmark")
            HStack { TextField("New account label", text: $label); Button("Add Account") { model.addProfile(label: label); label = "" }.disabled(!model.backendOnline || model.busy || label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty).accessibilityIdentifier("addAccount") }
            List(model.profiles) { profile in
                HStack {
                    Image(systemName: profile.active ? "person.crop.circle.fill.badge.checkmark" : "person.crop.circle").font(.title2).foregroundStyle(.blue)
                    VStack(alignment: .leading) { Text(profile.title).font(.headline); Text("\(profile.accountID) · \(profile.state)\(profile.legacy ? " · Original installation" : "")").font(.caption).foregroundStyle(.secondary) }
                    Spacer()
                    if profile.active { Text("Active").font(.caption.bold()); Button("Disconnect") { pending = profile; action = "disconnect" } }
                    else if !profile.archived { Button("Switch") { model.switchProfile(profile) } }
                    Menu("Manage") {
                        if profile.active { Button("Log Out of Telegram…", role: .destructive) { pending = profile; action = "logout" } }
                        if !profile.legacy { Button("Remove Local Account…", role: .destructive) { pending = profile; action = "remove" } }
                        if profile.archived { Button("Restore Profile") { model.manageProfile(profile, action: "restore") } }
                    }
                }.padding(.vertical, 8).disabled(model.busy || !model.backendOnline)
            }.overlay {
                if model.profiles.isEmpty {
                    ContentUnavailableView(model.backendOnline ? "No saved accounts" : "Account manager is offline", systemImage: "person.crop.circle", description: Text(model.backendOnline ? "Add an account above to begin secure Telegram setup." : "Use Retry Connection to load your saved account profiles."))
                }
            }.accessibilityIdentifier("accountList")
        }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .sheet(item: $pending) { profile in
            VStack(alignment: .leading, spacing: 18) {
                Text(action == "remove" ? "Remove Local Account" : action == "logout" ? "Log Out of Telegram" : "Disconnect Account").font(.title2.bold())
                Text(profile.title)
                Text(action == "remove" ? "This permanently removes this profile’s local session, database, drafts, delivery history, approvals, and Keychain credential. Other accounts are preserved. This does not log out the session on Telegram’s servers." : action == "logout" ? "This revokes this selected Telegram session. Local records are preserved. Reconnecting will require authentication." : "This closes the local connection. The session and all records remain available.")
                if action != "disconnect" {
                    Text("Type exactly: \(profile.data[action == "logout" ? "logout_confirmation" : "remove_confirmation"].string)").textSelection(.enabled)
                    TextField("Confirmation phrase", text: $confirmation).textFieldStyle(.roundedBorder).accessibilityIdentifier("accountActionConfirmation")
                }
                HStack { Button("Cancel") { pending = nil; confirmation = "" }; Spacer(); Button("Confirm", role: .destructive) { model.manageProfile(profile, action: action, confirmation: confirmation); pending = nil; confirmation = "" }.disabled(action != "disconnect" && confirmation != profile.data[action == "logout" ? "logout_confirmation" : "remove_confirmation"].string) }
            }.padding(28).frame(width: 550)
        }
    }
}

struct ChatsView: View {
    @ObservedObject var model: AppModel
    var detailOnly = false
    @State private var messageSearch = ""
    @State private var showConversation = false
    private enum Field: Hashable { case search, composer }
    @FocusState private var focusedField: Field?
    @State private var windowFocused = false
    @State private var historySize = CGSize.zero
    @State private var legacyVisibleIDs: Set<Int> = []
    private var automaticReadSupported: Bool { if #available(macOS 15.0, *) { return true }; return false }
    private var focusedChat: ChatSummary? {
        guard let chat = model.selectedChat else { return nil }
        if model.screen == .channels && chat.kind != "channel" { return nil }
        if model.screen == .groupChats && !["group", "supergroup"].contains(chat.kind) { return nil }
        return chat
    }

    var body: some View {
        GeometryReader { geometry in
            let wide = geometry.size.width >= 800
            Group {
                if detailOnly {
                    conversationDetail(height: geometry.size.height, compact: false)
                } else if wide {
                    HStack(spacing: 0) {
                        conversationList.frame(width: min(360, max(300, geometry.size.width * 0.32)))
                        Divider()
                        conversationDetail(height: geometry.size.height, compact: false)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                } else if showConversation && focusedChat != nil {
                    conversationDetail(height: geometry.size.height, compact: true)
                } else {
                    conversationList
                }
            }
            .frame(width: geometry.size.width, height: geometry.size.height, alignment: .topLeading)
        }
        .background(NativeWindowFocusReader(focused: $windowFocused).frame(width: 0, height: 0))
        .sheet(item: $model.messageActionTarget, onDismiss: { model.closeMessageAction(force: true) }) { target in MessageActionSheet(model: model, context: target) }
        .accessibilityIdentifier("chatsScreen")
        .onChange(of: windowFocused) { _, value in model.setConversationFocused(value && focusedChat != nil, automaticRead: automaticReadSupported) }
        .onChange(of: focusedField) { _, value in if value != .composer { model.stopConversationTyping() } }
        .onDisappear { model.setConversationFocused(false) }
        .onAppear { showConversation = focusedChat != nil; fulfillComposerFocus() }
        .onChange(of: model.composerFocusRequested) { _, _ in fulfillComposerFocus() }
        .onChange(of: model.screen) { _, _ in showConversation = focusedChat != nil; messageSearch = "" }
        .onChange(of: focusedChat?.contentAvailable) { _, _ in model.setConversationFocused(windowFocused && focusedChat != nil, automaticRead: automaticReadSupported) }
        .onChange(of: model.selectedChat?.id) { _, id in if id != nil { showConversation = true }; messageSearch = ""; model.setConversationFocused(windowFocused && focusedChat != nil, automaticRead: automaticReadSupported) }
    }

    private func fulfillComposerFocus() {
        guard model.composerFocusRequested else { return }
        focusedField = focusedChat?.allowsPersonalSend == true ? .composer : .search
        model.composerFocusRequested = false
    }
    private var conversationList: some View {
        VStack(spacing: 0) {
            VStack(spacing: 10) {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                    TextField("Search conversations", text: $model.chatQuery)
                        .focused($focusedField, equals: .search)
                        .textFieldStyle(.plain).accessibilityIdentifier("conversationSearch")
                        .onSubmit { Task { model.chatPage = 0; await model.loadChats() } }
                    if !model.chatQuery.isEmpty { Button { model.chatQuery = "" } label: { Image(systemName: "xmark.circle.fill") }.buttonStyle(.plain).foregroundStyle(.secondary).help("Clear search") }
                }.padding(9).background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
                HStack {
                    Menu {
                        Picker("Conversation type", selection: $model.chatKind) {
                            ForEach(model.screen == .groupChats ? ["groups", "group", "supergroup"] : model.screen == .channels ? ["channel"] : ["all", "private", "groups", "group", "supergroup", "channel", "saved"], id: \.self) { Text($0.capitalized).tag($0) }
                        }
                    } label: { Label(model.chatKind == "all" ? "All conversations" : model.chatKind.capitalized, systemImage: "line.3.horizontal.decrease") }
                    Spacer()
                    if model.chatsLoading { ProgressView().controlSize(.small).accessibilityLabel("Loading cached conversations") }
                    Menu {
                        Button("Refresh Conversations") { model.refreshChats() }.disabled(!model.connected || model.busy)
                        Button("Telegram Folders…") { model.foldersPresented = true }
                        Button("Saved Messages") { model.openSavedMessages(); showConversation = true }.disabled(!model.connected || model.busy)
                        if model.chatRefreshCursor != nil { Button("Load Older Dialogs") { model.refreshChats(older: true) }.disabled(!model.connected || model.busy) }
                    } label: { Image(systemName: "ellipsis.circle") }.menuStyle(.borderlessButton).fixedSize().help("Conversation actions").accessibilityLabel("Conversation actions")
                }
            }.padding(14)
            CachedReadStatus(model: model, screen: model.screen == .channels ? .channels : model.screen == .groupChats ? .groupChats : .chats, retry: { Task { await model.loadChats() } }).padding(.horizontal, 14)
            Divider()
            List(selection: Binding<Int?>(get: { focusedChat?.id }, set: { id in
                if let id, let chat = model.chats.first(where: { $0.id == id }) { model.selectChat(chat); showConversation = true }
            })) {
                ForEach(model.chats) { chat in
                    conversationRow(chat).tag(chat.id).accessibilityIdentifier("chatRow_\(chat.id)")
                }
            }
            .listStyle(.inset)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .accessibilityIdentifier("conversationList")
            .overlay {
                if model.chats.isEmpty && !model.chatsLoading {
                    ContentUnavailableView("No conversations", systemImage: "bubble.left.and.bubble.right", description: Text(model.chatQuery.isEmpty ? "Choose Refresh in the actions menu to retrieve conversations." : "Try another search or conversation type."))
                }
            }
            Divider()
            HStack {
                Button { model.chatPage -= 1; Task { await model.loadChats() } } label: { Image(systemName: "chevron.left") }.disabled(model.chatPage == 0 || model.chatsLoading).help("Previous page").accessibilityLabel("Previous")
                Spacer()
                Text("\(model.chatTotal) cached · Page \(model.chatPage + 1)").font(.caption).foregroundStyle(.secondary).lineLimit(1)
                Spacer()
                Button { model.chatPage += 1; Task { await model.loadChats() } } label: { Image(systemName: "chevron.right") }.disabled((model.chatPage + 1) * model.pageSize >= model.chatTotal || model.chatsLoading).help("Next page").accessibilityLabel("Next")
            }.padding(.horizontal, 14).padding(.vertical, 10).accessibilityIdentifier("conversationPagination")
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .onChange(of: model.chatQuery) { _, _ in model.scheduleChatSearch() }
        .onChange(of: model.chatKind) { _, _ in Task { model.chatPage = 0; await model.loadChats() } }
    }

    private func conversationRow(_ chat: ChatSummary) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: chat.kind == "private" ? "person.crop.circle.fill" : chat.kind == "saved" ? "bookmark.circle.fill" : "person.2.circle.fill")
                .font(.system(size: 32)).foregroundStyle(.blue).frame(width: 36)
            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline) {
                    Text(chat.title).font(.body.weight(.semibold)).lineLimit(1)
                    Spacer(minLength: 4)
                    if chat.data["unread_count"].int > 0 {
                        Text(chat.data["unread_count"].int > 999 ? "999+" : String(chat.data["unread_count"].int))
                            .font(.caption2.bold()).padding(.horizontal, 6).padding(.vertical, 2)
                            .background(.blue, in: Capsule()).foregroundStyle(.white)
                            .accessibilityLabel("\(chat.data["unread_count"].int) unread messages")
                    }
                }
                Text(chat.kind == "channel" ? "Channel identity · content unavailable" : chat.lastMessage.isEmpty ? chat.kind.capitalized : chat.lastMessage).font(.callout).foregroundStyle(.secondary).lineLimit(2)
                Text(displayDate(chat.data["last_date"])).font(.caption2).foregroundStyle(.tertiary).lineLimit(1)
            }
        }.padding(.vertical, 8).frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle()).help(chat.title)
    }

    @ViewBuilder private func conversationDetail(height: CGFloat, compact: Bool) -> some View {
        if let chat = focusedChat, !chat.contentAvailable {
            VStack(alignment: .leading, spacing: 18) {
                if compact { Button { showConversation = false } label: { Label("Conversations", systemImage: "chevron.left") }.accessibilityIdentifier("backToConversations") }
                PageHeader(title: chat.title, subtitle: "Cached identity", symbol: "info.bubble")
                LabeledContent("Telegram ID", value: String(chat.id)).textSelection(.enabled)
                LabeledContent("Username", value: chat.data["username"].string.isEmpty ? "Unavailable" : "@" + chat.data["username"].string)
                Label(chat.contentReason, systemImage: "info.circle").foregroundStyle(.secondary)
                Text("Cached identity only. Refresh conversations to update supported metadata; unavailable content is not requested.").font(.caption).foregroundStyle(.secondary)
                Button("Refresh Conversations") { model.refreshChats() }.disabled(!model.connected || model.busy)
                Spacer()
            }.padding(22).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).accessibilityIdentifier("channelMetadataOnly")
        } else if let chat = focusedChat {
            VStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 10) {
                    if compact {
                        Button { showConversation = false } label: { Label("Conversations", systemImage: "chevron.left") }.buttonStyle(.plain).foregroundStyle(.blue).accessibilityIdentifier("backToConversations")
                    }
                    HStack {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(chat.title).font(.title3.weight(.semibold)).lineLimit(2).textSelection(.enabled)
                            Text("\(chat.kind.capitalized) · \(chat.id) · Account \(model.accountID)").font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                            if !model.typingDescription.isEmpty { Text(model.typingDescription).font(.caption).foregroundStyle(.tint) }
                        }
                        Spacer()
                        Button { model.showProfile(chat.id) } label: { Image(systemName: "person.crop.circle") }.disabled(!model.connected || model.busy).help("View profile")
                        if model.messagesLoading { ProgressView().controlSize(.small).accessibilityLabel("Loading messages") }
                        Button { Task { await model.loadMessages() } } label: { Image(systemName: "arrow.clockwise") }.disabled(!model.connected || model.busy || model.messagesLoading).help("Refresh messages")
                    }
                    HStack(spacing: 8) {
                        TextField("Search Telegram messages", text: $messageSearch).textFieldStyle(.roundedBorder).onSubmit { if !model.messagesLoading { Task { await model.loadMessages(search: messageSearch) } } }
                        Button { Task { await model.loadMessages(search: messageSearch) } } label: { Image(systemName: "magnifyingglass") }.disabled(!model.connected || model.busy || model.messagesLoading).help("Search messages")
                    }
                }.padding(16)
                if model.liveRepairNeeded {
                    HStack { Label(model.liveMessage, systemImage: "arrow.triangle.2.circlepath").font(.caption); Spacer(); Button("Refresh Updates") { model.repairLiveUpdates() } }.padding(10).background(.orange.opacity(0.08))
                }
                if !model.chatMessages.isEmpty, let error = model.messagesError {
                    Label(error, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.red).padding(10)
                }
                Divider()
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        if model.hasMoreMessages { Button("Load Older Messages") { Task { await model.loadMessages(older: true) } }.disabled(!model.connected || model.busy || model.messagesLoading).frame(maxWidth: .infinity) }
                        ForEach(model.chatMessages.sorted { $0.id < $1.id }) { message in observedMessageRow(message, chat: chat) }

                    }.padding(16).frame(maxWidth: .infinity)
                }.coordinateSpace(name: "conversationHistoryViewport")
                .background(GeometryReader { geometry in Color.clear.onAppear { historySize = geometry.size }.onChange(of: geometry.size) { _, size in historySize = size } })
                .onPreferenceChange(MessageFramePreference.self) { frames in
                    guard !automaticReadSupported else { return }
                    let viewport = CGRect(origin: .zero, size: historySize)
                    let visible = Set(frames.filter { _, frame in Self.visibleFraction(frame, viewport: viewport) >= 0.5 }.map(\.key))
                    for id in legacyVisibleIDs.subtracting(visible) { model.messageVisibilityChanged(id: id, peer: chat.id, incoming: true, visible: false) }
                    for id in visible { model.messageVisibilityChanged(id: id, peer: chat.id, incoming: true, visible: true) }
                    legacyVisibleIDs = visible
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity).accessibilityIdentifier("conversationHistory")
                .overlay {
                    if model.chatMessages.isEmpty {
                        if model.messagesLoading { LoadingStateView(title: "Loading conversation…").accessibilityIdentifier("messagesLoading") }
                        else if let error = model.messagesError {
                            ErrorStateView(title: "Messages could not be loaded", message: error, retry: model.connected ? { Task { await model.loadMessages() } } : nil)
                                .accessibilityIdentifier("messagesError")
                        } else {
                            EmptyStateView(title: model.connected ? "No messages in this view" : "Connect to load messages", symbol: "bubble.left", description: model.connected ? "Refresh this conversation or change your search. Unsupported content remains unavailable." : "Cached identity is available offline. Restore this account’s session to retrieve supported history.", actionTitle: model.connected ? "Refresh Messages" : nil, action: model.connected ? { Task { await model.loadMessages() } } : nil)
                        }
                    }
                }
                if #unavailable(macOS 15.0) {
                    HStack { Text("Read status updates only when you choose this action.").font(.caption).foregroundStyle(.secondary); Spacer(); Button("Mark Displayed Messages Read") { model.markDisplayedConversationRead() }.disabled(!model.connected || !windowFocused || legacyVisibleIDs.isEmpty) }.padding(10)
                }
                Divider()
                if chat.allowsPersonalSend {
                    personalComposer(chat).frame(height: min(model.chatPreview == nil ? 205 : 340, max(150, height * (model.chatPreview == nil ? 0.4 : 0.58))))
                } else {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Group messages require explicit destination approval.", systemImage: "checkmark.shield").font(.callout)
                        Button("Open Managed Composer") { model.screen = .composer }
                    }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top).accessibilityIdentifier("conversationDetail")
        } else {
            ContentUnavailableView("Select a conversation", systemImage: "bubble.left.and.bubble.right", description: Text("Cached conversations appear immediately. Refresh explicitly to retrieve Telegram dialogs.")).frame(maxWidth: .infinity, maxHeight: .infinity).accessibilityIdentifier("conversationDetail")
        }
    }

    @ViewBuilder private func observedMessageRow(_ message: ChatMessage, chat: ChatSummary) -> some View {
        if #available(macOS 15.0, *) {
            messageRow(message, chat: chat).onScrollVisibilityChange(threshold: 0.5) { visible in
                model.messageVisibilityChanged(id: message.id, peer: chat.id, incoming: !message.outgoing && message.contentAvailable, visible: visible)
            }.onDisappear { model.messageVisibilityChanged(id: message.id, peer: chat.id, incoming: !message.outgoing && message.contentAvailable, visible: false) }
        } else {
            messageRow(message, chat: chat).background(GeometryReader { geometry in
                Color.clear.preference(key: MessageFramePreference.self, value: !message.outgoing && message.contentAvailable ? [message.id: geometry.frame(in: .named("conversationHistoryViewport"))] : [:])
            })
        }
    }
    static func visibleFraction(_ frame: CGRect, viewport: CGRect) -> CGFloat {
        guard frame.width > 0, frame.height > 0, frame.width.isFinite, frame.height.isFinite else { return 0 }
        let intersection = frame.intersection(viewport)
        guard !intersection.isNull, !intersection.isEmpty else { return 0 }
        return (intersection.width * intersection.height) / (frame.width * frame.height)
    }
    private func messageRow(_ message: ChatMessage, chat: ChatSummary) -> some View {
        HStack {
            if message.outgoing { Spacer(minLength: 30) }
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline) {
                    Text(message.sender).font(.caption.weight(.semibold)).lineLimit(1)
                    Spacer(minLength: 6)
                    Text(displayDate(message.data["date"])).font(.caption2).foregroundStyle(.secondary)
                    if chat.allowsPersonalSend { Button { model.chatReply = message.id; model.invalidateChatPreview() } label: { Image(systemName: "arrowshape.turn.up.left") }.buttonStyle(.borderless).disabled(model.busy).help("Reply to this message") }
                }
                if message.contentAvailable {
                    if let reply = message.replyID { Label("Reply to message \(reply)", systemImage: "arrowshape.turn.up.left").font(.caption).foregroundStyle(.secondary) }
                    if let forwarded = message.forwarded {
                        Label(forwarded["name"].string.isEmpty ? "Forwarded message" : "Forwarded from " + safeDisplay(forwarded["name"].string), systemImage: "arrowshape.turn.up.right").font(.caption).foregroundStyle(.secondary)
                    }
                    if message.pinned { Label("Pinned", systemImage: "pin").font(.caption).foregroundStyle(.secondary) }
                    Text(MessagePresentation.attributed(message)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                    if !message.reactions.isEmpty {
                        HStack { ForEach(message.reactions) { reaction in Text("\(reaction.emoji.isEmpty ? "Custom reaction" : reaction.emoji) \(reaction.count)").font(.caption).padding(.horizontal, 7).padding(.vertical, 3).background(reaction.chosen ? Color.accentColor.opacity(0.14) : Color.secondary.opacity(0.09), in: Capsule()) } }
                    }
                    HStack {
                        if message.edited { Text("Edited").font(.caption2).foregroundStyle(.secondary) }
                        if message.outgoing, let frontier = model.liveProjection?.readOutboxMaxID, message.id <= frontier { Label("Read", systemImage: "checkmark.circle").font(.caption2).foregroundStyle(.secondary) }
                    }
                } else { Text("Content unavailable").foregroundStyle(.secondary) }
                if message.hasAttachment && message.contentAvailable { HStack { Label(message.data["media"]["kind"].string, systemImage: "paperclip"); if message.data["media"]["kind"].string == "image" || ["image/jpeg", "image/png"].contains(message.data["media"]["mime_type"].string) { Button("Preview Image") { model.openMediaPreview(message) }.disabled(model.busy) }; Button("Save Attachment…") { model.downloadAttachment(message) }.disabled(model.busy) }.font(.caption) }
            }.padding(12).background(message.outgoing ? Color.blue.opacity(0.09) : Color.secondary.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
            if !message.outgoing { Spacer(minLength: 30) }
        }
        .contextMenu {
            if message.contentAvailable {
                Button("Copy Text", systemImage: "doc.on.doc") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(message.text, forType: .string) }
                if chat.allowsPersonalSend {
                    Button("Reply", systemImage: "arrowshape.turn.up.left") { model.chatReply = message.id; model.invalidateChatPreview() }.disabled(model.busy)
                    if message.canRequestEdit { Button("Edit Message…", systemImage: "pencil") { model.beginMessageAction("edit", message: message) } }
                    if message.canRequestDelete { Button("Delete for Me…", systemImage: "trash", role: .destructive) { model.beginMessageAction("delete", message: message) } }
                }
            }
        }
    }

    private func personalComposer(_ chat: ChatSummary) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 9) {
                if let reply = model.chatReply {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 4) {
                            Label("Replying to message \(reply)", systemImage: "arrowshape.turn.up.left").font(.caption.weight(.medium))
                            if let original = model.chatMessages.first(where: { $0.id == reply }), original.contentAvailable { Text(original.text).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                        }
                        Spacer(); Button("Clear Reply") { model.chatReply = nil; model.invalidateChatPreview() }
                    }
                }
                TextEditor(text: Binding(get: { model.chatDraft }, set: { model.userEditedConversation($0, focused: windowFocused && focusedField == .composer) })).focused($focusedField, equals: .composer).font(.body).padding(5).frame(height: 84)
                    .background(.background).overlay(RoundedRectangle(cornerRadius: 8).stroke(.quaternary))
                    .accessibilityIdentifier("chatComposer")
                HStack {
                    Text("\(model.chatDraft.utf16.count) / 4096").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("Save Draft") { model.saveChatDraft() }.disabled(model.busy)
                    Button("Preview") { model.prepareChatPreview() }.disabled(!model.chatCanPreview)
                }
                if let error = ComposerValidation.error(model.chatDraft), !model.chatDraft.isEmpty { Text(error).font(.caption).foregroundStyle(.orange) }
                if let preview = model.chatPreview {
                    GroupBox {
                        VStack(alignment: .leading, spacing: 9) {
                            Text("From \(model.accountName) (\(model.accountID)) to \(chat.title) · \(chat.id)").font(.caption.weight(.medium))
                            ScrollView { Text(preview["message"].string).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }.frame(minHeight: 40, maxHeight: 80)
                            TextField("Type \(preview["confirmation"].string) to confirm", text: $model.chatConfirmation).textFieldStyle(.roundedBorder)
                            Button("Send One Message") { model.sendChatConfirmed() }.disabled(!model.chatCanSend).buttonStyle(.borderedProminent)
                        }
                    }
                }
            }.padding(14)
        }.accessibilityIdentifier("conversationComposer")
    }
}

struct DraftsView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageHeader(title: "Drafts", subtitle: "Local composition saved separately for each account and conversation.", symbol: "doc.text")
            CachedReadStatus(model: model, screen: .drafts, retry: { Task { await model.loadChatDrafts() } })
            Button("Open Managed Message Draft") { model.screen = .composer }
            List(Array(model.chatDrafts.enumerated()), id: \.offset) { _, draft in
                HStack { VStack(alignment: .leading) { Text(safeDisplay(draft["title"].string)).font(.headline); Text(safeDisplay(draft["message"].string)).lineLimit(2); Text(displayDate(draft["updated_at"])).font(.caption).foregroundStyle(.secondary) }; Spacer(); Button("Open") { model.selectChat(model.chats.first { $0.id == draft["destination"].int } ?? ChatSummary(data: .object(["id": draft["destination"], "name": draft["title"], "kind": .string("unknown")]))); model.screen = .chats }; Button("Delete Draft", role: .destructive) { model.deleteChatDraft(draft["destination"].int) } }
            }
            .overlay {
                if model.chatDrafts.isEmpty { ContentUnavailableView("No conversation drafts", systemImage: "doc.text", description: Text("Open a personal conversation and compose a message. Local drafts are saved automatically; sending always needs confirmation.")) }
            }
            Text("Drafts belong to the active account. Switching accounts saves your current composition first.").font(.caption).foregroundStyle(.secondary)
        }.padding(24)
    }
}

private func displayDate(_ value: JSONValue) -> String {
    if value.doubleValue > 0 { return Date(timeIntervalSince1970: value.doubleValue).formatted(date: .abbreviated, time: .shortened) }
    return value.string.isEmpty ? "" : readableTime(safeDisplay(value.string))
}

private struct NativeWindowFocusReader: NSViewRepresentable {
    @Binding var focused: Bool
    func makeNSView(context: Context) -> FocusReportingView {
        let view = FocusReportingView()
        view.changed = { value in if focused != value { focused = value } }
        return view
    }
    func updateNSView(_ view: FocusReportingView, context: Context) { view.reportFocus() }
    static func dismantleNSView(_ view: FocusReportingView, coordinator: ()) { view.stopObserving() }
}

private final class FocusReportingView: NSView {
    var changed: ((Bool) -> Void)?
    private var observations: [NSObjectProtocol] = []
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow(); stopObserving()
        for name in [NSWindow.didBecomeKeyNotification, NSWindow.didResignKeyNotification, NSApplication.didBecomeActiveNotification, NSApplication.didResignActiveNotification] {
            observations.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor [weak self] in self?.reportFocus() }
            })
        }
        reportFocus()
    }
    func reportFocus() {
        let value = window?.isKeyWindow == true && NSApp.isActive
        DispatchQueue.main.async { [weak self] in self?.changed?(value) }
    }
    func stopObserving() {
        for observer in observations { NotificationCenter.default.removeObserver(observer) }
        observations = []
    }
}

private struct MessageFramePreference: PreferenceKey {
    static let defaultValue: [Int: CGRect] = [:]
    static func reduce(value: inout [Int: CGRect], nextValue: () -> [Int: CGRect]) { value.merge(nextValue(), uniquingKeysWith: { _, newer in newer }) }
}
