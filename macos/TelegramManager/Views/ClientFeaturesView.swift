import SwiftUI
import AppKit

struct ContactsView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageHeader(title: "Contacts", subtitle: "Your cached Telegram contacts. Refresh explicitly to retrieve the latest list.", symbol: "person.crop.rectangle.stack")
            HStack {
                SearchToolbar(text: $model.contactQuery, prompt: "Search contacts or username")
                if model.contactsLoading { ProgressView().controlSize(.small) }
                Button("Refresh Contacts") { model.refreshContacts() }.disabled(!model.connected || model.busy).accessibilityIdentifier("refreshContacts").help("Explicitly retrieve Telegram contacts; does not access the macOS address book")
            }
            if !model.contactNotice.isEmpty { Label(model.contactNotice, systemImage: "info.circle").font(.caption).foregroundStyle(.secondary) }
            List(model.contacts) { contact in
                HStack(spacing: 12) {
                    Image(systemName: "person.crop.circle.fill").font(.system(size: 32)).foregroundStyle(.secondary).accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 4) {
                        HStack { Text(contact.name).font(.headline); if contact.data["verified"].bool { Image(systemName: "checkmark.seal.fill").foregroundStyle(.blue).accessibilityLabel("Verified by Telegram") } }
                        if !contact.username.isEmpty { Text("@" + contact.username).font(.caption).foregroundStyle(.secondary) }
                        if !contact.available { Text(safeDisplay(contact.data["content_reason"].string)).font(.caption).foregroundStyle(.secondary) }
                    }
                    Spacer()
                    Button("Profile") { model.showProfile(contact.id) }.disabled(!model.connected || model.busy)
                    Button("Message") { model.openContact(contact.id) }.disabled(!model.connected || model.busy || !contact.available)
                }.padding(.vertical, 7).accessibilityIdentifier("contact_\(contact.id)")
            }.frame(maxWidth: .infinity, maxHeight: .infinity).overlay {
                if model.contacts.isEmpty {
                    if model.contactsLoading { LoadingStateView(title: "Loading contacts…") }
                    else if let error = model.contactsError { ErrorStateView(title: "Contacts unavailable", message: error, retry: { Task { await model.loadContacts() } }) }
                    else { EmptyStateView(title: "No cached contacts", symbol: "person.crop.rectangle.stack", description: model.connected ? "Refresh to retrieve Telegram contacts. Your macOS address book is never accessed." : "Connect this Telegram account, then choose Refresh Contacts.", actionTitle: model.connected ? "Load Telegram Contacts" : nil, action: model.connected ? { model.refreshContacts() } : nil) }
                }
            }
            if !model.contacts.isEmpty, let error = model.contactsError { Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.red).font(.caption) }
            HStack { Button("Previous") { model.contactPage -= 1; Task { await model.loadContacts() } }.disabled(model.contactPage == 0); Spacer(); Text("\(model.contactTotal) contacts · Page \(model.contactPage + 1)").font(.caption).foregroundStyle(.secondary); Spacer(); Button("Next") { model.contactPage += 1; Task { await model.loadContacts() } }.disabled((model.contactPage + 1) * model.pageSize >= model.contactTotal) }
        }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).onChange(of: model.contactQuery) { _, _ in model.scheduleContactSearch() }.task { await model.loadContacts() }.accessibilityIdentifier("contactsScreen")
    }
}

struct PeerProfileView: View {
    @ObservedObject var model: AppModel
    let profile: PeerProfile
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack { PageHeader(title: profile.name, subtitle: profile.data["kind"].string.capitalized, symbol: "person.crop.circle"); Button("Close") { model.profileTarget = nil } }
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if profile.data["verified"].bool { Label("Verified by Telegram", systemImage: "checkmark.seal.fill").foregroundStyle(.blue) }
                    LabeledContent("Telegram ID", value: String(profile.id)).textSelection(.enabled)
                    LabeledContent("Username", value: profile.data["username"].string.isEmpty ? "Unavailable" : "@" + profile.data["username"].string)
                    if profile.data["members"] != .null { LabeledContent("Members", value: profile.data["members"].string) }
                    Text("About").font(.headline)
                    Text(profile.data["about"].string.isEmpty ? "Not available" : profile.data["about"].string.split(separator: "\n", omittingEmptySubsequences: false).map { safeDisplay(String($0)) }.joined(separator: "\n")).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                    if profile.data["has_photo"].bool { Label("A profile photo is available on Telegram. Profile photo loading is not implemented here.", systemImage: "person.crop.circle").font(.caption).foregroundStyle(.secondary) }
                    Text("Checked: " + profile.data["checked_at"].string).font(.caption).foregroundStyle(.secondary)
                    if !profile.data["content_available"].bool { Label(safeDisplay(profile.data["content_reason"].string), systemImage: "info.circle").foregroundStyle(.secondary) }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
            HStack { Button("Copy ID") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(String(profile.id), forType: .string) }; Spacer(); if profile.data["content_available"].bool && ["private", "saved"].contains(profile.data["kind"].string) { Button("Open Conversation") { model.openProfileConversation(profile.id) }.disabled(model.busy) } }
        }.padding(24).frame(width: 540, height: 500).accessibilityIdentifier("peerProfileSheet")
    }
}

struct TelegramFoldersView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack { PageHeader(title: "Telegram Folders", subtitle: "Read-only server definitions. Folder membership filtering and remote changes are not implemented.", symbol: "folder"); Button("Close") { model.foldersPresented = false } }
            Button("Refresh Definitions") { model.refreshFolders() }.disabled(!model.connected || model.busy)
            List(Array(model.telegramFolders.enumerated()), id: \.offset) { _, folder in
                DisclosureGroup(safeDisplay(folder["title"].string)) {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(["contacts", "non_contacts", "groups", "broadcasts", "bots", "exclude_muted", "exclude_read", "exclude_archived"], id: \.self) { key in LabeledContent(key.replacingOccurrences(of: "_", with: " ").capitalized, value: folder[key] == .null ? "Not available" : folder[key].bool ? "Yes" : "No") }
                        LabeledContent("Explicit includes", value: folder["include_peer_ids"].array.map(\.string).joined(separator: ", "))
                        LabeledContent("Explicit excludes", value: folder["exclude_peer_ids"].array.map(\.string).joined(separator: ", "))
                        LabeledContent("Pinned IDs", value: folder["pinned_peer_ids"].array.map(\.string).joined(separator: ", "))
                    }.font(.caption).padding(.vertical, 8).textSelection(.enabled)
                }
            }.overlay { if model.telegramFolders.isEmpty { ContentUnavailableView("No cached folder definitions", systemImage: "folder", description: Text("Refresh to read your Telegram configuration. No remote changes are made.")) } }
        }.padding(24).frame(width: 620, height: 550).task { await model.loadFolders() }.accessibilityIdentifier("telegramFoldersSheet")
    }
}
