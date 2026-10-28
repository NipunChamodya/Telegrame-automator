import SwiftUI

struct AccountsView: View {
    @ObservedObject var model: AppModel
    @State private var label = ""
    @State private var pending: AccountProfile?
    @State private var action = ""
    @State private var confirmation = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Accounts").font(.largeTitle.bold())
            Text("Each account has its own session, groups, drafts, approvals, and delivery ledger.").foregroundStyle(.secondary)
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
        }.padding(24)
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
    @State private var messageSearch = ""
    @State private var showConversation = false

    var body: some View {
        GeometryReader { geometry in
            let wide = geometry.size.width >= 800
            Group {
                if wide {
                    HStack(spacing: 0) {
                        conversationList.frame(width: min(360, max(300, geometry.size.width * 0.32)))
                        Divider()
                        conversationDetail(height: geometry.size.height, compact: false)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                } else if showConversation && model.selectedChat != nil {
                    conversationDetail(height: geometry.size.height, compact: true)
                } else {
                    conversationList
                }
            }
            .frame(width: geometry.size.width, height: geometry.size.height, alignment: .topLeading)
        }
        .accessibilityIdentifier("chatsScreen")
        .onAppear { showConversation = model.selectedChat != nil }
        .onChange(of: model.selectedChat?.id) { _, id in if id != nil { showConversation = true }; messageSearch = "" }
    }

    private var conversationList: some View {
        VStack(spacing: 0) {
            VStack(spacing: 10) {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                    TextField("Search conversations", text: $model.chatQuery)
                        .textFieldStyle(.plain).accessibilityIdentifier("conversationSearch")
                        .onSubmit { Task { model.chatPage = 0; await model.loadChats() } }
                    if !model.chatQuery.isEmpty { Button { model.chatQuery = "" } label: { Image(systemName: "xmark.circle.fill") }.buttonStyle(.plain).foregroundStyle(.secondary).help("Clear search") }
                }.padding(9).background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
                HStack {
                    Menu {
                        Picker("Conversation type", selection: $model.chatKind) {
                            ForEach(["all", "private", "group", "supergroup", "channel", "saved"], id: \.self) { Text($0.capitalized).tag($0) }
                        }
                    } label: { Label(model.chatKind == "all" ? "All conversations" : model.chatKind.capitalized, systemImage: "line.3.horizontal.decrease") }
                    Spacer()
                    if model.chatsLoading { ProgressView().controlSize(.small).accessibilityLabel("Loading cached conversations") }
                    Menu {
                        Button("Refresh Conversations") { model.refreshChats() }.disabled(!model.connected || model.busy)
                        Button("Saved Messages") { model.openSavedMessages(); showConversation = true }.disabled(!model.connected || model.busy)
                        if model.chatRefreshCursor != nil { Button("Load Older Dialogs") { model.refreshChats(older: true) }.disabled(!model.connected || model.busy) }
                    } label: { Image(systemName: "ellipsis.circle") }.menuStyle(.borderlessButton).fixedSize().help("Conversation actions").accessibilityLabel("Conversation actions")
                }
            }.padding(14)
            Divider()
            List(selection: Binding<Int?>(get: { model.selectedChat?.id }, set: { id in
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
                Text(chat.lastMessage.isEmpty ? chat.kind.capitalized : chat.lastMessage).font(.callout).foregroundStyle(.secondary).lineLimit(2)
                Text(displayDate(chat.data["last_date"])).font(.caption2).foregroundStyle(.tertiary).lineLimit(1)
            }
        }.padding(.vertical, 8).frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle()).help(chat.title)
    }

    @ViewBuilder private func conversationDetail(height: CGFloat, compact: Bool) -> some View {
        if let chat = model.selectedChat {
            VStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 10) {
                    if compact {
                        Button { showConversation = false } label: { Label("Conversations", systemImage: "chevron.left") }.buttonStyle(.plain).foregroundStyle(.blue).accessibilityIdentifier("backToConversations")
                    }
                    HStack {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(chat.title).font(.title3.weight(.semibold)).lineLimit(2).textSelection(.enabled)
                            Text("\(chat.kind.capitalized) · \(chat.id)").font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                        }
                        Spacer()
                        if model.messagesLoading { ProgressView().controlSize(.small).accessibilityLabel("Loading messages") }
                        Button { Task { await model.loadMessages() } } label: { Image(systemName: "arrow.clockwise") }.disabled(!model.connected || model.busy || model.messagesLoading).help("Refresh messages")
                    }
                    HStack(spacing: 8) {
                        TextField("Search Telegram messages", text: $messageSearch).textFieldStyle(.roundedBorder).onSubmit { if !model.messagesLoading { Task { await model.loadMessages(search: messageSearch) } } }
                        Button { Task { await model.loadMessages(search: messageSearch) } } label: { Image(systemName: "magnifyingglass") }.disabled(!model.connected || model.busy || model.messagesLoading).help("Search messages")
                    }
                }.padding(16)
                Divider()
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        if model.hasMoreMessages { Button("Load Older Messages") { Task { await model.loadMessages(older: true) } }.disabled(!model.connected || model.busy || model.messagesLoading).frame(maxWidth: .infinity) }
                        ForEach(model.chatMessages.sorted { $0.id < $1.id }) { message in messageRow(message, chat: chat) }
                        if model.chatMessages.isEmpty && !model.messagesLoading { ContentUnavailableView("No messages loaded", systemImage: "bubble.left", description: Text("Use Refresh to retrieve this conversation’s history.")) }
                    }.padding(16).frame(maxWidth: .infinity)
                }.frame(maxWidth: .infinity, maxHeight: .infinity).accessibilityIdentifier("conversationHistory")
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
                Text(message.text).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                if message.hasAttachment { HStack { Label(message.data["media"]["kind"].string, systemImage: "paperclip"); Button("Save Attachment…") { model.downloadAttachment(message) }.disabled(model.busy) }.font(.caption) }
            }.padding(12).background(message.outgoing ? Color.blue.opacity(0.09) : Color.secondary.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
            if !message.outgoing { Spacer(minLength: 30) }
        }
    }

    private func personalComposer(_ chat: ChatSummary) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 9) {
                if let reply = model.chatReply { HStack { Text("Replying to message \(reply)").font(.caption); Button("Clear Reply") { model.chatReply = nil; model.invalidateChatPreview() } } }
                TextEditor(text: $model.chatDraft).font(.body).padding(5).frame(height: 84)
                    .background(.background).overlay(RoundedRectangle(cornerRadius: 8).stroke(.quaternary))
                    .onChange(of: model.chatDraft) { _, _ in model.invalidateChatPreview(); model.scheduleChatDraftSave() }.accessibilityIdentifier("chatComposer")
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
            Text("Drafts").font(.largeTitle.bold())
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
