import SwiftUI

struct MessageActionSheet: View {
    @ObservedObject var model: AppModel
    let context: MessageActionContext
    private var deleting: Bool { context.action == "delete" }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Label(deleting ? "Delete for Me" : "Edit Message", systemImage: deleting ? "trash" : "pencil").font(.title2.weight(.semibold))
                Spacer()
                Button("Close") { model.closeMessageAction() }.disabled(model.messageActionBusy)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Account \(context.scope.accountID) · \(context.peerName) (\(context.peerID)) · Message \(context.messageID)").font(.callout).textSelection(.enabled)
                    if deleting { Label("Only your copy is deleted. Other participants’ copies remain unchanged.", systemImage: "person.crop.circle").foregroundStyle(.orange) }
                    else { Text("Editing replaces this own message with plain text. Telegram checks the current edit permissions.").font(.callout).foregroundStyle(.secondary) }
                    GroupBox("Cached original message") { ScrollView { Text(model.messageActionOriginalText.isEmpty ? "Original content is no longer available." : model.messageActionOriginalText).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }.frame(height: 80) }
                    if !deleting {
                        TextEditor(text: $model.messageActionDraft).font(.body).frame(height: 120).overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))
                            .disabled(model.messageActionBusy || model.messageActionSubmitted)
                            .onChange(of: model.messageActionDraft) { _, _ in model.invalidateMessageActionPreview() }.accessibilityIdentifier("messageActionEditor")
                        Text("\(model.messageActionDraft.utf16.count) / 4096").font(.caption).foregroundStyle(.secondary)
                    }
                    if let preview = model.messageActionPreview {
                        GroupBox("Review the exact action") {
                            VStack(alignment: .leading, spacing: 10) {
                                Text("\(deleting ? "Delete for me" : "Edit") message \(preview["message_id"].int) in \(preview["destination"].int), account \(preview["account_id"].int).")
                                Text("Current Telegram text").font(.caption.weight(.semibold))
                                ScrollView { Text(preview["original_text"].string).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }.frame(height: 70)
                                if !deleting { Text("Revised text").font(.caption.weight(.semibold)); ScrollView { Text(preview["message"].string).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }.frame(height: 70) }
                                TextField("Type \(preview["confirmation"].string)", text: $model.messageActionConfirmation).textFieldStyle(.roundedBorder).disabled(model.messageActionBusy || model.messageActionSubmitted)
                                Button(deleting ? "Confirm Delete for Me" : "Confirm Edit", role: deleting ? .destructive : nil) { model.commitMessageAction() }.disabled(!model.canCommitMessageAction).accessibilityIdentifier("commitMessageAction")
                            }.frame(maxWidth: .infinity, alignment: .leading)
                        }
                    } else if !model.messageActionSubmitted {
                        Button("Verify and Preview") { model.previewMessageAction() }.disabled(!model.canPreviewMessageAction).buttonStyle(.borderedProminent).accessibilityIdentifier("previewMessageAction")
                    }
                    if model.messageActionBusy { ProgressView("Checking Telegram…").controlSize(.small) }
                    if let error = model.messageActionError { Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.orange) }
                    if let operation = model.messageActionResult {
                        GroupBox("Operation result") {
                            VStack(alignment: .leading, spacing: 8) {
                                Text(operation["status"].string.capitalized).font(.headline)
                                Text(operation["status"].string == "acknowledged" ? "Telegram acknowledged the action." : operation["status"].string == "uncertain" ? "The outcome is uncertain. Do not repeat this action; inspect the operation record." : "Telegram rejected the action. No automatic retry was attempted.")
                                Text("Operation \(operation["id"].string)").font(.caption)
                            }.frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    Button("View Message Actions") { model.closeMessageAction(); model.navigate(to: .messageOperations) }.disabled(model.messageActionBusy)
                }.padding(.vertical, 4)
            }
        }.padding(24).frame(width: 600, height: 600).interactiveDismissDisabled(model.messageActionBusy).accessibilityIdentifier("messageActionSheet")
    }
}

struct MessageOperationsView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageHeader(title: "Message Actions", subtitle: "Own-message edits and deletions have a separate account-specific operation ledger. Uncertain actions are never automatically retried.", symbol: "pencil.and.list.clipboard")
            HStack { Text("Latest 100 records").font(.caption).foregroundStyle(.secondary); Spacer(); Button("Refresh Records") { Task { await model.loadMessageOperations() } } }
            CachedReadStatus(model: model, screen: .messageOperations, retry: { Task { await model.loadMessageOperations() } })
            List(Array(model.messageOperations.enumerated()), id: \.offset) { _, row in
                DisclosureGroup {
                    VStack(alignment: .leading, spacing: 6) {
                        LabeledContent("Operation", value: row["id"].string)
                        LabeledContent("Destination", value: row["destination"].string)
                        LabeledContent("Message", value: row["message_id"].string)
                        LabeledContent("Updated", value: row["updated_at"].string)
                        Text(safeDisplay(row["detail"].string)).foregroundStyle(.secondary)
                    }.font(.callout).textSelection(.enabled)
                } label: { HStack { Text(row["action"].string == "delete" ? "Delete for me" : "Edit message").font(.headline); Text(row["created_at"].string).font(.caption).foregroundStyle(.secondary); Spacer(); Text(row["status"].string.capitalized).font(.caption.weight(.medium)) } }
            }.overlay { if model.messageOperations.isEmpty { EmptyStateView(title: "No message actions", symbol: "pencil", description: "Use a supported own message’s context menu in Chats. Edits and delete-for-me outcomes appear here; deliveries remain in Delivery History.", actionTitle: "Open Chats", action: { model.navigate(to: .chats) }) } }
        }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).task { await model.loadMessageOperations() }.accessibilityIdentifier("messageOperations")
    }
}
