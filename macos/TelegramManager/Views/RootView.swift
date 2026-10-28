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
    var body: some View {
        NavigationSplitView {
            VStack(spacing: 0) {
                HStack(spacing: 10) {
                    Image(systemName: "paperplane.circle.fill").font(.system(size: 32)).foregroundStyle(.blue)
                    VStack(alignment: .leading) { Text("Telegram Manager").font(.headline); Text("Personal workspace").font(.caption).foregroundStyle(.secondary) }
                    Spacer()
                }.padding(.horizontal, 16).padding(.vertical, 22)
                Menu {
                    ForEach(model.profiles.filter { !$0.archived }) { profile in
                        Button(profile.title + (profile.active ? " ✓" : "")) { if !profile.active { model.switchProfile(profile) } }.disabled(model.busy)
                    }
                    Divider(); Button("Manage Accounts…") { model.screen = .accounts }
                } label: { Label(model.activeProfile?.title ?? "Choose Account", systemImage: "person.crop.circle") }.padding(.horizontal, 16).padding(.bottom, 12).accessibilityIdentifier("accountSwitcher")
                List(Screen.allCases, selection: $model.screen) { screen in Label(screen.rawValue, systemImage: screen.symbol).tag(screen).padding(.vertical, 4) }
                    .listStyle(.sidebar).accessibilityIdentifier("workspaceSidebar")
                VStack(alignment: .leading, spacing: 6) {
                    Label(model.connected ? "Account connected" : model.backendOnline ? "Account not connected" : "Backend unavailable", systemImage: model.connected ? "checkmark.circle.fill" : "circle.dotted")
                        .font(.caption).foregroundStyle(model.connected ? .green : .secondary)
                    Text(model.activeProfile?.title ?? "Explicit account selection.").font(.caption2).foregroundStyle(.secondary)
                }.frame(maxWidth: .infinity, alignment: .leading).padding(16)
            }.navigationSplitViewColumnWidth(min: 210, ideal: 235, max: 280)
        } detail: {
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
                    case .chats: ChatsView(model: model)
                    case .accounts: AccountsView(model: model)
                    case .drafts: DraftsView(model: model)
                    case .activity: ActivityView(model: model)
                    case .groups: GroupsView(model: model, inspectionMode: false)
                    case .permissions: GroupsView(model: model, inspectionMode: true)
                    case .composer: ComposerView(model: model)
                    case .destinations: DestinationsView(model: model)
                    case .history: HistoryView(model: model)
                    case .settings: SettingsView(model: model)
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .navigationTitle(model.screen.rawValue)
            .toolbar {
                ToolbarItem {
                    if #available(macOS 26.0, *) {
                        Label(model.backendOnline ? "Backend ready" : "Backend offline", systemImage: model.backendOnline ? "circle.fill" : "circle.dotted")
                            .font(.caption).foregroundStyle(model.backendOnline ? .green : .secondary)
                            .padding(.horizontal, 10).padding(.vertical, 6).glassEffect()
                    }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button { model.retryConnection() } label: { Label(model.connected ? "Restore Session" : "Connect", systemImage: "bolt.horizontal.circle") }
                        .disabled(model.busy || model.isConnecting || !model.connectionActionAvailable).help("Restore the saved session or continue secure setup").accessibilityIdentifier("connectBackend")
                }
                ToolbarItem { Button { model.discover() } label: { Label("Discover", systemImage: "arrow.clockwise") }.disabled(!model.connected || model.busy).help("Refresh lightweight group metadata; never sends messages") }
            }
        }
        .alert("Operation needs attention", isPresented: Binding(get: { model.errorMessage != nil }, set: { if !$0 { model.dismissError() } })) {
            Button("OK") { model.dismissError() }
        } message: { Text(model.errorMessage ?? "") }
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
                    Image(systemName: "paperplane").font(.system(size: 44, weight: .light)).foregroundStyle(.blue.opacity(0.7)).padding()
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
                    ForEach(Array(model.activity.prefix(8).enumerated()), id: \.offset) { _, text in Label(text, systemImage: "clock").font(.callout) }
                }
                Text("Text-posting permission is not permission to advertise. Always follow group rules.").font(.caption).foregroundStyle(.secondary)
            }.padding(28)
        }.background(Color(nsColor: .windowBackgroundColor))
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
