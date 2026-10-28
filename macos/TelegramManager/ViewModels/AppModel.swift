import Foundation
import SwiftUI
import UniformTypeIdentifiers
import AppKit
import UserNotifications

enum Screen: String, CaseIterable, Identifiable {
    case dashboard = "Dashboard", groups = "Groups", permissions = "Permissions", composer = "Composer", destinations = "Destinations", history = "History", settings = "Settings"
    var id: String { rawValue }
    var symbol: String {
        switch self { case .dashboard: return "square.grid.2x2"; case .groups: return "person.3"; case .permissions: return "checkmark.shield"; case .composer: return "square.and.pencil"; case .destinations: return "checkmark.seal"; case .history: return "clock.arrow.circlepath"; case .settings: return "gearshape" }
    }
}

@MainActor final class AppModel: ObservableObject {
    let backend: BackendClient
    init(backend: BackendClient = BackendClient()) { self.backend = backend }
    @Published var screen: Screen = .dashboard
    @Published var status: JSONValue = .object([:])
    @Published var settings: JSONValue = .object([:])
    @Published var groups: [TelegramGroup] = []
    @Published var approvals: [TelegramGroup] = []
    @Published var deliveries: [Delivery] = []
    @Published var selectedGroup: Int?
    @Published var detail: TelegramGroup?
    @Published var search = ""
    @Published var permissionFilter = "all"
    @Published var kindFilter = "all"
    @Published var sort = "name"
    @Published var page = 0
    @Published var totalGroups = 0
    @Published var draft = ""
    @Published var draftSaved = ""
    @Published var destination: Int?
    @Published var preview: JSONValue?
    @Published var confirmation = ""
    @Published var busy = false
    @Published var operation = ""
    @Published var progress = ""
    @Published var errorMessage: String?
    @Published var activity: [String] = []
    @Published var backendOnline = false
    @Published var authStage = ""
    @Published var authAccount = 0
    @Published var inspectionLimit = 10
    @Published var selectedInspection: Set<Int> = []
    @Published var historySearch = ""
    @Published var approvedSearch = ""
    private var queryTask: Task<Void, Never>?
    private var operationTask: Task<Void, Never>?
    private var started = false
    private var draftLoaded = false
    private var savedDraftMessage = ""
    private var previewRevision = 0
    private var authenticationRevision = 0
    var canInspect: Bool { connected && !busy && (selectedInspection.isEmpty || selectedInspection.count <= inspectionLimit) }
    var draftDirty: Bool { draft != savedDraftMessage }
    let pageSize = 50

    var connected: Bool { status["connected"].bool }
    var accountName: String { safeDisplay(status["account"]["display_name"].string) }
    var accountID: Int { status["account"]["id"].int != 0 ? status["account"]["id"].int : status["bound_account_id"].int }
    var validation: String? { ComposerValidation.error(draft) }
    var canPreview: Bool { validation == nil && destination != nil && connected && !busy }
    var canSend: Bool {
        guard let preview else { return false }
        return confirmation == preview["confirmation"].string && !confirmation.isEmpty && !busy && connected
            && preview["message"].string == draft && preview["destination"].int == destination
            && preview["expires_at"].doubleValue > Date().timeIntervalSince1970
    }

    func start() {
        guard !started else { return }; started = true
        if ProcessInfo.processInfo.environment["TGM_TEST_MODE"] == "1" { return }
        operationTask = Task { [weak self] in
            guard let self else { return }
            await backend.setEventHandler { [weak self] event in Task { @MainActor [weak self] in self?.handle(event) } }
            await run("Starting backend") {
                _ = try await self.backend.request("health")
                self.backendOnline = true
                await self.refreshStatus()
                if self.accountID != 0 { await self.loadGroups() }
                if ProcessInfo.processInfo.environment["TGM_NO_AUTO_CONNECT"] != "1" && (UserDefaults.standard.object(forKey: "connectAtLaunch") == nil || UserDefaults.standard.bool(forKey: "connectAtLaunch")) {
                    let connection = try await self.backend.request("connect")
                    try Task.checkCancellation()
                    self.acceptAuth(connection)
                }
                await self.refreshAll()
            }
        }
    }

    func reconnect() {
        operationTask = Task { await run("Restoring session") {
            let value = try await self.backend.request("connect")
            try Task.checkCancellation()
            self.acceptAuth(value); self.backendOnline = true
            await self.refreshAll()
        } }
    }
    private func acceptAuth(_ value: JSONValue) {
        authStage = value["auth_stage"].string
        authAccount = value["account"]["id"].int != 0 ? value["account"]["id"].int : value["account_id"].int
        if authStage == "connected" { authStage = "" }
    }
    func authenticate(_ method: String, params: [String: JSONValue]) {
        let revision = authenticationRevision
        operationTask = Task { await run("Authenticating") {
            let value = try await self.backend.request(method, params: params)
            guard revision == self.authenticationRevision && !Task.isCancelled else { return }
            self.status = value
            self.acceptAuth(value)
            if self.connected { self.authStage = ""; await self.refreshAll() }
        } }
    }
    func cancelAuthentication() {
        authenticationRevision += 1
        authStage = ""
        operationTask?.cancel()
        Task { await backend.cancelCurrent() }
    }
    func dismissError() { errorMessage = nil }
    func handle(_ event: JSONValue) {
        if event["event"].string == "backend_stopped" {
            backendOnline = false; busy = false; operation = ""; preview = nil; confirmation = ""
            var disconnected = status.object
            disconnected["connected"] = .bool(false)
            status = .object(disconnected)
            authStage = ""
            errorMessage = event["data"]["error"]["message"].string.isEmpty ? BackendFailure.disconnected.message : safeDisplay(event["data"]["error"]["message"].string)
            return
        }
        let data = event["data"]
        if event["event"].string == "progress" {
            let phase = data["phase"].string
            let index = data["index"].int
            let name = safeDisplay(data["group"]["name"].string)
            progress = "\(phase.capitalized) · \(index)\(name.isEmpty ? "" : " · " + name)"
        }
    }
    func addActivity(_ text: String) { activity.insert(safeDisplay(text), at: 0); if activity.count > 30 { activity.removeLast() } }
    func run(_ title: String, action: @escaping @MainActor () async throws -> Void) async {
        guard !busy else { return }
        busy = true; operation = title; progress = ""
        defer { busy = false; operation = "" }
        do { try await action(); addActivity(title + " completed"); notify(title + " completed") }
        catch is CancellationError { addActivity(title + " cancelled; saved progress retained") }
        catch {
            errorMessage = error.localizedDescription; addActivity(title + " stopped")
            // These are backend responses, so reload committed progress/cooldowns locally.
            // Transport failures must not implicitly start another backend or replay work.
            if backendOnline, let failure = error as? BackendFailure,
               ["cooldown", "io", "authorization_expired", "not_connected"].contains(failure.code) {
                await refreshStatus()
            }
        }
    }
    func refreshStatus() async {
        do {
            status = try await backend.request("status")
            if !connected && !status["auth_stage"].string.isEmpty { authStage = status["auth_stage"].string }
        } catch is CancellationError { } catch { if backendOnline { errorMessage = error.localizedDescription } }
    }
    func refreshAll() async {
        await refreshStatus()
        await loadGroups(); await loadApprovals(); await loadHistory()
        if accountID != 0 && !draftLoaded {
            let revision = previewRevision
            if let value = try? await backend.request("draft.get") {
                savedDraftMessage = value["message"].string
                if draft.isEmpty && revision == previewRevision { draft = savedDraftMessage }
                draftSaved = value["updated_at"].string
                draftLoaded = true
            }
        }
        if let value = try? await backend.request("settings") { settings = value; if value["inspection_limit"].int > 0 { inspectionLimit = value["inspection_limit"].int } }
    }
    func scheduleSearch() {
        page = 0
        queryTask?.cancel()
        queryTask = Task { try? await Task.sleep(nanoseconds: 250_000_000); guard !Task.isCancelled else { return }; await loadGroups() }
    }
    func loadGroups() async {
        guard accountID != 0 else { groups = []; totalGroups = 0; return }
        do {
            let result = try await backend.request("groups", params: ["query": .string(search), "permission": .string(permissionFilter), "kind": .string(kindFilter), "sort": .string(sort), "page": .integer(page), "size": .integer(pageSize)])
            guard !Task.isCancelled else { return }
            groups = result["groups"].array.map(TelegramGroup.init)
            totalGroups = result["total"].int
        } catch is CancellationError { } catch { if backendOnline { errorMessage = error.localizedDescription } }
    }
    func select(_ id: Int?) {
        selectedGroup = id
        guard let id else { detail = nil; return }
        Task {
            do {
                let value = try await backend.request("detail", params: ["destination": .integer(id)])
                if selectedGroup == id { detail = TelegramGroup(data: value["group"]) }
            } catch { errorMessage = error.localizedDescription }
        }
    }
    func discover() {
        operationTask = Task { await run("Discovering groups") {
            _ = try await self.backend.request("discover", timeout: 600)
            await self.refreshStatus(); await self.loadGroups()
        } }
    }
    func inspect(_ id: Int) {
        operationTask = Task { await run("Inspecting permissions") {
            let result = try await self.backend.request("inspect", params: ["destination": .integer(id)], timeout: 180)
            if self.selectedGroup == id { self.detail = TelegramGroup(data: result["group"]) }
            await self.refreshStatus(); await self.loadGroups(); await self.loadApprovals()
        } }
    }
    func inspectPending() {
        guard canInspect else { errorMessage = "Select no more groups than the inspection batch limit."; return }
        let selection = selectedInspection
        operationTask = Task { await run("Inspecting selected / pending groups") {
            var params: [String: JSONValue] = ["limit": .integer(self.inspectionLimit), "force": .bool(false)]
            if !selection.isEmpty { params["destinations"] = .array(selection.sorted().map(JSONValue.integer)) }
            _ = try await self.backend.request("inspect_pending", params: params, timeout: 600)
            await self.refreshStatus(); await self.loadGroups()
        } }
    }
    func cancelOperation() { operationTask?.cancel(); Task { await backend.cancelCurrent() } }
    func loadApprovals() async {
        guard accountID != 0 else { approvals = []; return }
        if let value = try? await backend.request("approvals", params: ["query": .string(approvedSearch)]) { approvals = value["groups"].array.map(TelegramGroup.init) }
    }
    func setApproval(_ id: Int, approved: Bool) {
        Task { await run(approved ? "Approving destination" : "Revoking approval") {
            _ = try await self.backend.request("approval.set", params: ["destination": .integer(id), "approved": .bool(approved)])
            if !approved && self.destination == id { self.destination = nil; self.invalidatePreview() }
            await self.loadApprovals()
        } }
    }
    func saveDraft() {
        let message = draft
        invalidatePreview()
        Task { await run("Saving draft") {
            let result = try await self.backend.request("draft.save", params: ["message": .string(message)])
            self.savedDraftMessage = message
            self.draftSaved = result["updated_at"].string
        } }
    }
    func importMessage() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.plainText]; panel.allowsMultipleSelection = false; panel.canChooseDirectories = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task {
            do {
                let text = try await Task.detached {
                    try readBoundedUTF8File(url)
                }.value
                draft = text; invalidatePreview()
            } catch { errorMessage = "Could not import that UTF-8 text file. Check its encoding, size and file permissions." }
        }
    }
    func invalidatePreview() { previewRevision += 1; preview = nil; confirmation = "" }
    func preparePreview() {
        guard let destination else { return }
        let message = draft, revision = previewRevision
        Task { await run("Verifying destination") {
            let value = try await self.backend.request("preview", params: ["destination": .integer(destination), "message": .string(message)])
            guard self.draft == message && self.destination == destination && self.previewRevision == revision else { self.invalidatePreview(); return }
            self.preview = value
            self.confirmation = ""
        } }
    }
    func sendConfirmed() {
        guard canSend, let preview else { return }
        let token = preview["token"].string, exactConfirmation = confirmation
        // Discard local standing approval before submission. No retry after error/timeout.
        invalidatePreview()
        operationTask = Task { await run("Sending one approved message") {
            let result = try await self.backend.request("send", params: ["token": .string(token), "confirmation": .string(exactConfirmation)], timeout: 180)
            self.addActivity(result["message"].string)
            await self.refreshStatus(); await self.loadHistory()
        } }
    }
    func loadHistory() async {
        guard accountID != 0 else { deliveries = []; return }
        if let value = try? await backend.request("history", params: ["query": .string(historySearch)]) { deliveries = value["deliveries"].array.map(Delivery.init) }
    }
    func updateSettings(basic: Int, permissions: Int, members: Int, metadata: Int) {
        Task { await run("Saving preferences") {
            self.settings = try await self.backend.request("settings.update", params: [
                "cache_policy": .object(["basic": .integer(basic), "permissions": .integer(permissions), "members": .integer(members), "metadata": .integer(metadata)]),
                "inspection_limit": .integer(self.inspectionLimit)])
        } }
    }
    func exportMaintenance(diagnostics: Bool) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = diagnostics ? "TelegramManager-diagnostics.json" : "TelegramManager-private-backup.sqlite3"
        panel.message = diagnostics ? "Exports sanitized version, schema and status information only. No credentials, sessions or message content." : "This database contains private metadata, drafts and delivery previews. Save it only in a private location. Session credentials are not included."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task { await run(diagnostics ? "Exporting safe diagnostics" : "Creating private database backup") {
            _ = try await self.backend.request(diagnostics ? "diagnostics.export" : "storage.backup", params: ["destination": .string(url.path)])
        } }
    }
    private func notify(_ message: String) {
        guard ProcessInfo.processInfo.environment["TGM_TEST_MODE"] != "1", UserDefaults.standard.bool(forKey: "notificationsEnabled") else { return }
        let content = UNMutableNotificationContent()
        content.title = "Telegram Group Manager"
        content.body = message
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)) { _ in }
    }
    func shutdown() async { queryTask?.cancel(); operationTask?.cancel(); await backend.shutdown() }
}
