import SwiftUI

struct ComposerView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        GeometryReader { geometry in
            if geometry.size.width >= 850 {
                HSplitView {
                    composingPane.frame(minWidth: 430)
                    reviewPane.frame(minWidth: 320, idealWidth: 380)
                }
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        composingPane
                        Divider()
                        reviewPane
                    }
                }
            }
        }
        .onChange(of: model.draft) { _, _ in model.invalidatePreview(); model.scheduleDraftSave() }
        .onChange(of: model.destination) { _, _ in model.invalidatePreview() }
        .task { await model.loadApprovals() }
    }
    private var composingPane: some View {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(title: "Compose message", subtitle: "One message. One explicitly approved destination.", symbol: "square.and.pencil")
                Label("From \(model.accountName.isEmpty ? model.activeProfile?.title ?? "Selected account" : model.accountName) · \(model.accountID)", systemImage: "person.crop.circle")
                    .font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
                TextEditor(text: $model.draft).font(.body).padding(8).scrollContentBackground(.hidden)
                    .background(.background, in: RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(.quaternary))
                    .frame(minHeight: 200)
                    .accessibilityLabel("Message text").accessibilityIdentifier("messageEditor")
                HStack {
                    Text("\(ComposerValidation.units(model.draft)) / 4096 UTF-16 units").monospacedDigit().font(.caption).foregroundStyle(model.validation != nil && !model.draft.isEmpty ? .red : .secondary)
                    Spacer(); Button("Import UTF-8 File…") { model.importMessage() }.disabled(model.busy).help("Import a regular UTF-8 text file without sending"); Button("Save Draft") { model.saveDraft() }.disabled(model.busy)
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
            }.padding(20)
    }
    private var reviewPane: some View {
            VStack(alignment: .leading, spacing: 18) {
                Text("Delivery review").font(.title2.weight(.semibold))
                if let preview = model.preview {
                    Surface(title: "Exact destination") {
                        Text(safeDisplay(preview["group"]["name"].string)).font(.headline)
                        Text("Telegram ID: \(preview["destination"].string)").font(.callout).textSelection(.enabled)
                        PermissionBadge(state: preview["group"]["permission"].string)
                    }
                    Text("Complete message").font(.headline)
                    ScrollView { Text(preview["message"].string).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled).padding(14) }.frame(minHeight: 120, maxHeight: 320).background(.background, in: RoundedRectangle(cornerRadius: 12))
                    Text("To send this exact message once, type:").font(.callout)
                    Text(preview["confirmation"].string).font(.system(.callout, design: .monospaced).weight(.semibold)).textSelection(.enabled)
                    TextField("Exact confirmation", text: $model.confirmation).textFieldStyle(.roundedBorder).accessibilityIdentifier("sendConfirmation")
                    Button(role: .destructive) { model.sendConfirmed() } label: { Label("Confirm & Send Once", systemImage: "paperplane.fill") }
                        .buttonStyle(.borderedProminent).disabled(!model.canSend).accessibilityIdentifier("sendOnce")
                    Text("Permissions are checked again before submission. No automatic retries. Uncertain outcomes must be checked in History and Telegram.").font(.caption).foregroundStyle(.secondary)
                } else {
                    EmptyStateView(title: "No approved preview", symbol: "doc.text.magnifyingglass", description: "Compose a message, select one approved destination, then verify permissions. Changing either clears the preview.").frame(minHeight: 260)
                }
                Spacer(minLength: 0)
            }.padding(20)
    }
}

struct DestinationsView: View {
    @ObservedObject var model: AppModel
    @State private var revoking: TelegramGroup?
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageHeader(title: "Approved destinations", subtitle: "Manage groups you have explicitly approved for message delivery.", symbol: "checkmark.seal")
            Text("Each message still requires a fresh permission check and exact confirmation.").font(.caption).foregroundStyle(.secondary)
            if model.approvals.isEmpty {
                EmptyStateView(title: model.approvedSearch.isEmpty ? "No approved destinations" : "No matching destinations", symbol: "checkmark.seal", description: "Choose a group in Groups and explicitly approve it from the inspector.", actionTitle: "Browse Groups", action: { model.screen = .groups })
            } else {
                List(model.approvals) { group in
                    HStack(spacing: 14) {
                        Image(systemName: "checkmark.seal.fill").font(.title2).foregroundStyle(.blue)
                        VStack(alignment: .leading, spacing: 5) {
                            Text(group.name).font(.headline)
                            Text("ID \(group.id) · checked \(readableTime(group.checked))").font(.caption).foregroundStyle(.secondary)
                            Text("Explicitly approved · Account \(model.accountID)").font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer(); PermissionBadge(state: group.permission)
                        Button("Compose") { model.destination = group.id; model.screen = .composer }
                        Button("Revoke", role: .destructive) { revoking = group }.disabled(model.busy || !model.backendOnline)
                    }.padding(.vertical, 8)
                }.listStyle(.inset)
            }
        }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
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
    @State private var query = ""
    @State private var status = "all"
    @State private var sort = "newest"
    private var records: [Delivery] {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return model.deliveries.filter { record in
            (status == "all" || record.status == status) &&
            (needle.isEmpty || [record.destination, record.data["destination_name"].string,
                record.detail, record.data["message_preview"].string].contains { $0.localizedCaseInsensitiveContains(needle) })
        }.sorted { left, right in
            if sort == "destination" {
                let a = left.data["destination_name"].string, b = right.data["destination_name"].string
                if a != b { return a.localizedStandardCompare(b) == .orderedAscending }
            }
            if left.date == right.date { return left.id > right.id }
            return sort == "oldest" ? left.date < right.date : left.date > right.date
        }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageHeader(title: "Delivery history", subtitle: "Review message delivery outcomes and previously confirmed sends.", symbol: "clock.arrow.circlepath")
            Text("Pending or uncertain outcomes are never retried automatically.").font(.caption).foregroundStyle(.secondary)
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) { filters }
                VStack(alignment: .leading, spacing: 10) { filters }
            }
            if records.isEmpty {
                EmptyStateView(title: model.deliveries.isEmpty ? "No delivery records" : "No matching deliveries", symbol: "clock.arrow.circlepath", description: model.deliveries.isEmpty ? "Delivery results appear here after a message you explicitly confirm. Nothing sends from this screen." : "Try a different search or status filter.", actionTitle: model.deliveries.isEmpty ? "Compose a Message" : "Clear Filters", action: {
                    if model.deliveries.isEmpty { model.screen = .composer } else { query = ""; status = "all" }
                })
            } else {
                Table(records, selection: $selected) {
                    TableColumn("Date") { Text(readableTime($0.date)) }.width(min: 120, ideal: 160)
                    TableColumn("Destination") { record in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(record.data["destination_name"].string.isEmpty ? record.destination : safeDisplay(record.data["destination_name"].string)).lineLimit(2)
                            Text(record.destination).font(.caption).foregroundStyle(.secondary)
                        }.textSelection(.enabled)
                    }.width(min: 120, ideal: 180)
                    TableColumn("Account") { Text($0.data["account"].string).font(.caption).monospacedDigit() }.width(min: 65, ideal: 90)
                    TableColumn("Status") { delivery in
                        StatusBadge(title: delivery.status.capitalized, symbol: delivery.status == "sent" ? "checkmark.circle" : "exclamationmark.circle", tone: delivery.status == "sent" ? .success : ["failed", "rejected"].contains(delivery.status) ? .failure : .warning)
                    }.width(min: 100, ideal: 125)
                    TableColumn("Result") { record in
                        VStack(alignment: .leading, spacing: 4) {
                            if !record.data["message_preview"].string.isEmpty { Text(safeDisplay(record.data["message_preview"].string)).font(.callout).lineLimit(1) }
                            Text(record.detail).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                        }.padding(.vertical, 3)
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity).accessibilityIdentifier("deliveryHistoryTable")
                if let record = records.first(where: { $0.id == selected }) {
                    SectionCard(title: "Record details") {
                        Text(record.detail).textSelection(.enabled)
                        LabeledContent("Ledger ID", value: String(record.id))
                        LabeledContent("Message ID", value: record.data["telegram_message_id"].string.isEmpty ? "Not recorded" : record.data["telegram_message_id"].string)
                        LabeledContent("Updated", value: readableTime(record.data["updated_at"].string))
                        Text(record.data["message_preview"].string.isEmpty ? "Message body is not stored in this legacy ledger record." : record.data["message_preview"].string).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .task { await model.loadHistory() }
    }
    @ViewBuilder private var filters: some View {
        SearchToolbar(text: $query, prompt: "Search cached delivery history").frame(minWidth: 180)
            .accessibilityIdentifier("historySearch")
        FilterMenu(title: "Status", selection: $status, options: ["all", "sent", "pending", "uncertain", "blocked", "rejected", "failed", "cancelled"])
            .accessibilityIdentifier("historyStatusFilter")
        FilterMenu(title: "Sort", selection: $sort, options: ["newest", "oldest", "destination"])
            .accessibilityIdentifier("historySort")
        Button { Task { await model.loadHistory() } } label: { Image(systemName: "arrow.clockwise") }
            .disabled(model.busy).help("Reload the latest 100 delivery records").accessibilityLabel("Refresh delivery history")
        Text("\(records.count) of \(model.deliveries.count) loaded").font(.caption).foregroundStyle(.secondary).fixedSize()
    }
}
