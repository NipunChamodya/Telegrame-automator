import SwiftUI
import AppKit

struct GroupsView: View {
    @ObservedObject var model: AppModel
    let inspectionMode: Bool
    var body: some View {
        VStack(spacing: 0) {
            PageHeader(title: inspectionMode ? "Permissions" : "Group management", subtitle: inspectionMode ? "Inspect a bounded selection. Cached permissions never authorize sending." : "Discover joined groups and review account-specific metadata.", symbol: inspectionMode ? "checkmark.shield" : "person.3").padding(16)
            HStack {
                SearchToolbar(text: $model.search, prompt: "Search name, username or Telegram ID")
                    .accessibilityIdentifier("groupSearch")
                Button("Discover Groups") { model.discover() }.disabled(model.busy || !model.connected)
            }.padding(.horizontal, 16).padding(.bottom, 8).fixedSize(horizontal: false, vertical: true)
            ScrollView(.horizontal, showsIndicators: false) {
            HStack {
                Picker("Permission", selection: $model.permissionFilter) { Text("All permissions").tag("all"); Text("Allowed").tag("allowed"); Text("Restricted").tag("denied"); Text("Unknown").tag("unknown") }.frame(width: 165)
                Picker("Type", selection: $model.kindFilter) { Text("All groups").tag("all"); Text("Groups").tag("group"); Text("Supergroups").tag("supergroup") }.frame(width: 140)
                Picker("Sort", selection: $model.sort) { Text("Name").tag("name"); Text("Members").tag("members"); Text("Last checked").tag("checked_at") }.frame(width: 150)
                Spacer()
                Text("\(model.totalGroups) groups").font(.caption).foregroundStyle(.secondary)
            }.padding(16)
            }.fixedSize(horizontal: false, vertical: true)
            if inspectionMode {
                HStack {
                    Label("\(model.status["overview"]["pending"].int) pending · \(model.selectedInspection.count) selected", systemImage: "checkmark.shield").font(.callout)
                    Spacer()
                    Stepper("Limit: \(model.inspectionLimit)", value: $model.inspectionLimit, in: 1...100).frame(width: 135)
                    Button(model.selectedInspection.isEmpty ? "Inspect Pending" : "Inspect Selected") { model.inspectPending() }.disabled(!model.canInspect).buttonStyle(.borderedProminent)
                }.padding(.horizontal, 16).padding(.bottom, 14)
            }
            CachedReadStatus(model: model, screen: inspectionMode ? .permissions : .groups, retry: { Task { await model.loadGroups() } }).padding(.horizontal, 16)
            Divider()
            if model.groups.isEmpty {
                ContentUnavailableView {
                    Label(model.search.isEmpty ? "No cached groups" : "No matching groups", systemImage: "person.3")
                } description: { Text(model.search.isEmpty ? "Discover joined groups when you are ready. Detailed inspection is a separate action." : "Try a different name, username, ID or permission filter.") }
            } else {
                Table(model.groups, selection: $model.selectedInspection) {
                    TableColumn("Group") { group in VStack(alignment: .leading, spacing: 4) { Text(group.name).fontWeight(.medium).lineLimit(2); if !group.username.isEmpty { Text("@" + group.username).font(.caption).foregroundStyle(.secondary) } }.padding(.vertical, 6) }.width(min: 180, ideal: 280)
                    TableColumn("Type") { Text($0.kind == "supergroup" ? "Supergroup" : "Group").foregroundStyle(.secondary) }.width(min: 80, ideal: 90)
                    TableColumn("Members") { Text($0.members).monospacedDigit() }.width(min: 65, ideal: 80)
                    TableColumn("Posting") { PermissionBadge(state: $0.permission) }.width(min: 85, ideal: 100)
                    TableColumn("Metadata") { Text($0.freshness.capitalized).font(.caption).foregroundStyle(.secondary) }.width(min: 75, ideal: 90)
                    TableColumn("Checked") { Text(readableTime($0.checked)).font(.caption).foregroundStyle(.secondary) }.width(min: 100, ideal: 140)
                }
                .accessibilityIdentifier("groupTable")
                .contextMenu(forSelectionType: Int.self) { ids in
                    if let id = ids.first {
                        Button("Inspect permissions") { model.inspect(id) }.disabled(model.busy || !model.connected)
                        Button("Copy group ID") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(String(id), forType: .string) }
                    }
                } primaryAction: { ids in if let id = ids.first { model.select(id) } }
            }
            Divider()
            HStack {
                Text("Cached rows only — opening this screen makes no Telegram requests.").font(.caption).foregroundStyle(.secondary)
                Spacer(); Button { model.page -= 1; Task { await model.loadGroups() } } label: { Image(systemName: "chevron.left") }.disabled(model.page == 0 || model.busy).help("Previous group page").accessibilityLabel("Previous group page")
                Text("Page \(model.page + 1)").font(.caption).monospacedDigit()
                Button { model.page += 1; Task { await model.loadGroups() } } label: { Image(systemName: "chevron.right") }.disabled((model.page + 1) * model.pageSize >= model.totalGroups || model.busy).help("Next group page").accessibilityLabel("Next group page")
            }.padding(12)
        }
        .onChange(of: model.search) { _, _ in model.scheduleSearch() }
        .onChange(of: model.permissionFilter) { _, _ in model.scheduleSearch() }
        .onChange(of: model.kindFilter) { _, _ in model.scheduleSearch() }
        .onChange(of: model.sort) { _, _ in model.scheduleSearch() }
        .onChange(of: model.selectedInspection) { _, ids in model.select(ids.first) }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .sheet(item: $model.detail) { group in
            GroupInspector(model: model, group: group).frame(minWidth: 380, idealWidth: 440, maxWidth: 560, minHeight: 400, idealHeight: 620)
                .accessibilityIdentifier("groupInspector")
        }
        .task { await model.loadGroups() }
    }
}

struct GroupInspector: View {
    @ObservedObject var model: AppModel
    let group: TelegramGroup
    @State private var approve = false
    @State private var localLabel = ""
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack { Image(systemName: "person.3.fill").font(.title).foregroundStyle(.blue); Spacer(); Button { model.detail = nil } label: { Image(systemName: "xmark.circle.fill") }.buttonStyle(.plain).foregroundStyle(.secondary).help("Close group details").accessibilityLabel("Close group details") }
                Text(group.name).font(.title2.weight(.semibold)).textSelection(.enabled)
                PermissionBadge(state: group.permission)
                Divider()
                LabeledContent("Telegram ID", value: String(group.id)).textSelection(.enabled)
                LabeledContent("Type", value: group.kind)
                LabeledContent("Username", value: group.username.isEmpty ? "Unavailable" : "@" + group.username)
                LabeledContent("Members", value: group.members)
                LabeledContent("Checked", value: readableTime(group.checked))
                LabeledContent("Metadata", value: group.completeness)
                LabeledContent("Freshness", value: group.freshness)
                LabeledContent("Slow mode", value: group.data["slowmode_seconds"] == .null ? "Unknown" : group.data["slowmode_seconds"].string + " seconds")
                VStack(alignment: .leading, spacing: 8) { Text("Permission reasons").font(.headline); ForEach(group.reasons, id: \.self) { Text($0).font(.callout).foregroundStyle(.secondary) } }
                VStack(alignment: .leading, spacing: 8) { Text("Visible bots").font(.headline); Text(group.data["visible_bots"].array.map(\.string).joined(separator: ", ").isEmpty ? "Not available" : group.data["visible_bots"].array.map(\.string).joined(separator: ", ")).font(.callout).foregroundStyle(.secondary) }
                VStack(alignment: .leading, spacing: 8) { Text("Unknown rules").font(.headline); ForEach(group.data["unknown_rules"].array.map(\.string), id: \.self) { Text(safeDisplay($0)).font(.callout).foregroundStyle(.secondary) } }
                Button("Inspect Permissions") { model.inspect(group.id) }.disabled(model.busy || !model.connected).buttonStyle(.borderedProminent)
                Text(model.localLabels.filter { $0["destination"].int == group.id }.map { safeDisplay($0["label"].string) }.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
                TextField("Local label", text: $localLabel).textFieldStyle(.roundedBorder)
                HStack { Button("Apply Label") { model.setGroupLabel(group.id, label: localLabel, enabled: true) }; Button("Remove Label") { model.setGroupLabel(group.id, label: localLabel, enabled: false) } }.disabled(model.busy || localLabel.isEmpty)
                Button("Copy Group ID") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(String(group.id), forType: .string) }
                Button("Approve Destination…") { approve = true }.disabled(model.busy || !model.connected)
                Text("Approval is separate from Telegram posting permissions. It does not send a message.").font(.caption).foregroundStyle(.secondary)
            }.padding(20)
        }.confirmationDialog("Approve this exact destination?", isPresented: $approve, titleVisibility: .visible) {
            Button("Approve \(group.name)") { model.setApproval(group.id, approved: true) }
        } message: { Text("Telegram ID: \(group.id). You remain responsible for group rules and administrator permission.") }
    }
}
