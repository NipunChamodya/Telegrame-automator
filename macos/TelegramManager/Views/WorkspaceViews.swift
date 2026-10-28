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
    @State private var localLabel = ""
    var body: some View {
        HSplitView {
            VStack(spacing: 12) {
                TextField("Search cached conversations", text: $model.chatQuery).textFieldStyle(.roundedBorder).accessibilityIdentifier("conversationSearch").onSubmit { Task { model.chatPage = 0; await model.loadChats() } }
                Picker("Kind", selection: $model.chatKind) { ForEach(["all", "private", "group", "supergroup", "channel", "saved"], id: \.self) { Text($0.capitalized).tag($0) } }.onChange(of: model.chatKind) { _, _ in Task { model.chatPage = 0; await model.loadChats() } }
                HStack { Button("Refresh") { model.refreshChats() }.disabled(!model.connected || model.busy); Button("Saved Messages") { model.openSavedMessages() }.disabled(!model.connected || model.busy) }
                if model.chatRefreshCursor != nil { Button("Load Older Dialogs") { model.refreshChats(older: true) }.disabled(!model.connected || model.busy) }
                List(model.chats) { chat in
                    Button { model.selectChat(chat) } label: {
                        VStack(alignment: .leading, spacing: 4) { HStack { Image(systemName: chat.kind == "private" ? "person.crop.circle" : chat.kind == "saved" ? "bookmark.circle" : "person.2.circle").foregroundStyle(.blue); Text(chat.title).font(.headline); Spacer(); if chat.data["unread_count"].int > 0 { Text(chat.data["unread_count"].int > 999 ? "999+" : String(chat.data["unread_count"].int)).font(.caption2.bold()).padding(.horizontal, 6).padding(.vertical, 2).background(.blue, in: Capsule()).foregroundStyle(.white).accessibilityLabel("\(chat.data["unread_count"].int) unread messages") } }; Text(chat.lastMessage).font(.caption).foregroundStyle(.secondary).lineLimit(2); HStack { Text(chat.kind.capitalized); Spacer(); Text(displayDate(chat.data["last_date"])) }.font(.caption2).foregroundStyle(.secondary) }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 5)
                    }.buttonStyle(.plain).accessibilityIdentifier("chatRow_\(chat.id)")
                }.overlay {
                    if model.chats.isEmpty {
                        ContentUnavailableView("No cached conversations", systemImage: "bubble.left.and.bubble.right", description: Text(model.chatQuery.isEmpty ? "Connect and choose Refresh to retrieve conversations." : "Try another search or conversation type."))
                    }
                }
                HStack { Button("Previous") { model.chatPage -= 1; Task { await model.loadChats() } }.disabled(model.chatPage == 0); Text("\(model.chatTotal) cached").font(.caption); Button("Next") { model.chatPage += 1; Task { await model.loadChats() } }.disabled((model.chatPage + 1) * model.pageSize >= model.chatTotal) }
            }.padding(16).frame(minWidth: 250, idealWidth: 300, maxWidth: 380)
            if let chat = model.selectedChat {
                VStack(alignment: .leading, spacing: 12) {
                    HStack { VStack(alignment: .leading) { Text(chat.title).font(.title2.bold()); Text("\(chat.kind.capitalized) · \(chat.id)").font(.caption).foregroundStyle(.secondary) }; Spacer(); Button("Refresh Messages") { Task { await model.loadMessages() } }.disabled(!model.connected || model.busy) }
                    HStack { TextField("Search Telegram messages", text: $messageSearch).textFieldStyle(.roundedBorder).onSubmit { Task { await model.loadMessages(search: messageSearch) } }; Button("Search") { Task { await model.loadMessages(search: messageSearch) } }.disabled(!model.connected || model.busy) }
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 14) {
                            ForEach(model.chatMessages) { message in
                                VStack(alignment: .leading, spacing: 5) {
                                    HStack { Text(message.sender).font(.caption.bold()); Text(displayDate(message.data["date"])).font(.caption).foregroundStyle(.secondary); Spacer(); if chat.allowsPersonalSend { Button("Reply") { model.chatReply = message.id; model.invalidateChatPreview() }.buttonStyle(.borderless).disabled(model.busy) } }
                                    Text(message.text).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                                    if message.hasAttachment { HStack { Label(message.data["media"]["kind"].string, systemImage: "paperclip"); Button("Save Attachment…") { model.downloadAttachment(message) }.disabled(model.busy) }.font(.caption) }
                                }.padding(12).background(message.outgoing ? Color.blue.opacity(0.08) : Color.secondary.opacity(0.06), in: RoundedRectangle(cornerRadius: 10))
                            }
                            if model.hasMoreMessages { Button("Load Older Messages") { Task { await model.loadMessages(older: true) } }.disabled(!model.connected || model.busy) }
                            if model.chatMessages.isEmpty { ContentUnavailableView("No messages loaded", systemImage: "bubble.left", description: Text("Select Refresh Messages to request Telegram history.")) }
                        }
                    }
                    Divider()
                    if chat.allowsPersonalSend {
                        if let reply = model.chatReply { HStack { Text("Replying to message \(reply)").font(.caption); Button("Clear Reply") { model.chatReply = nil; model.invalidateChatPreview() } } }
                        TextEditor(text: $model.chatDraft).font(.body).frame(minHeight: 90, maxHeight: 130).overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary)).onChange(of: model.chatDraft) { _, _ in model.invalidateChatPreview(); model.scheduleChatDraftSave() }.accessibilityIdentifier("chatComposer")
                        HStack { Text("\(model.chatDraft.utf16.count) / 4096").font(.caption); if let error = ComposerValidation.error(model.chatDraft) { Text(error).font(.caption).foregroundStyle(.orange) }; Spacer(); Button("Save Draft") { model.saveChatDraft() }.disabled(model.busy); Button("Preview") { model.prepareChatPreview() }.disabled(!model.chatCanPreview) }
                        if let preview = model.chatPreview {
                            GroupBox("From \(model.accountName) (\(model.accountID)) to \(chat.title) · \(chat.id)") { VStack(alignment: .leading) { Text(preview["message"].string).textSelection(.enabled); TextField("Type \(preview["confirmation"].string) to confirm", text: $model.chatConfirmation); Button("Send One Message") { model.sendChatConfirmed() }.disabled(!model.chatCanSend).buttonStyle(.borderedProminent) } }
                        }
                    } else { Label("Group messages require explicit destination approval in Composer.", systemImage: "checkmark.shield"); Button("Open Managed Composer") { model.screen = .composer } }
                }.padding(20).frame(minWidth: 420)
            } else { ContentUnavailableView("Select a conversation", systemImage: "bubble.left.and.bubble.right", description: Text("Cached conversations appear immediately. Refresh explicitly to retrieve Telegram dialogs.")).frame(maxWidth: .infinity) }
        }.accessibilityIdentifier("chatsScreen")
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

struct ActivityView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Activity").font(.largeTitle.bold())
            List(Array(model.activity.enumerated()), id: \.offset) { _, item in Text(item).textSelection(.enabled) }
                .overlay {
                    if model.activity.isEmpty { ContentUnavailableView("No activity this session", systemImage: "waveform.path.ecg", description: Text("Discoveries, inspections and connection events appear here. Saved delivery records are in History.")) }
                }
        }.padding(24)
    }
}

private func displayDate(_ value: JSONValue) -> String {
    if value.doubleValue > 0 { return Date(timeIntervalSince1970: value.doubleValue).formatted(date: .abbreviated, time: .shortened) }
    return safeDisplay(value.string)
}
