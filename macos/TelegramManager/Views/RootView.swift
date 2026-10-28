import SwiftUI
import AppKit

struct PermissionBadge: View {
    var state: String
    var body: some View {
        Label(state.capitalized, systemImage: state == "allowed" ? "checkmark.circle.fill" : state == "denied" ? "nosign" : "questionmark.circle")
            .font(.caption.weight(.medium))
            .foregroundStyle(state == "allowed" ? .green : state == "denied" ? .red : .orange)
            .accessibilityLabel("Posting permission \(state)")
    }
}

struct Surface<Content: View>: View {
    var title: String
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(title.uppercased()).font(.caption.weight(.semibold)).tracking(1).foregroundStyle(.secondary)
            content
        }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
            .background(.background, in: RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(.quaternary, lineWidth: 1))
    }
}

struct RootView: View {
    @ObservedObject var model: AppModel
    @State private var didRestoreNavigation = false
    @SceneStorage("workspace.navigation") private var restoredScreen = Screen.chats.rawValue
    var body: some View {
        HSplitView {
            sidebar
            workspaceContent
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .navigationTitle("Unofficial Telegram Manager")
        .toolbar { workspaceToolbar }
        .onAppear {
            guard !didRestoreNavigation else { return }
            didRestoreNavigation = true
            // Restoration is local-only. Never restore a send preview or trigger a remote action.
            if !model.isUIFixture, let destination = Screen(rawValue: restoredScreen) {
                model.restoreNavigation(to: destination)
            }
        }
        .onChange(of: model.screen) { _, destination in if !model.isUIFixture { restoredScreen = destination.rawValue } }
        .alert("Operation needs attention", isPresented: Binding(get: { model.errorMessage != nil }, set: { if !$0 { model.dismissError() } })) {
            Button("OK") { model.dismissError() }
        } message: { Text(model.errorMessage ?? "") }
        .sheet(item: $model.profileTarget) { profile in PeerProfileView(model: model, profile: profile) }
        .sheet(isPresented: $model.foldersPresented) { TelegramFoldersView(model: model) }
        .sheet(item: $model.mediaPreview, onDismiss: { model.closeMediaPreview() }) { preview in ImagePreviewView(model: model, context: preview) }
        .sheet(isPresented: Binding(get: { ["credentials", "phone", "code", "password", "bind_account"].contains(model.authStage) }, set: { if !$0 { model.cancelAuthentication() } })) {
            AuthenticationView(model: model)
        }
        .sheet(isPresented: $model.diagnosticsPresented) {
            VStack(alignment: .leading, spacing: 16) {
                Text("Connection Diagnostics").font(.title2.weight(.semibold))
                ScrollView { Text(model.diagnosticsSummary).font(.system(.callout, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(4) }
                HStack { Spacer(); Button("Close") { model.diagnosticsPresented = false }.keyboardShortcut(.cancelAction) }
            }.padding(24).frame(minWidth: 520, idealWidth: 620, minHeight: 340)
                .accessibilityIdentifier("connectionDiagnosticsSheet")
        }
        .tint(.blue)
    }
    private var sidebar: some View {
        VStack(spacing: 0) {
                HStack(spacing: 10) {
                    Image(systemName: "checkmark.bubble.fill").font(.system(size: 32)).foregroundStyle(.blue)
                    VStack(alignment: .leading) { Text("Unofficial Telegram Manager").font(.headline); Text("Personal workspace").font(.caption).foregroundStyle(.secondary) }
                    Spacer()
                }.padding(16).fixedSize(horizontal: false, vertical: true).accessibilityIdentifier("workspaceIdentity")
                accountMenu.fixedSize(horizontal: false, vertical: true)
                List(selection: Binding<Screen>(get: { Screen.advanced.contains(model.screen) ? .advancedWorkspace : model.screen }, set: { model.navigate(to: $0) })) {
                    sidebarSection("Messaging", screens: Screen.messaging)
                    sidebarSection("Workspace", screens: [.advancedWorkspace])
                    if Screen.advanced.contains(model.screen) {
                        Section("Current tool") { Label(model.screen.rawValue, systemImage: model.screen.symbol).foregroundStyle(.secondary) }
                    }
                    sidebarSection("App", screens: [.accounts, .settings])
                }.listStyle(.sidebar).accessibilityIdentifier("workspaceSidebar").frame(maxHeight: .infinity)
                VStack(alignment: .leading, spacing: 6) {
                    Label(model.connected ? "Account connected" : model.backendOnline ? "Account not connected" : "Backend unavailable", systemImage: model.connected ? "checkmark.circle.fill" : "circle.dotted")
                        .font(.caption).foregroundStyle(model.connected ? .green : .secondary)
                    Text(model.activeProfile?.title ?? "Explicit account selection.").font(.caption2).foregroundStyle(.secondary)
                }.frame(maxWidth: .infinity, alignment: .leading).padding(16)
            }.frame(minWidth: 220, idealWidth: 245, maxWidth: 280, maxHeight: .infinity, alignment: .top).accessibilityIdentifier("applicationSidebar")
    }
    private var workspaceContent: some View {
        VStack(spacing: 0) {
                if model.busy {
                    HStack(spacing: 12) {
                        ProgressView().controlSize(.small)
                        VStack(alignment: .leading, spacing: 2) { Text(model.operation).font(.callout.weight(.medium)); if !model.progress.isEmpty { Text(model.progress).font(.caption).foregroundStyle(.secondary).lineLimit(1) } }
                        Spacer(); Button("Cancel", role: .cancel) { model.cancelOperation() }
                    }.padding(12).background(.blue.opacity(0.06))
                    Divider()
                }
                if !model.connected && !model.busy && model.screen != .dashboard {
                    RecoveryPanel(model: model, compact: true).padding(12)
                }
                Group {
                    switch model.screen {
                    case .dashboard: DashboardView(model: model)
                    case .chats, .groupChats, .channels: ChatsView(model: model)
                    case .savedMessages: ChatsView(model: model, detailOnly: true)
                    case .advancedWorkspace: AdvancedWorkspaceView(model: model)
                    case .contacts: ContactsView(model: model)
                    case .accounts: AccountsView(model: model)
                    case .drafts: DraftsView(model: model)
                    case .activity: ActivityTimeline(events: model.activity)
                    case .groups: GroupsView(model: model, inspectionMode: false)
                    case .permissions: GroupsView(model: model, inspectionMode: true)
                    case .composer: ComposerView(model: model)
                    case .destinations: DestinationsView(model: model)
                    case .history: HistoryView(model: model)
                    case .messageOperations: MessageOperationsView(model: model)
                    case .settings: SettingsView(model: model)
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .frame(minWidth: 460, maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(Color(nsColor: .windowBackgroundColor))
            .accessibilityIdentifier("workspaceContent")
    }
    @ToolbarContentBuilder private var workspaceToolbar: some ToolbarContent {

            ToolbarItem(placement: .navigation) {
                HStack(spacing: 8) {
                    if Screen.advanced.contains(model.screen) {
                        Button { model.navigate(to: .advancedWorkspace) } label: { Image(systemName: "chevron.left") }
                            .help("Back to Advanced Workspace").accessibilityLabel("Back to Advanced Workspace")
                    }
                    Label(model.screen.rawValue, systemImage: model.screen.symbol)
                        .lineLimit(1).frame(maxWidth: 220, alignment: .leading)
                        .accessibilityIdentifier("workspaceTitle")
                }
            }
            ToolbarItem(placement: .primaryAction) {
                Button { if model.connected { model.openDiagnostics() } else { model.retryConnection() } } label: {
                    Label(model.connected ? "Connection Details" : "Connect", systemImage: model.connected ? "info.circle" : "bolt.horizontal.circle")
                }
                .disabled(model.busy || model.isConnecting || (!model.connected && !model.connectionActionAvailable))
                .help(model.connected ? "View sanitized connection diagnostics" : "Restore the saved session or continue secure setup")
                .accessibilityIdentifier("connectBackend")
            }

    }
    @ViewBuilder private func sidebarSection(_ title: String, screens: [Screen]) -> some View {
        Section(title) {
            ForEach(screens) { screen in
                Label(screen.rawValue, systemImage: screen.symbol).tag(screen).padding(.vertical, 4)
            }
        }
    }
    private var accountMenu: some View {
        Menu {
            ForEach(model.profiles.filter { !$0.archived }) { profile in
                Button { if !profile.active { model.switchProfile(profile) } } label: {
                    Label(profile.title, systemImage: profile.active ? "checkmark.circle.fill" : "person.crop.circle")
                }.disabled(model.busy || model.isConnecting)
            }
            Divider()
            Button("Add Account…", systemImage: "person.badge.plus") { model.screen = .accounts }
            Button("Manage Accounts…", systemImage: "person.2.badge.gearshape") { model.screen = .accounts }
            Divider()
            Button("Disconnect Account…", systemImage: "bolt.slash") { model.screen = .accounts }
            Button("Log Out of Telegram…", systemImage: "rectangle.portrait.and.arrow.right") { model.screen = .accounts }
        } label: {
            AccountIdentityView(name: model.activeProfile?.title ?? model.accountName,
                                identifier: model.accountID == 0 ? "Not authenticated" : String(model.accountID),
                                status: model.connected ? "Connected" : model.connectionTitle,
                                connected: model.connected)
        }.menuStyle(.borderlessButton).padding(12)
            .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 12))
            .padding(.horizontal, 12).padding(.bottom, 12)
            .disabled(model.busy || model.isConnecting).accessibilityIdentifier("accountSwitcher")
            .help("Switch accounts or open account management; logout requires its own confirmation")
    }

}

struct DashboardView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack(alignment: .center) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Your Telegram workspace").font(.largeTitle.weight(.bold))
                        Text("Discover groups, understand permissions, and post with care.").foregroundStyle(.secondary)
                    }; Spacer()
                    Image(systemName: "checkmark.bubble").font(.system(size: 44, weight: .light)).foregroundStyle(.blue.opacity(0.7)).padding()
                }
                if !model.connected { RecoveryPanel(model: model) }
                HStack(spacing: 14) {
                    metric("Cached groups", key: "total", icon: "person.3", color: .blue)
                    metric("Allowed", key: "allowed", icon: "checkmark.circle", color: .green)
                    metric("Restricted", key: "denied", icon: "nosign", color: .red)
                    metric("Unknown", key: "unknown", icon: "questionmark.circle", color: .orange)
                }
                HStack(alignment: .top, spacing: 16) {
                    Surface(title: "Account") {
                        Label(model.connected ? "Connected" : "Not connected", systemImage: model.connected ? "checkmark.shield.fill" : "person.crop.circle.badge.questionmark").font(.title3.weight(.semibold))
                        Text(model.accountName.isEmpty ? "Personal Telegram account" : model.accountName)
                        LabeledContent("Account ID", value: model.accountID == 0 ? "Not bound" : String(model.accountID))
                        LabeledContent("Session", value: model.status["session_present"].bool ? "Saved privately" : "Setup required")
                        if !model.connected { Button("Connect Telegram") { model.retryConnection() }.disabled(model.busy) }
                    }
                    Surface(title: "System status") {
                        LabeledContent("Backend", value: model.backendOnline ? "Running" : "Offline")
                        LabeledContent("Pending inspections", value: model.status["overview"]["pending"].string)
                        LabeledContent("Metadata complete", value: model.status["overview"]["complete"].string)
                        LabeledContent("Last scan", value: readableTime(model.status["scan"]["started_at"].string))
                        CooldownView(deadline: model.status["cooldown_until"].doubleValue)
                    }
                }
                Surface(title: "Quick actions") {
                    HStack {
                        Button { model.discover() } label: { Label("Discover groups", systemImage: "arrow.clockwise") }.disabled(!model.connected || model.busy)
                        Button { model.screen = .groups } label: { Label("Browse groups", systemImage: "person.3") }
                        Button { model.screen = .permissions } label: { Label("Inspect permissions", systemImage: "checkmark.shield") }
                        Button { model.screen = .composer } label: { Label("Compose", systemImage: "square.and.pencil") }
                    }.buttonStyle(.bordered)
                }
                Surface(title: "Recent activity") {
                    if model.activity.isEmpty { Text("Operations you start will appear here. Nothing runs automatically.").foregroundStyle(.secondary) }
                    ForEach(Array(model.activity.prefix(8))) { event in
                        HStack(alignment: .top) {
                            Label(event.title, systemImage: event.kind.symbol).font(.callout)
                            Spacer()
                            Text(event.status.title).font(.caption).foregroundStyle(.secondary)
                            Text(event.date, style: .time).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                Text("Text-posting permission is not permission to advertise. Always follow group rules.").font(.caption).foregroundStyle(.secondary)
            }.padding(28).frame(maxWidth: .infinity, alignment: .topLeading)
        }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).background(Color(nsColor: .windowBackgroundColor))
    }
    func metric(_ title: String, key: String, icon: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Image(systemName: icon).font(.title3).foregroundStyle(color)
            Text(model.status["overview"][key].string.isEmpty ? "—" : model.status["overview"][key].string).font(.system(size: 32, weight: .semibold, design: .rounded))
            Text(title).font(.caption).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(18).background(.background, in: RoundedRectangle(cornerRadius: 14))
    }
}

extension JSONValue { var doubleValue: Double { switch self { case .number(let v): return v; case .integer(let v): return Double(v); default: return 0 } } }
func readableTime(_ text: String) -> String {
    guard !text.isEmpty else { return "Never" }
    let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    guard let date = formatter.date(from: text) ?? ISO8601DateFormatter().date(from: text) else { return text }
    return date.formatted(date: .abbreviated, time: .shortened)
}
struct CooldownView: View {
    let deadline: Double
    @State private var remaining = 0
    var body: some View {
        Group {
            if remaining > 0 {
                Label("Telegram cooldown · \(remaining)s remaining", systemImage: "hourglass").foregroundStyle(.orange).font(.callout)
            } else {
                Label(deadline > 0 ? "Cooldown expired · resume explicitly" : "No Telegram cooldown", systemImage: "checkmark.circle").foregroundStyle(.secondary).font(.callout)
            }
        }.task(id: deadline) {
            remaining = max(0, Int(ceil(deadline - Date().timeIntervalSince1970)))
            while remaining > 0 && !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: 1_000_000_000) } catch { return }
                remaining = max(0, Int(ceil(deadline - Date().timeIntervalSince1970)))
            }
        }
    }
}


struct RecoveryPanel: View {
    @ObservedObject var model: AppModel
    var compact = false
    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 8 : 14) {
            Label(model.connectionTitle, systemImage: model.connectionSymbol)
                .font(compact ? .headline : .title3.weight(.semibold))
                .accessibilityIdentifier("connectionRecoveryTitle")
            Text(model.connectionExplanation).font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) { actions }
                VStack(alignment: .leading, spacing: 8) { actions }
            }
        }.padding(compact ? 12 : 18).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.blue.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
            .accessibilityElement(children: .contain).accessibilityIdentifier("connectionRecoveryPanel")
    }
    @ViewBuilder private var actions: some View {
        Button("Retry Connection") { model.retryConnection() }
            .disabled(model.busy || model.isConnecting || !model.connectionActionAvailable)
            .help("Reconnect safely without deleting credentials or local history")
            .accessibilityIdentifier("retryConnection")
        Button("Manage Accounts") { model.screen = .accounts }.disabled(model.busy)
            .accessibilityIdentifier("recoveryManageAccounts")
        Button("Connection Diagnostics") { model.openDiagnostics() }.disabled(model.busy)
            .help("Open sanitized backend and connection diagnostics")
            .accessibilityIdentifier("openConnectionDiagnostics")
    }
}

struct AdvancedWorkspaceView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                PageHeader(title: "Advanced Workspace", subtitle: "Group management, explicit destination approvals, and delivery records remain available here.", symbol: "square.stack.3d.up")
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 16)], spacing: 16) {
                    ForEach(Screen.advanced) { screen in
                        Button { model.navigate(to: screen) } label: {
                            VStack(alignment: .leading, spacing: 12) {
                                Image(systemName: screen.symbol).font(.title2).foregroundStyle(.tint)
                                Text(screen.rawValue).font(.headline)
                                Text(description(screen)).font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.leading)
                            }.frame(maxWidth: .infinity, minHeight: 115, alignment: .topLeading).padding(18)
                                .background(.background, in: RoundedRectangle(cornerRadius: 12)).overlay(RoundedRectangle(cornerRadius: 12).stroke(.quaternary))
                        }.buttonStyle(.plain).accessibilityIdentifier("advanced_\(screen.id)")
                    }
                }
                Label("Technical posting permission does not authorize advertising or unsolicited messages.", systemImage: "checkmark.shield").font(.callout).foregroundStyle(.secondary)
            }.padding(24)
        }.accessibilityIdentifier("advancedWorkspace")
    }
    private func description(_ screen: Screen) -> String {
        switch screen {
        case .dashboard: return "Account, group, and system status."
        case .groups: return "Discover groups and inspect cached metadata."
        case .permissions: return "Inspect selected destinations with controlled limits."
        case .composer: return "Compose, preview, and confirm one approved group delivery."
        case .drafts: return "Continue saved account-specific drafts."
        case .destinations: return "Explicitly approve or revoke messaging destinations."
        case .history: return "Review persistent delivery outcomes without automatic retries."
        case .messageOperations: return "Review acknowledged, rejected, and uncertain own-message edits or deletions."
        case .activity: return "Review this session’s connection and operation timeline."
        default: return ""
        }
    }
}
