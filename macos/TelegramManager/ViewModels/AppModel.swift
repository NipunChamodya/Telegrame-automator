import Foundation
import SwiftUI
import UniformTypeIdentifiers
import AppKit
import UserNotifications

enum Screen: String, CaseIterable, Identifiable {
    case dashboard = "Dashboard", chats = "Chats", groups = "Groups", permissions = "Permissions", composer = "Composer", drafts = "Drafts", destinations = "Destinations", history = "History", activity = "Activity", accounts = "Accounts", settings = "Settings"
    var id: String { rawValue }
    var symbol: String {
        switch self { case .dashboard: return "square.grid.2x2"; case .chats: return "bubble.left.and.bubble.right"; case .accounts: return "person.crop.circle.badge.checkmark"; case .drafts: return "doc.text"; case .activity: return "waveform.path.ecg"; case .groups: return "person.3"; case .permissions: return "checkmark.shield"; case .composer: return "square.and.pencil"; case .destinations: return "checkmark.seal"; case .history: return "clock.arrow.circlepath"; case .settings: return "gearshape" }
    }
}

@MainActor final class AppModel: ObservableObject {
    let backend: BackendClient
    init(backend: BackendClient = BackendClient()) { self.backend = backend }
    @Published var screen: Screen = .dashboard
    @Published var status: JSONValue = .object([:])
    @Published var settings: JSONValue = .object([:])
    @Published var groups: [TelegramGroup] = []
    @Published var profiles: [AccountProfile] = []
    @Published var chats: [ChatSummary] = []
    @Published var chatMessages: [ChatMessage] = []
    @Published var selectedChat: ChatSummary?
    @Published var chatDrafts: [JSONValue] = []
    @Published var chatQuery = ""
    @Published var chatKind = "all"
    @Published var chatPage = 0
    @Published var chatTotal = 0
    @Published var chatRefreshCursor: Int?
    @Published var localLabels: [JSONValue] = []
    @Published var chatDraft = ""
    @Published var chatDraftSaved = ""
    @Published var chatReply: Int?
    @Published var chatPreview: JSONValue?
    @Published var chatConfirmation = ""
    @Published var nextMessageOffset = 0
    @Published var hasMoreMessages = false
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
    @Published private(set) var isConnecting = false
    @Published private(set) var connectionFailureCode = ""
    @Published var diagnosticsPresented = false
    @Published private var processDiagnostics = "Managed process details have not been requested."
    private var shuttingDown = false
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
    private var accountEpoch = 0
    private var conversationRevision = 0
    private var chatPreviewRevision = 0
    private var conversationTask: Task<Void, Never>?
    private var draftAutoTask: Task<Void, Never>?
    private var chatAutoTask: Task<Void, Never>?
    private var savedChatMessage = ""
    private var suppressAuthenticationPrompts = false
    var activeProfileID: String { status["profile_id"].string }
    var activeProfile: AccountProfile? { profiles.first { $0.id == activeProfileID } }
    var chatCanPreview: Bool { connected && !busy && selectedChat?.allowsPersonalSend == true && ComposerValidation.error(chatDraft) == nil }
    var chatCanSend: Bool {
        guard let preview = chatPreview, let chat = selectedChat else { return false }
        return connected && !busy && preview["message"].string == chatDraft && preview["destination"].int == chat.id
            && preview["account_id"].int == accountID && preview["reply_to"].int == (chatReply ?? 0) && preview["expires_at"].doubleValue > Date().timeIntervalSince1970
            && !chatConfirmation.isEmpty && chatConfirmation == preview["confirmation"].string
    }
    var canInspect: Bool { connected && !busy && (selectedInspection.isEmpty || selectedInspection.count <= inspectionLimit) }
    var draftDirty: Bool { draft != savedDraftMessage }
    let pageSize = 50

    var connected: Bool { backendOnline && status["connected"].bool }
    var connectionTitle: String {
        if isConnecting { return "Connecting" }
        if connectionFailureCode == "already_running" { return "Another instance is running" }
        if !backendOnline { return "Backend unavailable" }
        if status["cooldown_until"].doubleValue > Date().timeIntervalSince1970 { return "Telegram cooldown active" }
        if ["credentials", "phone", "code", "password", "bind_account"].contains(authStage)
            || ["credentials", "phone", "code", "password", "bind_account"].contains(status["auth_stage"].string) { return "Telegram authentication required" }
        if connectionFailureCode == "io" && !connected { return "Telegram connection interrupted" }
        return connected ? "Connected" : "Disconnected"
    }
    var connectionSymbol: String {
        if isConnecting { return "arrow.triangle.2.circlepath" }
        if connectionFailureCode == "already_running" { return "lock.circle" }
        if !backendOnline { return "exclamationmark.triangle" }
        if status["cooldown_until"].doubleValue > Date().timeIntervalSince1970 { return "hourglass" }
        return connected ? "checkmark.circle.fill" : "bolt.slash.circle"
    }
    var connectionExplanation: String {
        if isConnecting { return "Starting one managed backend and checking the saved session. You can cancel this attempt." }
        if connectionFailureCode == "already_running" {
            return "Another process holds this installation’s exclusive lock. Close the other CLI or desktop instance, then retry. A leftover lock file alone does not cause this conflict; do not delete it."
        }
        if !backendOnline { return "The local Python backend is not ready. Retry once to restart only this app’s managed child, or view diagnostics for runtime and ownership guidance. Your editor text and saved records are retained." }
        if status["cooldown_until"].doubleValue > Date().timeIntervalSince1970 { return "Telegram requested a wait. Saved progress is retained; resume explicitly after the displayed deadline." }
        if connectionTitle == "Telegram authentication required" { return "Complete the secure login steps for the selected account. No discovery or messages are sent during authentication." }
        if connectionFailureCode == "io" && !connected { return "The connection was interrupted. Reconnect explicitly; uncertain deliveries are never replayed." }
        return connected ? "The selected Telegram account is ready. Network operations and sends remain explicit." : "The backend is ready and cached data is available. Connect to restore this account’s Telegram authorization."
    }
    var connectionActionAvailable: Bool {
        !busy && !isConnecting && !shuttingDown && status["cooldown_until"].doubleValue <= Date().timeIntervalSince1970
    }
    var diagnosticsSummary: String {
        """
        Connection: \(connectionTitle)
        Backend process ready: \(backendOnline ? "Yes" : "No")
        Failure category: \(connectionFailureCode.isEmpty ? "None" : connectionFailureCode)

        \(processDiagnostics)

        \(connectionExplanation)

        The app never removes lock files or kills an unknown process. A lock releases when its owning process exits; an old file is harmless. Quit other Telegram Manager builds and CLI terminals before retrying.

        For a persistent conflict, inspect manager.lock with lsof from Terminal. Do not share process arguments, session files, API hashes or databases. Use Settings → Export Diagnostics when the backend is ready. If the runtime is missing, complete the project’s guided environment setup using python3 main.py, then reopen this app.
        """
    }
    func openDiagnostics() {
        diagnosticsPresented = true
        Task { processDiagnostics = await backend.localDiagnostics() }
    }
    func retryConnection() { reconnect() }
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

    private var isUIFixture: Bool {
        #if DEBUG
        return ProcessInfo.processInfo.environment["TGM_UI_FIXTURE"] == "1"
        #else
        return false
        #endif
    }

    func start() {
        guard !started else { return }; started = true
        #if DEBUG
        if ProcessInfo.processInfo.environment["TGM_UI_FIXTURE"] == "1" { loadUIFixture(); return }
        #endif
        if ProcessInfo.processInfo.environment["TGM_TEST_MODE"] == "1" { return }
        isConnecting = true
        operationTask = Task { [weak self] in
            guard let self else { return }
            defer { self.isConnecting = false }
            await backend.setEventHandler { [weak self] event in Task { @MainActor [weak self] in self?.handle(event) } }
            await run("Starting backend") {
                try await self.backend.start()
                _ = try await self.backend.request("health")
                self.backendOnline = true
                self.connectionFailureCode = ""
                await self.refreshStatus()
                if self.accountID != 0 { await self.loadGroups() }
                if ProcessInfo.processInfo.environment["TGM_NO_AUTO_CONNECT"] != "1" && (UserDefaults.standard.object(forKey: "connectAtLaunch") == nil || UserDefaults.standard.bool(forKey: "connectAtLaunch")) {
                    let connection = try await self.backend.request("connect")
                    try Task.checkCancellation()
                    self.status = connection; self.acceptAuth(connection)
                }
                await self.refreshAll()
            }
        }
    }

    func reconnect() {
        guard connectionActionAvailable else { return }
        suppressAuthenticationPrompts = false
        isConnecting = true
        operationTask = Task {
            defer { self.isConnecting = false }
            await backend.setEventHandler { [weak self] event in Task { @MainActor [weak self] in self?.handle(event) } }
            await run("Restoring session") {
                if !self.backendOnline {
                    self.queryTask?.cancel(); self.draftAutoTask?.cancel(); self.chatAutoTask?.cancel()
                    try await self.backend.restart()
                }
                _ = try await self.backend.request("health")
                self.backendOnline = true; self.connectionFailureCode = ""
                await self.refreshAll()
                let value = try await self.backend.request("connect")
                try Task.checkCancellation()
                self.status = value; self.acceptAuth(value)
                await self.refreshAll()
            }
        }
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
            guard !shuttingDown && !isConnecting else { return }
            connectionFailureCode = event["data"]["error"]["code"].string
            backendOnline = false; busy = false; operation = ""; preview = nil; confirmation = ""
            var disconnected = status.object
            disconnected["connected"] = .bool(false)
            status = .object(disconnected)
            authStage = ""
            invalidateChatPreview()
            errorMessage = event["data"]["error"]["message"].string.isEmpty ? BackendFailure.disconnected.message : safeDisplay(event["data"]["error"]["message"].string)
            return
        }
        let data = event["data"]
        if !data["profile_id"].string.isEmpty && data["profile_id"].string != activeProfileID { return }
        if data["account_generation"] != .null && data["account_generation"].int != status["account_generation"].int { return }
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
            if let failure = error as? BackendFailure {
                let transport = ["already_running", "backend_unavailable", "runtime_missing", "launch_failed", "protocol_error", "startup", "shutting_down", "backend_stopping", "pipe_setup"]
                if transport.contains(failure.code) {
                    connectionFailureCode = failure.code; backendOnline = false
                    invalidatePreview(); invalidateChatPreview()
                } else if ["io", "not_connected", "authorization_expired"].contains(failure.code) {
                    connectionFailureCode = failure.code
                }
            }
            // These are backend responses, so reload committed progress/cooldowns locally.
            // Transport failures must not implicitly start another backend or replay work.
            if backendOnline, let failure = error as? BackendFailure,
               ["cooldown", "io", "authorization_expired", "not_connected"].contains(failure.code) {
                await refreshStatus()
            }
        }
    }
    func refreshStatus() async {
        guard !isUIFixture else { return }
        do {
            status = try await backend.request("status")
            if !connected && !suppressAuthenticationPrompts && !status["auth_stage"].string.isEmpty { authStage = status["auth_stage"].string }
        } catch is CancellationError { } catch { if backendOnline { errorMessage = error.localizedDescription } }
    }
    func refreshAll() async {
        guard !isUIFixture else { return }
        await refreshStatus()
        await loadGroups(); await loadApprovals(); await loadHistory(); await loadAccounts(); await loadChats(); await loadChatDrafts(); await loadLabels()
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
        guard !isUIFixture else { return }
        let epoch = accountEpoch
        guard accountID != 0 else { groups = []; totalGroups = 0; return }
        do {
            let result = try await backend.request("groups", params: ["query": .string(search), "permission": .string(permissionFilter), "kind": .string(kindFilter), "sort": .string(sort), "page": .integer(page), "size": .integer(pageSize)])
            guard !Task.isCancelled && epoch == accountEpoch else { return }
            groups = result["groups"].array.map(TelegramGroup.init)
            totalGroups = result["total"].int
        } catch is CancellationError { } catch { if backendOnline { errorMessage = error.localizedDescription } }
    }
    func select(_ id: Int?) {
        selectedGroup = id
        guard let id else { detail = nil; return }
        if isUIFixture || !backendOnline { detail = groups.first { $0.id == id }; return }
        let epoch = accountEpoch
        Task {
            do {
                let value = try await backend.request("detail", params: ["destination": .integer(id)])
                if selectedGroup == id && epoch == accountEpoch { detail = TelegramGroup(data: value["group"]) }
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
        guard !isUIFixture else { return }
        let epoch = accountEpoch
        guard accountID != 0 else { approvals = []; return }
        if let value = try? await backend.request("approvals", params: ["query": .string(approvedSearch)]) { if epoch == accountEpoch { approvals = value["groups"].array.map(TelegramGroup.init) } }
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
            await self.flushAutosaves()
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
        guard !isUIFixture else { return }
        let epoch = accountEpoch
        guard accountID != 0 else { deliveries = []; return }
        if let value = try? await backend.request("history", params: ["query": .string(historySearch)]) { if epoch == accountEpoch { deliveries = value["deliveries"].array.map(Delivery.init) } }
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
    func shutdown() async {
        guard !isUIFixture else { return }
        shuttingDown = true
        queryTask?.cancel(); operationTask?.cancel(); conversationTask?.cancel()
        await operationTask?.value
        await flushAutosaves()
        if backendOnline && accountID != 0 { try? await preserveDraftsBeforeContextChange() }
        await backend.shutdown()
    }
}

extension AppModel {
    func loadAccounts() async {
        guard !isUIFixture else { return }
        if let result = try? await backend.request("accounts.list") { profiles = result["profiles"].array.map(AccountProfile.init) }
    }
    private func preserveDraftsBeforeContextChange() async throws {
        accountEpoch += 1
        queryTask?.cancel(); conversationTask?.cancel(); draftAutoTask?.cancel(); chatAutoTask?.cancel()
        await queryTask?.value; await conversationTask?.value; await draftAutoTask?.value; await chatAutoTask?.value
        guard accountID != 0 else { return }
        if draftDirty {
            _ = try await backend.request("draft.save", params: ["message": .string(draft)])
            savedDraftMessage = draft
        }
        if let chat = selectedChat {
            _ = try await backend.request("chatdraft.save", params: ["destination": .integer(chat.id), "message": .string(chatDraft)])
        }
    }
    private func clearAccountContext() {
        accountEpoch += 1
        queryTask?.cancel(); conversationTask?.cancel()
        invalidatePreview(); invalidateChatPreview()
        groups = []; approvals = []; deliveries = []; selectedGroup = nil; detail = nil
        selectedInspection = []; destination = nil; draft = ""; draftSaved = ""; draftLoaded = false; savedDraftMessage = ""
        chats = []; chatMessages = []; selectedChat = nil; localLabels = []; chatRefreshCursor = nil; chatDrafts = []; chatDraft = ""; savedChatMessage = ""; chatDraftSaved = ""; chatReply = nil
        page = 0; chatPage = 0; totalGroups = 0; chatTotal = 0; hasMoreMessages = false; nextMessageOffset = 0
        authenticationRevision += 1; authStage = ""
    }
    func switchProfile(_ profile: AccountProfile) {
        guard !busy && !profile.active && !profile.archived else { return }
        operationTask = Task { await run("Switching account") {
            try await self.preserveDraftsBeforeContextChange()
            let response = try await self.backend.request("accounts.switch", params: ["profile_id": .string(profile.id), "confirm": .bool(true)])
            self.clearAccountContext()
            self.status = response["status"]
            self.profiles = response["profiles"].array.map(AccountProfile.init)
            self.suppressAuthenticationPrompts = false
            let connected = try await self.backend.request("connect")
            self.status = connected; self.acceptAuth(connected)
            await self.refreshAll()
        } }
    }
    func addProfile(label: String) {
        guard !busy else { return }
        operationTask = Task { await run("Adding account") {
            try await self.preserveDraftsBeforeContextChange()
            let response = try await self.backend.request("accounts.add", params: ["label": .string(label), "confirm": .bool(true)])
            self.clearAccountContext(); self.status = response["status"]
            self.profiles = response["profiles"].array.map(AccountProfile.init)
            self.suppressAuthenticationPrompts = false
            let connected = try await self.backend.request("connect")
            self.status = connected; self.acceptAuth(connected)
            await self.refreshAll()
        } }
    }
    func manageProfile(_ profile: AccountProfile, action: String, confirmation: String = "") {
        guard !busy else { return }
        operationTask = Task { await run(action == "logout" ? "Logging out selected account" : action == "remove" ? "Removing local account profile" : action == "restore" ? "Restoring account profile" : "Disconnecting account") {
            if profile.active { try await self.preserveDraftsBeforeContextChange() }
            var params: [String: JSONValue] = ["profile_id": .string(profile.id)]
            if action == "logout" || action == "remove" { params["confirmation"] = .string(confirmation) }
            else { params["confirm"] = .bool(true) }
            let response = try await self.backend.request("accounts." + action, params: params)
            if profile.active { self.clearAccountContext() }
            self.profiles = response["profiles"].array.map(AccountProfile.init)
            self.status = response["status"]
            self.suppressAuthenticationPrompts = true; self.authStage = ""
            await self.refreshAll()
        } }
    }
    func loadChats() async {
        guard !isUIFixture else { return }
        guard accountID != 0 else { chats = []; chatTotal = 0; return }
        let epoch = accountEpoch
        if let value = try? await backend.request("chats.list", params: ["query": .string(chatQuery), "kind": .string(chatKind), "page": .integer(chatPage), "size": .integer(pageSize)]), epoch == accountEpoch {
            chats = value["chats"].array.map(ChatSummary.init); chatTotal = value["total"].int
        }
    }
    func refreshChats(older: Bool = false) {
        operationTask = Task { await run("Refreshing conversation list") {
            var params: [String: JSONValue] = ["limit": .integer(100)]
            if older, let cursor = self.chatRefreshCursor { params["after"] = .integer(cursor) }
            let result = try await self.backend.request("chats.refresh", params: params, timeout: 180)
            self.chatRefreshCursor = result["next_cursor"] == .null ? nil : result["next_cursor"].int
            await self.loadChats()
        } }
    }
    func openSavedMessages() {
        operationTask = Task { await run("Opening Saved Messages") {
            let result = try await self.backend.request("chats.saved")
            self.selectChat(ChatSummary(data: result["chat"]))
            self.screen = .chats
        } }
    }
    func selectChat(_ chat: ChatSummary) {
        guard !busy || operation == "Opening Saved Messages" else { return }
        let previous = selectedChat, previousText = chatDraft
        conversationTask?.cancel(); conversationRevision += 1
        invalidateChatPreview()
        let revision = conversationRevision, epoch = accountEpoch
        selectedChat = chat; chatMessages = []; chatDraft = ""; savedChatMessage = ""; chatDraftSaved = ""; chatReply = nil; hasMoreMessages = false
        conversationTask = Task {
            do {
                if let previous {
                    _ = try await backend.request("chatdraft.save", params: ["destination": .integer(previous.id), "message": .string(previousText)])
                }
                let draft = try await backend.request("chatdraft.get", params: ["destination": .integer(chat.id)])
                guard epoch == accountEpoch && revision == conversationRevision else { return }
                savedChatMessage = draft["message"].string
                if chatDraft.isEmpty { chatDraft = savedChatMessage }
                chatDraftSaved = draft["updated_at"].string
                if connected { await loadMessages() }
            } catch is CancellationError {} catch { errorMessage = error.localizedDescription }
        }
    }
    func loadMessages(older: Bool = false, search: String = "") async {
        guard let chat = selectedChat, connected else { return }
        let epoch = accountEpoch, revision = conversationRevision
        do {
            var params: [String: JSONValue] = ["destination": .integer(chat.id), "limit": .integer(50)]
            if older && nextMessageOffset > 0 { params["offset_id"] = .integer(nextMessageOffset) }
            if !search.isEmpty { params["search"] = .string(search) }
            let result = try await backend.request("messages.list", params: params, timeout: 180)
            guard epoch == accountEpoch && revision == conversationRevision else { return }
            let rows = result["messages"].array.map(ChatMessage.init)
            if older { chatMessages = Array((chatMessages + rows).prefix(200)) } else { chatMessages = rows }
            nextMessageOffset = result["next_offset_id"].int; hasMoreMessages = result["has_more"].bool && chatMessages.count < 200
        } catch is CancellationError {} catch { errorMessage = error.localizedDescription }
    }
    func loadChatDrafts() async {
        guard !isUIFixture else { return }
        guard accountID != 0 else { chatDrafts = []; return }
        let epoch = accountEpoch
        if let result = try? await backend.request("chatdraft.list"), epoch == accountEpoch { chatDrafts = result["drafts"].array }
    }
    func saveChatDraft() {
        guard let chat = selectedChat else { return }
        let message = chatDraft
        invalidateChatPreview()
        Task { await run("Saving conversation draft") {
            let result = try await self.backend.request("chatdraft.save", params: ["destination": .integer(chat.id), "message": .string(message)])
            self.chatDraftSaved = result["updated_at"].string
            await self.loadChatDrafts()
        } }
    }
    func deleteChatDraft(_ destination: Int) {
        Task { await run("Deleting saved conversation draft") {
            _ = try await self.backend.request("chatdraft.delete", params: ["destination": .integer(destination)])
            if self.selectedChat?.id == destination { self.chatDraft = ""; self.invalidateChatPreview() }
            await self.loadChatDrafts()
        } }
    }
    func invalidateChatPreview() { chatPreviewRevision += 1; chatPreview = nil; chatConfirmation = "" }
    func prepareChatPreview() {
        guard chatCanPreview, let chat = selectedChat else { return }
        let message = chatDraft, revision = chatPreviewRevision, epoch = accountEpoch, reply = chatReply
        Task { await run("Previewing personal message") {
            var params: [String: JSONValue] = ["account_id": .integer(self.accountID), "destination": .integer(chat.id), "message": .string(message)]
            if let reply { params["reply_to"] = .integer(reply) }
            await self.flushAutosaves()
            let value = try await self.backend.request("chat.preview", params: params)
            guard epoch == self.accountEpoch && revision == self.chatPreviewRevision && self.chatDraft == message && self.selectedChat?.id == chat.id && self.chatReply == reply else { return }
            self.chatPreview = value; self.chatConfirmation = ""
        } }
    }
    func sendChatConfirmed() {
        guard chatCanSend, let preview = chatPreview else { return }
        let token = preview["token"].string, confirmation = chatConfirmation, account = accountID
        invalidateChatPreview()
        operationTask = Task { await run("Sending one personal message") {
            let result = try await self.backend.request("chat.send", params: ["account_id": .integer(account), "token": .string(token), "confirmation": .string(confirmation)], timeout: 180)
            self.addActivity(result["message"].string)
            await self.loadMessages(); await self.loadHistory(); await self.refreshStatus()
        } }
    }
    func loadLabels() async {
        guard !isUIFixture else { return }
        guard accountID != 0 else { localLabels = []; return }
        let epoch = accountEpoch
        if let result = try? await backend.request("labels"), epoch == accountEpoch { localLabels = result["labels"].array }
    }
    func setGroupLabel(_ destination: Int, label: String, enabled: Bool) {
        guard !label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        let epoch = accountEpoch
        Task { await run("Updating local label") {
            _ = try await self.backend.request("label.set", params: ["destination": .integer(destination), "label": .string(label), "enabled": .bool(enabled)])
            let result = try await self.backend.request("labels")
            guard epoch == self.accountEpoch else { return }
            self.localLabels = result["labels"].array
        } }
    }
    func downloadAttachment(_ message: ChatMessage) {
        guard let chat = selectedChat, connected else { return }
        let panel = NSSavePanel(); panel.nameFieldStringValue = safeDisplay(message.data["media"]["name"].string).isEmpty ? "Telegram-attachment" : URL(fileURLWithPath: safeDisplay(message.data["media"]["name"].string)).lastPathComponent
        panel.message = "Save this existing attachment to a new local file. Downloads are limited to 64 MiB."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        operationTask = Task { await run("Downloading attachment") {
            _ = try await self.backend.request("media.download", params: ["destination": .integer(chat.id), "message_id": .integer(message.id), "path": .string(url.path)], timeout: 600)
        } }
    }
}

#if DEBUG
extension AppModel {
    private func loadUIFixture() {
        backendOnline = true
        status = .object(["connected": .bool(false), "profile_id": .string("fixture"), "bound_account_id": .integer(101), "account": .object(["id": .integer(101), "display_name": .string("Example Account")]), "overview": .object(["total": .integer(3), "allowed": .integer(1), "denied": .integer(1), "unknown": .integer(1), "pending": .integer(1)])])
        profiles = [AccountProfile(data: .object(["profile_id": .string("fixture"), "label": .string("Example Account"), "telegram_id": .integer(101), "is_active": .bool(true), "legacy": .bool(true), "auth_state": .string("disconnected")]))]
        groups = ["ශ්‍රී ලංකා Community 👩‍💻", "தமிழ் Developers", "Engineering Discussion"].enumerated().map { index, title in
            TelegramGroup(data: .object(["id": .integer(-1001 - index), "name": .string(title), "title": .string(title), "kind": .string("supergroup"), "effective_permission": .string(["allowed", "denied", "unknown"][index])]))
        }
        totalGroups = groups.count
        chats = [ChatSummary(data: .object(["id": .integer(202), "name": .string("Example Conversation"), "kind": .string("private"), "last_message": .string("A synthetic conversation preview 👋")]))]
        chatTotal = chats.count; selectedChat = chats.first
        chatMessages = [ChatMessage(data: .object(["id": .integer(1), "text": .string("Welcome! Synthetic test data.\nසිංහල · தமிழ் · 👩‍💻"), "sender_name": .string("Example Contact"), "outgoing": .bool(false)]))]
        draft = "Hello community! 👋"; chatDraft = "A personal draft"; activity = ["Synthetic fixture loaded. No Telegram connection was made."]
        let fixtureEnvironment = ProcessInfo.processInfo.environment
        if let target = fixtureEnvironment["TGM_UI_SCREEN"], let value = Screen(rawValue: target) { screen = value }
        if fixtureEnvironment["TGM_UI_EMPTY"] == "1" { groups = []; chats = []; profiles = []; selectedChat = nil; chatMessages = []; totalGroups = 0; chatTotal = 0 }
        if fixtureEnvironment["TGM_UI_INSPECTOR"] == "1" { detail = groups.first; selectedGroup = groups.first?.id }
        if let stage = fixtureEnvironment["TGM_UI_AUTH_STAGE"], ["credentials", "phone", "code", "password", "bind_account"].contains(stage) { authStage = stage; authAccount = 101 }
        if fixtureEnvironment["TGM_UI_ERROR"] == "1" { errorMessage = "The backend could not be started. Existing local data was preserved. This is a synthetic error state." }

    }
}
#endif

extension AppModel {
    private func flushAutosaves() async {
        draftAutoTask?.cancel(); chatAutoTask?.cancel()
        await draftAutoTask?.value; await chatAutoTask?.value
    }
    func scheduleDraftSave() {
        guard !isUIFixture else { return }
        draftAutoTask?.cancel()
        guard accountID != 0, backendOnline, draft != savedDraftMessage, draft.utf16.count <= 4096 else { return }
        let epoch = accountEpoch, message = draft
        draftAutoTask = Task {
            do {
                try await Task.sleep(nanoseconds: 800_000_000)
                guard !Task.isCancelled, epoch == accountEpoch, draft == message else { return }
                let result = try await backend.request("draft.save", params: ["message": .string(message)])
                guard epoch == accountEpoch, draft == message else { return }
                savedDraftMessage = message; draftSaved = result["updated_at"].string
            } catch is CancellationError {} catch { if epoch == accountEpoch { errorMessage = "Draft could not be saved. Your editor text is retained." } }
        }
    }
    func scheduleChatDraftSave() {
        guard !isUIFixture else { return }
        chatAutoTask?.cancel()
        guard let chat = selectedChat, accountID != 0, backendOnline, chatDraft != savedChatMessage, chatDraft.utf16.count <= 4096 else { return }
        let epoch = accountEpoch, message = chatDraft
        chatAutoTask = Task {
            do {
                try await Task.sleep(nanoseconds: 800_000_000)
                guard !Task.isCancelled, epoch == accountEpoch, selectedChat?.id == chat.id, chatDraft == message else { return }
                let result = try await backend.request("chatdraft.save", params: ["destination": .integer(chat.id), "message": .string(message)])
                guard epoch == accountEpoch, selectedChat?.id == chat.id, chatDraft == message else { return }
                savedChatMessage = message; chatDraftSaved = result["updated_at"].string
            } catch is CancellationError {} catch { if epoch == accountEpoch { errorMessage = "Conversation draft could not be saved. Your editor text is retained." } }
        }
    }
}
