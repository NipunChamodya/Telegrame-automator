import SwiftUI

struct ComposerView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        HSplitView {
            VStack(alignment: .leading, spacing: 18) {
                HStack { VStack(alignment: .leading, spacing: 6) { Text("Compose with intention").font(.title.weight(.semibold)); Text("One message. One explicitly approved destination.").foregroundStyle(.secondary) }; Spacer() }
                TextEditor(text: $model.draft).font(.body).padding(8).scrollContentBackground(.hidden)
                    .background(.background, in: RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(.quaternary))
                    .accessibilityLabel("Message text").accessibilityIdentifier("messageEditor")
                HStack {
                    Text("\(ComposerValidation.units(model.draft)) / 4096 UTF-16 units").monospacedDigit().font(.caption).foregroundStyle(model.validation != nil && !model.draft.isEmpty ? .red : .secondary)
                    Spacer(); Button("Import UTF-8 File…") { model.importMessage() }; Button("Save Draft") { model.saveDraft() }.disabled(model.busy)
                }
                if let validation = model.validation, !model.draft.isEmpty { Label(validation, systemImage: "exclamationmark.circle").foregroundStyle(.red).font(.callout) }
                Text(model.draftDirty ? "Unsaved changes" : model.draftSaved.isEmpty ? "" : "Draft saved \(readableTime(model.draftSaved))").font(.caption).foregroundStyle(.secondary)
                Divider()
                Picker("Approved destination", selection: $model.destination) {
                    Text("Select an approved group").tag(Int?.none)
                    ForEach(model.approvals) { group in Text("\(group.name) · \(group.id)").tag(Optional(group.id)) }
                }
                if model.approvals.isEmpty { Text("Approve a group from its inspector or Destinations first. Permission to post does not imply approval.").font(.caption).foregroundStyle(.secondary) }
                HStack {
                    Button("Manage Destinations") { model.screen = .destinations }
                    Spacer()
                    Button { model.preparePreview() } label: { Label("Preview & Verify Permissions", systemImage: "checkmark.shield") }
                        .buttonStyle(.borderedProminent).disabled(!model.canPreview).accessibilityIdentifier("previewMessage")
                }
            }.padding(26).frame(minWidth: 440)
            VStack(alignment: .leading, spacing: 18) {
                Text("Delivery review").font(.title2.weight(.semibold))
                if let preview = model.preview {
                    Surface(title: "Exact destination") {
                        Text(safeDisplay(preview["group"]["name"].string)).font(.headline)
                        Text("Telegram ID: \(preview["destination"].string)").font(.callout).textSelection(.enabled)
                        PermissionBadge(state: preview["group"]["permission"].string)
                    }
                    Text("Complete message").font(.headline)
                    ScrollView { Text(preview["message"].string).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled).padding(14) }.background(.background, in: RoundedRectangle(cornerRadius: 12))
                    Text("To send this exact message once, type:").font(.callout)
                    Text(preview["confirmation"].string).font(.system(.callout, design: .monospaced).weight(.semibold)).textSelection(.enabled)
                    TextField("Exact confirmation", text: $model.confirmation).textFieldStyle(.roundedBorder).accessibilityIdentifier("sendConfirmation")
                    Button(role: .destructive) { model.sendConfirmed() } label: { Label("Confirm & Send Once", systemImage: "paperplane.fill") }
                        .buttonStyle(.borderedProminent).disabled(!model.canSend).accessibilityIdentifier("sendOnce")
                    Text("Permissions are checked again before submission. No automatic retries. Uncertain outcomes must be checked in History and Telegram.").font(.caption).foregroundStyle(.secondary)
                } else {
                    ContentUnavailableView("No approved preview", systemImage: "doc.text.magnifyingglass", description: Text("Compose a message, select one approved destination, then verify permissions. Changing either clears the preview."))
                }
                Spacer(minLength: 0)
            }.padding(26).frame(minWidth: 320, idealWidth: 380)
        }
        .onChange(of: model.draft) { _, _ in model.invalidatePreview() }
        .onChange(of: model.destination) { _, _ in model.invalidatePreview() }
        .task { await model.loadApprovals() }
    }
}

struct DestinationsView: View {
    @ObservedObject var model: AppModel
    @State private var revoking: TelegramGroup?
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Explicitly approved destinations").font(.title2.weight(.semibold))
            Text("Approval records your choice of destination. Every message still needs its own preview, fresh permission check and exact confirmation.").foregroundStyle(.secondary)
            if model.approvals.isEmpty {
                ContentUnavailableView("No approved destinations", systemImage: "checkmark.seal", description: Text("Choose a group in Groups and explicitly approve it from the inspector."))
                Button("Browse Groups") { model.screen = .groups }
            } else {
                List(model.approvals) { group in
                    HStack(spacing: 14) {
                        Image(systemName: "checkmark.seal.fill").font(.title2).foregroundStyle(.blue)
                        VStack(alignment: .leading, spacing: 5) { Text(group.name).font(.headline); Text("ID \(group.id) · checked \(readableTime(group.checked))").font(.caption).foregroundStyle(.secondary) }
                        Spacer(); PermissionBadge(state: group.permission)
                        Button("Compose") { model.destination = group.id; model.screen = .composer }
                        Button("Revoke", role: .destructive) { revoking = group }.disabled(model.busy)
                    }.padding(.vertical, 8)
                }.listStyle(.inset)
            }
        }.padding(24)
        .searchable(text: $model.approvedSearch, prompt: "Search approved groups")
        .onChange(of: model.approvedSearch) { _, _ in Task { await model.loadApprovals() } }
        .task { await model.loadApprovals() }
        .confirmationDialog("Revoke this destination's approval?", isPresented: Binding(get: { revoking != nil }, set: { if !$0 { revoking = nil } }), titleVisibility: .visible) {
            if let group = revoking { Button("Revoke \(group.name)", role: .destructive) { model.setApproval(group.id, approved: false); revoking = nil } }
        }
    }
}

struct HistoryView: View {
    @ObservedObject var model: AppModel
    @State private var selected: Int?
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack { Text("Delivery ledger").font(.title2.weight(.semibold)); Spacer(); Button("Refresh") { Task { await model.loadHistory() } } }
            Text("Unknown or pending outcomes are never retried automatically. Legacy records may not contain message previews or Telegram message IDs.").font(.callout).foregroundStyle(.secondary)
            if model.deliveries.isEmpty { ContentUnavailableView("No delivery records", systemImage: "clock.arrow.circlepath", description: Text("Delivery results appear here after an explicitly confirmed send.")) }
            else {
                Table(model.deliveries, selection: $selected) {
                    TableColumn("Date") { Text(readableTime($0.date)) }.width(min: 130, ideal: 170)
                    TableColumn("Destination") { record in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(record.data["destination_name"].string.isEmpty ? record.destination : safeDisplay(record.data["destination_name"].string)).lineLimit(2)
                            Text(record.destination).font(.caption).foregroundStyle(.secondary)
                        }.textSelection(.enabled)
                    }.width(min: 130, ideal: 180)
                    TableColumn("Status") { delivery in Label(delivery.status.capitalized, systemImage: delivery.status == "sent" ? "checkmark.circle" : "exclamationmark.circle").foregroundStyle(delivery.status == "sent" ? .green : .orange) }.width(min: 90, ideal: 120)
                    TableColumn("Result") { Text($0.detail).font(.callout).lineLimit(2) }
                }
                if let record = model.deliveries.first(where: { $0.id == selected }) {
                    Surface(title: "Record details") {
                        Text(record.detail).textSelection(.enabled)
                        LabeledContent("Ledger ID", value: String(record.id))
                        LabeledContent("Message ID", value: record.data["telegram_message_id"].string.isEmpty ? "Not recorded" : record.data["telegram_message_id"].string)
                        LabeledContent("Updated", value: readableTime(record.data["updated_at"].string))
                        Text(record.data["message_preview"].string.isEmpty ? "Message body is not stored in this legacy ledger record." : record.data["message_preview"].string).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }.padding(24).searchable(text: $model.historySearch, prompt: "Search delivery history")
            .onChange(of: model.historySearch) { _, _ in Task { await model.loadHistory() } }
            .task { await model.loadHistory() }
    }
}
