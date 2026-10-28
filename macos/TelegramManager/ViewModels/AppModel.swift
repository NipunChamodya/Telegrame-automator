import Foundation
import SwiftUI
import UniformTypeIdentifiers
import AppKit
import UserNotifications

enum Screen: String, CaseIterable, Identifiable {
    case contacts = "Contacts"
    case chats = "Chats", groupChats = "Groups", channels = "Channels", savedMessages = "Saved Messages", advancedWorkspace = "Advanced Workspace"
    case messageOperations = "Message Actions"
    case dashboard = "Dashboard", groups = "Group Management", permissions = "Permissions", composer = "Composer", drafts = "Drafts", destinations = "Destinations", history = "History", activity = "Activity", accounts = "Accounts", settings = "Settings"
    static let messaging: [Screen] = [.chats, .contacts, .groupChats, .channels, .savedMessages]
    static let advanced: [Screen] = [.dashboard, .groups, .permissions, .composer, .drafts, .destinations, .history, .activity, .messageOperations]
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .dashboard: return "square.grid.2x2"
        case .chats: return "bubble.left.and.bubble.right"
        case .contacts: return "person.crop.rectangle.stack"
        case .groupChats, .groups: return "person.3"
        case .channels: return "megaphone"
        case .savedMessages: return "bookmark"
        case .advancedWorkspace: return "square.stack.3d.up"
        case .accounts: return "person.crop.circle.badge.checkmark"
        case .drafts: return "doc.text"
        case .activity: return "waveform.path.ecg"
        case .permissions: return "checkmark.shield"
        case .composer: return "square.and.pencil"
        case .destinations: return "checkmark.seal"
        case .history: return "clock.arrow.circlepath"
        case .messageOperations: return "pencil.and.list.clipboard"
        case .settings: return "gearshape"
        }
    }
}

@MainActor final class AppModel: ObservableObject {
    let backend: BackendClient
    init(backend: BackendClient = BackendClient()) { self.backend = backend }
    @Published var screen: Screen = .chats
    @Published var status: JSONValue = .object([:])
    @Published var settings: JSONValue = .object([:])
    @Published var groups: [TelegramGroup] = []
    @Published var profiles: [AccountProfile] = []
    @Published var chats: [ChatSummary] = []
    @Published private(set) var chatsLoading = false
    @Published private(set) var messagesLoading = false
    @Published private(set) var messagesError: String?
    @Published private(set) var contactsError: String?
    @Published private(set) var cachedLoading: Set<Screen> = []
    @Published private(set) var cachedErrors: [Screen: String] = [:]
    private var cachedRevisions: [Screen: Int] = [:]
    // Transient recovery for failed local draft writes; never shared across account/profile scopes.
    private var draftRecovery: [String: String] = [:]
    private func draftRecoveryKey(_ destination: Int) -> String { "\(activeProfileID):\(accountID):\(destination)" }
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
    @Published var composerFocusRequested = false
    @Published private(set) var liveProjection: LiveProjection?
    @Published private(set) var liveRepairNeeded = false
    @Published private(set) var liveMessage = ""
    @Published private(set) var typingDescription = ""
    @Published var messageActionTarget: MessageActionContext?
    @Published var messageActionDraft = ""
    @Published var messageActionConfirmation = ""
    @Published private(set) var messageActionOriginalText = ""
    @Published private(set) var messageActionPreview: JSONValue?
    @Published private(set) var messageActionResult: JSONValue?
    @Published private(set) var messageActionError: String?
    @Published private(set) var messageActionBusy = false
    @Published private(set) var messageActionSubmitted = false
    @Published private(set) var messageOperations: [JSONValue] = []
    @Published private(set) var contacts: [TelegramContact] = []
    @Published var contactQuery = ""
    @Published var contactPage = 0
    @Published private(set) var contactTotal = 0
    @Published private(set) var contactsLoading = false
    @Published private(set) var contactNotice = ""
    @Published var profileTarget: PeerProfile?
    @Published var foldersPresented = false
    @Published private(set) var telegramFolders: [JSONValue] = []
    @Published var mediaPreview: MediaPreviewContext?
    @Published private(set) var previewImage: NSImage?
    @Published private(set) var mediaPreviewPreparing = false
    private var contactListTask: Task<Void, Never>?
    private var contactRevision = 0
    private var mediaPreviewExpiryTask: Task<Void, Never>?
    private var heldMediaPreview: MediaPreviewContext?
    private var pendingMediaMessage: (peer: Int, message: Int)?
    private var mediaPreviewRevision = 0
    private var messageActionTask: Task<Void, Never>?
    private var messageActionExpiryTask: Task<Void, Never>?
    private var messageActionRevision = 0
    private var messageActionUnavailable = false
    private var liveWatchKey: String?
    private var pendingLiveEvents: [JSONValue] = []
    private var pendingLiveOverflow = false
    private var liveRepairTask: Task<Void, Never>?
    private var typingExpiryTask: Task<Void, Never>?
    private var typingSendTask: Task<Void, Never>?
    private var typingIdleTask: Task<Void, Never>?
    private var lastTypingSent: TimeInterval = 0
    private var typingPeer: Int?
    private var visibleIncoming: Set<Int> = []
    private var conversationFocused = false
    private var automaticReadVisibilitySupported = false
    private var readTask: Task<Void, Never>?
    private var lastReadPeer: Int?
    private var lastReadID = 0
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
    @Published var activity: [ActivityEvent] = []
    private var currentActivityID: UUID?
    private var currentActivityOutcome: ActivityStatus?
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
    private var chatListTask: Task<Void, Never>?
    private var chatListRevision = 0
    private var messageListRevision = 0
    private var activeMessageSearch = ""
    private var fixtureChatSource: [ChatSummary] = []
    private var fixtureMessageSource: [ChatMessage] = []
    #if DEBUG
    private var fixtureContactSource: [TelegramContact] = []
    private var fixtureAccountDrafts: [String: String] = [:]
    #endif
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

        The app never removes lock files or kills an unknown process. A lock releases when its owning process exits; an old file is harmless. Quit other Unofficial Telegram Manager builds and CLI terminals before retrying.

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

    var isUIFixture: Bool {
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
            defer {
                self.isConnecting = false
                if self.connected { Task { await self.ensureLiveUpdates(peer: self.selectedChat?.contentAvailable == true ? self.selectedChat?.id : nil) } }
            }
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
        resetLiveState()
        suppressAuthenticationPrompts = false
        isConnecting = true
        operationTask = Task {
            defer {
                self.isConnecting = false
                if self.connected { Task { await self.ensureLiveUpdates(peer: self.selectedChat?.contentAvailable == true ? self.selectedChat?.id : nil) } }
            }
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
            resetLiveState()
            errorMessage = event["data"]["error"]["message"].string.isEmpty ? BackendFailure.disconnected.message : safeDisplay(event["data"]["error"]["message"].string)
            return
        }
        let data = event["data"]
        if !data["profile_id"].string.isEmpty && data["profile_id"].string != activeProfileID { return }
        if data["account_generation"] != .null && data["account_generation"].int != status["account_generation"].int { return }
        if ["chat.changed", "message.changed", "message.deleted", "read.changed", "typing.changed", "sync.required"].contains(event["event"].string) {
            consumeLiveEvent(event)
            return
        }
        if event["event"].string == "progress" {
            let phase = data["phase"].string
            let index = data["index"].int
            let name = safeDisplay(data["group"]["name"].string)
            progress = "\(phase.capitalized) · \(index)\(name.isEmpty ? "" : " · " + name)"
        }
    }
    func addActivity(_ text: String) {
        ActivityHistory.insert(ActivityEvent(kind: ActivityKind.classify(text), status: .info,
            accountID: accountID == 0 ? nil : String(accountID), profileID: activeProfileID,
            accountName: accountName.isEmpty ? activeProfile?.title : accountName), into: &activity)
    }
    private func recordProcessed(_ count: Int) {
        if let id = currentActivityID { ActivityHistory.update(id: id, in: &activity, completed: count) }
    }
    private func recordDeliveryOutcome(_ result: JSONValue) {
        switch result["delivery"]["status"].string {
        case "sent": currentActivityOutcome = .succeeded
        case "rejected", "failed": currentActivityOutcome = .failed
        default: currentActivityOutcome = .warning
        }
    }
    func run(_ title: String, action: @escaping @MainActor () async throws -> Void) async {
        guard !busy else { return }
        busy = true; operation = title; progress = ""
        let event = ActivityEvent(kind: ActivityKind.classify(title), accountID: accountID == 0 ? nil : String(accountID),
                                  profileID: activeProfileID, accountName: accountName.isEmpty ? activeProfile?.title : accountName)
        ActivityHistory.insert(event, into: &activity)
        currentActivityID = event.id; currentActivityOutcome = nil
        defer { busy = false; operation = ""; currentActivityID = nil; currentActivityOutcome = nil }
        do {
            try await action()
            let outcome = currentActivityOutcome ?? .succeeded
            ActivityHistory.update(id: event.id, in: &activity, status: outcome)
            notify(event.title + " · " + outcome.title)
        }
        catch is CancellationError { ActivityHistory.update(id: event.id, in: &activity, status: .cancelled) }
        catch {
            errorMessage = error.localizedDescription
            ActivityHistory.update(id: event.id, in: &activity, status: (error as? BackendFailure)?.code == "cooldown" ? .warning : .failed)
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
        await loadGroups(); await loadApprovals(); await loadHistory(); await loadAccounts(); await loadChats(); await loadChatDrafts(); await loadLabels(); await loadContacts()
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
        if connected { await ensureLiveUpdates(peer: selectedChat?.contentAvailable == true ? selectedChat?.id : nil) }
    }
    func scheduleSearch() {
        page = 0
        queryTask?.cancel()
        queryTask = Task { try? await Task.sleep(nanoseconds: 250_000_000); guard !Task.isCancelled else { return }; await loadGroups() }
    }
    private func cachedRequest(_ method: String, screen: Screen, params: [String: JSONValue] = [:]) async -> JSONValue? {
        let epoch = accountEpoch
        let revision = (cachedRevisions[screen] ?? 0) + 1
        cachedRevisions[screen] = revision
        cachedLoading.insert(screen); cachedErrors[screen] = nil
        defer { if epoch == accountEpoch && cachedRevisions[screen] == revision { cachedLoading.remove(screen) } }
        do {
            let result = try await backend.request(method, params: params)
            guard !Task.isCancelled, epoch == accountEpoch, cachedRevisions[screen] == revision else { return nil }
            return result
        } catch is CancellationError { return nil }
        catch {
            if !Task.isCancelled, epoch == accountEpoch, cachedRevisions[screen] == revision { cachedErrors[screen] = error.localizedDescription }
            return nil
        }
    }
    func loadGroups() async {
        guard !isUIFixture else { return }
        guard accountID != 0 else { groups = []; totalGroups = 0; return }
        let query = search, permission = permissionFilter, kind = kindFilter, ordering = sort, requestedPage = page
        let target: Screen = screen == .permissions ? .permissions : .groups
        if let result = await cachedRequest("groups", screen: target, params: ["query": .string(query), "permission": .string(permission), "kind": .string(kind), "sort": .string(ordering), "page": .integer(requestedPage), "size": .integer(pageSize)]),
           query == search, permission == permissionFilter, kind == kindFilter, ordering == sort, requestedPage == page {
            groups = result["groups"].array.map(TelegramGroup.init)
            totalGroups = result["total"].int
        }
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
            let result = try await self.backend.request("discover", timeout: 600)
            self.recordProcessed(result["processed"].int)
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
            let result = try await self.backend.request("inspect_pending", params: params, timeout: 600)
            self.recordProcessed(result["inspected"].int)
            await self.refreshStatus(); await self.loadGroups()
        } }
    }
    func cancelOperation() { operationTask?.cancel(); Task { await backend.cancelCurrent() } }
    func loadApprovals() async {
        guard !isUIFixture else { return }
        guard accountID != 0 else { approvals = []; return }
        let query = approvedSearch
        if let value = await cachedRequest("approvals", screen: .destinations, params: ["query": .string(query)]), query == approvedSearch {
            approvals = value["groups"].array.map(TelegramGroup.init)
        }
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
            self.recordDeliveryOutcome(result)
            await self.refreshStatus(); await self.loadHistory()
        } }
    }
    func loadHistory() async {
        guard !isUIFixture else { return }
        guard accountID != 0 else { deliveries = []; return }
        let query = historySearch
        if let value = await cachedRequest("history", screen: .history, params: ["query": .string(query)]), query == historySearch {
            deliveries = value["deliveries"].array.map(Delivery.init)
        }
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
        content.title = "Unofficial Telegram Manager"
        content.body = message
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)) { _ in }
    }
    func shutdown() async {
        guard !isUIFixture else { return }
        shuttingDown = true
        queryTask?.cancel(); chatListTask?.cancel(); operationTask?.cancel(); conversationTask?.cancel()
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
        liveRepairTask?.cancel(); messageActionTask?.cancel(); contactListTask?.cancel()
        accountEpoch += 1
        queryTask?.cancel(); chatListTask?.cancel(); conversationTask?.cancel(); draftAutoTask?.cancel(); chatAutoTask?.cancel()
        await queryTask?.value; await chatListTask?.value; await conversationTask?.value; await draftAutoTask?.value; await chatAutoTask?.value; await liveRepairTask?.value; await messageActionTask?.value; await contactListTask?.value
        await stopLiveUpdates()
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
        resetLiveState()
        accountEpoch += 1
        queryTask?.cancel(); chatListTask?.cancel(); conversationTask?.cancel()
        chatListRevision += 1; messageListRevision += 1
        chatsLoading = false; messagesLoading = false; messagesError = nil; contactsError = nil; cachedLoading = []; cachedErrors = [:]; activeMessageSearch = ""
        invalidatePreview(); invalidateChatPreview()
        groups = []; approvals = []; deliveries = []; messageOperations = []; contacts = []; contactPage = 0; contactTotal = 0; contactNotice = ""; telegramFolders = []; profileTarget = nil; foldersPresented = false; selectedGroup = nil; detail = nil
        selectedInspection = []; destination = nil; draft = ""; draftSaved = ""; draftLoaded = false; savedDraftMessage = ""
        chats = []; chatMessages = []; selectedChat = nil; localLabels = []; chatRefreshCursor = nil; chatDrafts = []; chatDraft = ""; savedChatMessage = ""; chatDraftSaved = ""; chatReply = nil
        page = 0; chatPage = 0; totalGroups = 0; chatTotal = 0; hasMoreMessages = false; nextMessageOffset = 0
        authenticationRevision += 1; authStage = ""
    }
    func switchProfile(_ profile: AccountProfile) {
        guard !busy && !profile.active && !profile.archived else { return }
        #if DEBUG
        if isUIFixture {
            fixtureAccountDrafts[activeProfileID] = chatDraft
            let allProfiles = profiles
            if profile.id == "fixture" { loadUIFixture() }
            else {
                clearAccountContext(); fixtureChatSource = []; fixtureMessageSource = []; chats = []; chatTotal = 0
                status = .object(["connected": .bool(false), "profile_id": .string(profile.id), "bound_account_id": .integer(102), "account": .object(["id": .integer(102), "display_name": .string(profile.title)])])
            }
            profiles = allProfiles.map { item in
                var fields: [String: JSONValue] = [:]; if case .object(let value) = item.data { fields = value }; fields["is_active"] = .bool(item.id == profile.id)
                return AccountProfile(data: .object(fields))
            }
            chatDraft = fixtureAccountDrafts[profile.id] ?? ""
            return
        }
        #endif
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
            if action == "remove" { self.draftRecovery = self.draftRecovery.filter { !$0.key.hasPrefix(profile.id + ":") } }
            self.profiles = response["profiles"].array.map(AccountProfile.init)
            self.status = response["status"]
            self.suppressAuthenticationPrompts = true; self.authStage = ""
            await self.refreshAll()
        } }
    }
    func composePersonalMessage() {
        navigate(to: .chats)
        composerFocusRequested = true
    }
    func restoreNavigation(to destination: Screen) {
        screen = destination
        chatKind = destination == .groupChats ? "groups" : destination == .channels ? "channel" : "all"
        chatPage = 0
    }
    func navigate(to destination: Screen) {
        screen = destination
        guard !busy else { return }
        if destination == .savedMessages { openSavedMessages(); return }
        if [.chats, .groupChats, .channels].contains(destination) {
            chatKind = destination == .groupChats ? "groups" : destination == .channels ? "channel" : "all"
            chatPage = 0
            Task { await loadChats() }
        }
    }
    func scheduleChatSearch() {
        chatPage = 0
        chatListTask?.cancel()
        chatListTask = Task {
            do { try await Task.sleep(nanoseconds: 250_000_000) }
            catch { return }
            guard !Task.isCancelled else { return }
            await loadChats()
        }
    }
    func loadChats() async {
        guard accountID != 0 else { chats = []; chatTotal = 0; return }
        chatListRevision += 1
        let revision = chatListRevision, epoch = accountEpoch
        let query = chatQuery, kind = chatKind, page = chatPage
        chatsLoading = true
        defer { if revision == chatListRevision { chatsLoading = false } }
        if isUIFixture {
            let filtered = fixtureChatSource.filter {
                (kind == "all" || (kind == "groups" && ["group", "supergroup"].contains($0.kind)) || $0.kind == kind) && (query.isEmpty || ($0.title + " " + $0.data["username"].string + " " + String($0.id)).localizedCaseInsensitiveContains(query))
            }
            chatTotal = filtered.count
            chats = Array(filtered.dropFirst(max(0, page) * pageSize).prefix(pageSize))
            return
        }
        if let value = await cachedRequest("chats.list", screen: screen == .channels ? .channels : screen == .groupChats ? .groupChats : .chats, params: ["query": .string(query), "kind": .string(kind), "page": .integer(page), "size": .integer(pageSize), "sort": .string("recent")]), !Task.isCancelled, epoch == accountEpoch, revision == chatListRevision, query == chatQuery, kind == chatKind, page == chatPage {
            chats = value["chats"].array.map(ChatSummary.init); chatTotal = value["total"].int
            if let selected = selectedChat, let refreshed = chats.first(where: { $0.id == selected.id }) {
                selectedChat = refreshed
                if !refreshed.contentAvailable { closeMediaPreview(); chatMessages = []; chatReply = nil; visibleIncoming = []; invalidateChatPreview(); liveProjection?.messages = [:] }
            }
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
        if isUIFixture {
            selectedChat = ChatSummary(data: .object(["id": .integer(accountID), "name": .string("Saved Messages"), "content_available": .bool(true), "kind": .string("saved")]))
            chatMessages = fixtureMessageSource; screen = .savedMessages; return
        }
        operationTask = Task { await run("Opening Saved Messages") {
            let result = try await self.backend.request("chats.saved")
            self.selectChat(ChatSummary(data: result["chat"]))
            self.screen = .savedMessages
        } }
    }
    func selectChat(_ chat: ChatSummary) {
        guard !busy || operation == "Opening Saved Messages" else { return }
        guard selectedChat?.id != chat.id else { return }
        let recoveryKey = draftRecoveryKey(chat.id)
        let previousKey = selectedChat.map { draftRecoveryKey($0.id) }
        if let previousKey, chatDraft != savedChatMessage {
            guard chatDraft.utf16.count <= 4096 else {
                errorMessage = "Shorten the draft to 4096 UTF-16 units before opening another conversation. Your editor text was retained."
                return
            }
            guard draftRecovery[previousKey] != nil || draftRecovery.count < 100 else {
                errorMessage = "Save the current draft before opening another conversation. The unsaved recovery buffer is full."
                return
            }
            draftRecovery[previousKey] = chatDraft
        }
        setConversationFocused(false)
        visibleIncoming = []; lastReadPeer = nil; lastReadID = 0
        let previous = selectedChat, previousText = chatDraft
        conversationTask?.cancel(); conversationRevision += 1
        invalidateChatPreview()
        let revision = conversationRevision, epoch = accountEpoch
        selectedChat = chat; chatMessages = []; chatDraft = draftRecovery[recoveryKey] ?? ""; savedChatMessage = ""; chatDraftSaved = ""; chatReply = nil; hasMoreMessages = false
        activeMessageSearch = ""; messageListRevision += 1; messagesLoading = false; messagesError = nil
        if !chat.contentAvailable {
            if let previous, !isUIFixture {
                conversationTask = Task {
                    do {
                        _ = try await backend.request("chatdraft.save", params: ["destination": .integer(previous.id), "message": .string(previousText)])
                        if let previousKey, draftRecovery[previousKey] == previousText { draftRecovery.removeValue(forKey: previousKey) }
                    } catch is CancellationError {} catch {
                        if epoch == accountEpoch && revision == conversationRevision { errorMessage = "The previous conversation draft could not be saved. No unavailable history was requested." }
                    }
                }
            }
            Task { await ensureLiveUpdates(peer: nil) }
            return
        }
        if isUIFixture { chatMessages = fixtureMessageSource; return }
        let initialEditorRevision = chatPreviewRevision
        messagesLoading = connected
        conversationTask = Task {
            // Draft persistence errors must never suppress an authorized history read.
            if let previous {
                do {
                    _ = try await backend.request("chatdraft.save", params: ["destination": .integer(previous.id), "message": .string(previousText)])
                    if let previousKey, draftRecovery[previousKey] == previousText { draftRecovery.removeValue(forKey: previousKey) }
                }
                catch is CancellationError { return }
                catch { if epoch == accountEpoch && revision == conversationRevision { errorMessage = "The previous draft could not be saved. Conversation history can still be loaded." } }
            }
            guard !Task.isCancelled, epoch == accountEpoch, revision == conversationRevision else { return }
            do {
                let draft = try await backend.request("chatdraft.get", params: ["destination": .integer(chat.id)])
                guard !Task.isCancelled, epoch == accountEpoch, revision == conversationRevision else { return }
                savedChatMessage = draft["message"].string
                if chatDraft.isEmpty, draftRecovery[recoveryKey] == nil, chatPreviewRevision == initialEditorRevision { chatDraft = savedChatMessage }
                chatDraftSaved = draft["updated_at"].string
                if chatPreviewRevision != initialEditorRevision { scheduleChatDraftSave() }
            } catch is CancellationError { return }
            catch { if epoch == accountEpoch && revision == conversationRevision { errorMessage = "The saved draft could not be loaded. Your editor text was retained." } }
            guard !Task.isCancelled, epoch == accountEpoch, revision == conversationRevision else { return }
            if connected {
                if currentUpdateScope != nil { await ensureLiveUpdates(peer: chat.id, fetchSnapshot: true) }
                else { await loadMessages() }
            } else { messagesLoading = false }
        }
    }

    func loadMessages(older: Bool = false, search: String? = nil) async {
        guard let chat = selectedChat, chat.contentAvailable, connected else { return }
        if let search { activeMessageSearch = search }
        messageListRevision += 1
        let epoch = accountEpoch, revision = conversationRevision, requestRevision = messageListRevision
        let remoteSearch = activeMessageSearch
        let initialStream = liveProjection?.streamID, initialSequence = liveProjection?.sequence
        messagesLoading = true; messagesError = nil
        defer { if requestRevision == messageListRevision { messagesLoading = false } }
        if isUIFixture {
            chatMessages = fixtureMessageSource.filter { remoteSearch.isEmpty || $0.text.localizedCaseInsensitiveContains(remoteSearch) }
            return
        }
        do {
            var params: [String: JSONValue] = ["destination": .integer(chat.id), "limit": .integer(50)]
            if older && nextMessageOffset > 0 { params["offset_id"] = .integer(nextMessageOffset) }
            if !remoteSearch.isEmpty { params["search"] = .string(remoteSearch) }
            let result = try await backend.request("messages.list", params: params, timeout: 180)
            guard !Task.isCancelled && epoch == accountEpoch && revision == conversationRevision && requestRevision == messageListRevision && selectedChat?.id == chat.id else { return }
            guard initialStream == liveProjection?.streamID, initialSequence == liveProjection?.sequence else {
                liveMessage = "New updates arrived during history loading. Your live conversation was retained; retry history when ready."
                return
            }
            let rows = result["messages"].array.map(ChatMessage.init)
            var seen = Set<Int>()
            chatMessages = Array(((older ? chatMessages : []) + rows).filter { seen.insert($0.id).inserted }.prefix(200))
            reconcileVisibleContent()
            if liveProjection?.peerID == chat.id { liveProjection?.seedMessages(chatMessages) }
            nextMessageOffset = result["next_offset_id"].int; hasMoreMessages = result["has_more"].bool && chatMessages.count < 200
        } catch is CancellationError {} catch {
            guard !Task.isCancelled, epoch == accountEpoch, revision == conversationRevision,
                  requestRevision == messageListRevision, selectedChat?.id == chat.id else { return }
            messagesError = error.localizedDescription
        }
    }
    func loadChatDrafts() async {
        guard !isUIFixture else { return }
        guard accountID != 0 else { chatDrafts = []; return }
        if let result = await cachedRequest("chatdraft.list", screen: .drafts) { chatDrafts = result["drafts"].array }
    }
    func saveChatDraft() {
        guard let chat = selectedChat else { return }
        let message = chatDraft, recoveryKey = draftRecoveryKey(chat.id)
        invalidateChatPreview()
        Task { await run("Saving conversation draft") {
            let result = try await self.backend.request("chatdraft.save", params: ["destination": .integer(chat.id), "message": .string(message)])
            self.chatDraftSaved = result["updated_at"].string
            if self.draftRecovery[recoveryKey] == message { self.draftRecovery.removeValue(forKey: recoveryKey) }
            await self.loadChatDrafts()
        } }
    }
    func deleteChatDraft(_ destination: Int) {
        let recoveryKey = draftRecoveryKey(destination)
        Task { await run("Deleting saved conversation draft") {
            _ = try await self.backend.request("chatdraft.delete", params: ["destination": .integer(destination)])
            self.draftRecovery.removeValue(forKey: recoveryKey)
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
            self.recordDeliveryOutcome(result)
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
        profiles = [AccountProfile(data: .object(["profile_id": .string("fixture"), "label": .string("Example Account"), "telegram_id": .integer(101), "is_active": .bool(true), "legacy": .bool(true), "auth_state": .string("disconnected")])), AccountProfile(data: .object(["profile_id": .string("fixture-second"), "label": .string("Second Example Account"), "telegram_id": .integer(102), "is_active": .bool(false), "auth_state": .string("disconnected")]))]
        groups = ["ශ්‍රී ලංකා Community 👩‍💻", "தமிழ் Developers", "Engineering Discussion"].enumerated().map { index, title in
            TelegramGroup(data: .object(["id": .integer(-1001 - index), "name": .string(title), "title": .string(title), "kind": .string("supergroup"), "effective_permission": .string(["allowed", "denied", "unknown"][index])]))
        }
        totalGroups = groups.count
        let fixtureNames = ["ශ්‍රී ලංකා Community — Long conversation name 👩🏽‍💻", "தமிழ் Developers and Engineering Discussion", "Example Conversation", "Engineering Study Group"]
        fixtureChatSource = (0..<198).map { index in
            ChatSummary(data: .object(["id": .integer(202 + index), "name": .string(fixtureNames[index % fixtureNames.count] + " \(index + 1)"),
                "content_available": .bool(index % 10 != 8), "kind": .string(index % 10 == 8 ? "channel" : index % 5 == 4 ? "supergroup" : "private"), "username": .string("example_\(index + 1)"),
                "last_message": .string("A synthetic conversation preview · සිංහල · தமிழ் · 👋"),
                "last_date": .string("2026-10-28T12:30:00+00:00"), "unread_count": .integer(index % 9 == 0 ? 3 : 0)]))
        }
        chatTotal = fixtureChatSource.count; chats = Array(fixtureChatSource.prefix(pageSize)); selectedChat = chats.first
        fixtureMessageSource = (1...12).map { index in
            ChatMessage(data: .object(["content_available": .bool(true), "id": .integer(index), "text": .string("Synthetic message \(index).\nසිංහල · தமிழ் · 👩🏽‍💻"),
                "sender_name": .string(index % 2 == 0 ? "Example Account" : "Example Contact"),
                "date": .string("2026-10-28T12:\(String(format: "%02d", index)):00+00:00"), "outgoing": .bool(index % 2 == 0)]))
        }
        chatMessages = fixtureMessageSource
        draft = "Hello community! 👋"; chatDraft = "A personal draft"
        activity = [ActivityKind.discovery, .inspection, .connection].enumerated().map { index, kind in
            var event = ActivityEvent(kind: kind, status: index == 1 ? .warning : .succeeded, accountID: "101", profileID: "fixture", accountName: "Example Account", date: Date().addingTimeInterval(Double(-index * 180)))
            if index == 0 { event.update(completed: 3) }
            return event
        }
        approvals = [groups[0]]
        deliveries = ["sent", "blocked", "uncertain", "rejected", "pending"].enumerated().map { index, state in
            Delivery(data: .object(["id": .integer(index + 1), "account": .integer(101), "destination": .integer(-1001),
                "destination_name": .string("Example Community · සිංහල தமிழ் 👩🏽‍💻"), "status": .string(state),
                "created_at": .string("2026-10-28T12:30:00+00:00"), "updated_at": .string("2026-10-28T12:30:00+00:00"),
                "message_preview": .string("Synthetic fixture preview; no Telegram request was made."),
                "telegram_message_id": index == 0 ? .integer(9001) : .null, "detail": .string("Fixture-only delivery state: " + state)]))
        }
        contacts = [TelegramContact(data: .object(["id": .integer(202), "name": .string("தமிழ் Example Contact"), "username": .string("example_contact"), "content_available": .bool(true)])), TelegramContact(data: .object(["id": .integer(203), "name": .string("ශ්‍රී ලංකා Example Contact"), "content_available": .bool(true)]))]
        contactTotal = contacts.count; fixtureContactSource = contacts
        telegramFolders = [.object(["id": .integer(2), "title": .string("Example Work Folder"), "contacts": .bool(true), "groups": .bool(true), "include_peer_ids": .array([.integer(202)]), "exclude_peer_ids": .array([]), "pinned_peer_ids": .array([])])]
        let fixtureEnvironment = ProcessInfo.processInfo.environment
        if let target = fixtureEnvironment["TGM_UI_SCREEN"], let value = Screen(rawValue: target) { screen = value }
        if fixtureEnvironment["TGM_UI_EMPTY"] == "1" { contacts = []; contactTotal = 0; telegramFolders = []; groups = []; chats = []; fixtureChatSource = []; profiles = []; selectedChat = nil; chatMessages = []; activity = []; approvals = []; deliveries = []; totalGroups = 0; chatTotal = 0 }
        if fixtureEnvironment["TGM_UI_CONNECTED"] == "1", case .object(var fields) = status { fields["connected"] = .bool(true); status = .object(fields) }
        if fixtureEnvironment["TGM_UI_MESSAGES_ERROR"] == "1" { chatMessages = []; messagesError = "Synthetic history retrieval failed. No private account was accessed." }
        if fixtureEnvironment["TGM_UI_MESSAGES_LOADING"] == "1" { chatMessages = []; messagesLoading = true }
        if fixtureEnvironment["TGM_UI_CONTACTS_EMPTY"] == "1" { contacts = []; contactTotal = 0 }
        if fixtureEnvironment["TGM_UI_NO_SELECTION"] == "1" { selectedChat = nil; chatMessages = [] }
        if fixtureEnvironment["TGM_UI_ACTIVITY_EMPTY"] == "1" { activity = [] }
        if fixtureEnvironment["TGM_UI_HISTORY_EMPTY"] == "1" { deliveries = [] }
        if fixtureEnvironment["TGM_UI_DESTINATIONS_EMPTY"] == "1" { approvals = [] }
        if fixtureEnvironment["TGM_UI_PROFILE"] == "1" { profileTarget = PeerProfile(data: .object(["id": .integer(202), "name": .string("Example Contact · தமிழ்"), "kind": .string("private"), "username": .string("example_contact"), "about": .string("Synthetic profile fixture.\nසිංහල · தமிழ் · 👩🏽‍💻"), "content_available": .bool(true), "checked_at": .string("2026-10-28T00:00:00+00:00")])) }
        if fixtureEnvironment["TGM_UI_FOLDERS"] == "1" { foldersPresented = true }
        if fixtureEnvironment["TGM_UI_IMAGE"] == "1" {
            previewImage = NSImage(systemSymbolName: "photo", accessibilityDescription: "Synthetic image viewer fixture")
            mediaPreview = MediaPreviewContext(scope: UpdateScope(profileID: "fixture", accountID: 101, generation: 0), token: "fixture-image", peerID: 202, messageID: 1, bytes: 1024, mimeType: "image/png")
            heldMediaPreview = mediaPreview
        }
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
        let epoch = accountEpoch, message = chatDraft, recoveryKey = draftRecoveryKey(chat.id)
        chatAutoTask = Task {
            do {
                try await Task.sleep(nanoseconds: 800_000_000)
                guard !Task.isCancelled, epoch == accountEpoch, selectedChat?.id == chat.id, chatDraft == message else { return }
                let result = try await backend.request("chatdraft.save", params: ["destination": .integer(chat.id), "message": .string(message)])
                guard epoch == accountEpoch, selectedChat?.id == chat.id, chatDraft == message else { return }
                savedChatMessage = message; chatDraftSaved = result["updated_at"].string
                if draftRecovery[recoveryKey] == message { draftRecovery.removeValue(forKey: recoveryKey) }
            } catch is CancellationError {} catch { if epoch == accountEpoch { errorMessage = "Conversation draft could not be saved. Your editor text is retained." } }
        }
    }
}

extension AppModel {
    private var currentUpdateScope: UpdateScope? {
        guard connected, !activeProfileID.isEmpty, status["account_generation"] != .null else { return nil }
        return UpdateScope(profileID: activeProfileID, accountID: accountID, generation: status["account_generation"].int)
    }
    private func resetLiveState() {
        closeMediaPreview(); profileTarget = nil
        closeMessageAction(force: true)
        liveRepairTask?.cancel(); typingExpiryTask?.cancel(); typingSendTask?.cancel(); typingIdleTask?.cancel(); readTask?.cancel()
        liveProjection = nil; liveWatchKey = nil; pendingLiveEvents = []; pendingLiveOverflow = false
        chatMessages = []; chatReply = nil; invalidateChatPreview()
        liveRepairNeeded = false; liveMessage = ""; typingDescription = ""
        visibleIncoming = []; conversationFocused = false; typingPeer = nil; lastTypingSent = 0; lastReadPeer = nil; lastReadID = 0
    }
    private func stopLiveUpdates() async {
        let scope = currentUpdateScope
        setConversationFocused(false)
        resetLiveState()
        if let scope, !isUIFixture {
            _ = try? await backend.request("updates.unwatch", params: ["account_id": .integer(scope.accountID)])
        }
    }
    private func ensureLiveUpdates(peer: Int?, fetchSnapshot: Bool = false) async {
        guard !isUIFixture, !isConnecting, let scope = currentUpdateScope else { return }
        let key = "\(scope.profileID):\(scope.accountID):\(scope.generation):\(peer ?? 0)"
        if liveWatchKey == key {
            if fetchSnapshot { await fetchLiveSnapshot(scope: scope, peer: peer) }
            return
        }
        liveWatchKey = key; liveProjection = nil; pendingLiveEvents = []; pendingLiveOverflow = false
        do {
            var params: [String: JSONValue] = ["account_id": .integer(scope.accountID)]
            if let peer { params["peer_id"] = .integer(peer) }
            let reply = try await backend.request("updates.watch", params: params)
            guard scope == currentUpdateScope, liveWatchKey == key, !Task.isCancelled else { return }
            guard scope.matches(reply), !reply["stream_id"].string.isEmpty else { throw BackendFailure(code: "protocol_error", message: "The live-update scope could not be verified.") }
            liveProjection = LiveProjection(scope: scope, streamID: reply["stream_id"].string, peerID: peer, sequence: reply["sequence"].int, dirty: reply["dirty"].bool)
            if let peer, peer == selectedChat?.id { liveProjection?.seedMessages(chatMessages) }
            let buffered = pendingLiveEvents; pendingLiveEvents = []
            for event in buffered { consumeLiveEvent(event) }
            if pendingLiveOverflow {
                liveProjection?.dirty = true; liveProjection?.messages = [:]
                chatMessages = []; chatReply = nil; invalidateChatPreview()
            }
            liveRepairNeeded = liveProjection?.dirty == true
            if liveRepairNeeded {
                chatMessages = []; chatReply = nil; invalidateChatPreview()
                liveMessage = "Live updates need synchronization. Refresh to recover the selected conversation."
            }
            if fetchSnapshot { await fetchLiveSnapshot(scope: scope, peer: peer) }
        } catch is CancellationError {} catch {
            guard scope == currentUpdateScope, liveWatchKey == key else { return }
            liveWatchKey = nil; liveRepairNeeded = true; liveMessage = "Live updates are unavailable. Refresh explicitly to reconnect them."
            if fetchSnapshot, peer == selectedChat?.id { await loadMessages() }
        }
    }
    func repairLiveUpdates() {
        guard !isUIFixture, connected else { return }
        liveRepairTask?.cancel()
        liveRepairTask = Task {
            guard let scope = currentUpdateScope else { return }
            let peer = selectedChat?.contentAvailable == true ? selectedChat?.id : nil
            if liveWatchKey == nil { await ensureLiveUpdates(peer: peer) }
            await fetchLiveSnapshot(scope: scope, peer: peer)
        }
    }
    private func fetchLiveSnapshot(scope: UpdateScope, peer: Int?) async {
        guard scope == currentUpdateScope else { return }
        messageListRevision += 1
        let revision = messageListRevision
        if peer != nil { messagesLoading = true; messagesError = nil }
        defer { if revision == messageListRevision { messagesLoading = false } }
        do {
            var params: [String: JSONValue] = ["account_id": .integer(scope.accountID), "limit": .integer(50)]
            if let peer { params["peer_id"] = .integer(peer) }
            let result = try await backend.request("sync.snapshot", params: params, timeout: 180)
            guard !Task.isCancelled, scope == currentUpdateScope, revision == messageListRevision, liveProjection?.peerID == peer else { return }
            guard liveProjection?.replace(with: result) == true else {
                liveRepairNeeded = true; liveMessage = "Updates changed during refresh. Refresh again when ready."; return
            }
            for value in result["chats"].array { mergeLiveChat(value) }
            if peer == selectedChat?.id {
                chatMessages = liveProjection?.visibleMessages ?? []
                nextMessageOffset = chatMessages.map(\.id).min() ?? 0
                hasMoreMessages = chatMessages.count == 50
                reconcileVisibleContent()
            }
            liveRepairNeeded = liveProjection?.dirty == true
            liveMessage = liveRepairNeeded ? "Some updates need another explicit refresh." : ""
        } catch is CancellationError {} catch {
            guard scope == currentUpdateScope, revision == messageListRevision, peer == selectedChat?.id else { return }
            messagesError = error.localizedDescription
            liveRepairNeeded = true; liveMessage = "The conversation could not be synchronized. Saved drafts are retained; refresh when ready."
        }
    }
    private func mergeLiveChat(_ value: JSONValue) {
        let row = ChatSummary(data: value)
        guard row.id != 0 else { return }
        if let index = chats.firstIndex(where: { $0.id == row.id }) { chats[index] = row }
        if selectedChat?.id == row.id {
            selectedChat = row
            if !row.contentAvailable { closeMediaPreview(); chatMessages = []; chatReply = nil; visibleIncoming = []; invalidateChatPreview() }
        }
    }
    private func consumeLiveEvent(_ event: JSONValue) {
        let data = event["data"]
        guard let scope = currentUpdateScope, scope.matches(data) else { return }
        guard var projection = liveProjection else {
            if liveWatchKey != nil {
                if pendingLiveEvents.count < 128 { pendingLiveEvents.append(event) }
                else { pendingLiveOverflow = true; liveRepairNeeded = true; chatMessages = []; chatReply = nil; invalidateChatPreview() }
            }
            return
        }
        if projection.peerID == selectedChat?.id { projection.seedMessages(chatMessages) }
        let effect = projection.accept(event)
        guard effect != .ignored else { return }
        liveProjection = projection
        if effect == .repairRequired {
            closeMediaPreview()
            chatMessages = []; chatReply = nil; visibleIncoming = []; invalidateChatPreview()
            liveRepairNeeded = true; liveMessage = "Live updates need synchronization. Refresh to recover the selected conversation."; return
        }
        if projection.peerID == selectedChat?.id && event["event"].string == "message.deleted" {
            let removed = Set(data["message_ids"].array.map(\.int))
            visibleIncoming.subtract(removed)
            if let reply = chatReply, removed.contains(reply) { chatReply = nil; invalidateChatPreview() }
            if let target = messageActionTarget, target.peerID == data["peer_id"].int, removed.contains(target.messageID) { invalidateActionTarget() }
            if (mediaPreview?.peerID == data["peer_id"].int && removed.contains(mediaPreview?.messageID ?? 0)) || (pendingMediaMessage?.peer == data["peer_id"].int && removed.contains(pendingMediaMessage?.message ?? 0)) { closeMediaPreview() }
        }
        if event["event"].string == "message.changed", let target = messageActionTarget, target.peerID == data["peer_id"].int, target.messageID == data["message"]["id"].int {
            let updated = ChatMessage(data: data["message"])
            if !updated.contentAvailable { invalidateActionTarget() }
            else if !messageActionSubmitted { messageActionOriginalText = updated.text; invalidateMessageActionPreview() }
        }
        if event["event"].string == "message.changed", !data["message"]["content_available"].bool,
           (mediaPreview?.peerID == data["peer_id"].int && mediaPreview?.messageID == data["message"]["id"].int) || (pendingMediaMessage?.peer == data["peer_id"].int && pendingMediaMessage?.message == data["message"]["id"].int) { closeMediaPreview() }
        if event["event"].string == "chat.changed" { mergeLiveChat(data["chat"]) }
        if projection.peerID == selectedChat?.id, selectedChat?.contentAvailable == true {
            chatMessages = projection.visibleMessages.filter { activeMessageSearch.isEmpty || $0.text.localizedCaseInsensitiveContains(activeMessageSearch) }
            reconcileVisibleContent()
        }
        if event["event"].string == "typing.changed" { refreshTypingDescription() }
    }
    private func refreshTypingDescription() {
        typingExpiryTask?.cancel()
        let now = Date().timeIntervalSince1970
        liveProjection?.typing = liveProjection?.typing.filter { $0.key > 0 && $0.value > now } ?? [:]
        guard let projection = liveProjection, projection.peerID == selectedChat?.id else { typingDescription = ""; return }
        let deadlines = projection.typing.filter { $0.key != accountID && $0.value > now }.map(\.value)
        typingDescription = deadlines.isEmpty ? "" : "Typing…"
        guard let deadline = deadlines.min() else { return }
        typingExpiryTask = Task {
            do { try await Task.sleep(nanoseconds: UInt64(max(0, deadline - now) * 1_000_000_000)) }
            catch { return }
            refreshTypingDescription()
        }
    }
    func stopConversationTyping() { stopTyping() }
    func setConversationFocused(_ focused: Bool, automaticRead: Bool = false) {
        automaticReadVisibilitySupported = automaticRead
        conversationFocused = focused
        if focused { scheduleReadFrontier() }
        else { readTask?.cancel(); stopTyping() }
    }
    func messageVisibilityChanged(id: Int, peer: Int, incoming: Bool, visible: Bool) {
        guard peer == selectedChat?.id else { return }
        if visible && incoming { visibleIncoming.insert(id) } else { visibleIncoming.remove(id) }
        scheduleReadFrontier()
    }
    private func reconcileVisibleContent() {
        visibleIncoming.formIntersection(Set(chatMessages.filter { !$0.outgoing && $0.contentAvailable }.map(\.id)))
        if let reply = chatReply, let row = chatMessages.first(where: { $0.id == reply }), !row.contentAvailable { chatReply = nil; invalidateChatPreview() }
    }
    private func scheduleReadFrontier(explicit: Bool = false) {
        reconcileVisibleContent()
        guard !isUIFixture, (automaticReadVisibilitySupported || explicit), conversationFocused, selectedChat?.contentAvailable == true,
              let peer = selectedChat?.id, let maximum = visibleIncoming.max(), let scope = currentUpdateScope,
              lastReadPeer != peer || maximum > lastReadID else { return }
        readTask?.cancel()
        readTask = Task {
            do {
                try await Task.sleep(nanoseconds: 150_000_000)
                guard !Task.isCancelled, conversationFocused, scope == currentUpdateScope, selectedChat?.id == peer,
                      visibleIncoming.contains(maximum) else { return }
                _ = try await backend.request("messages.read", params: ["account_id": .integer(scope.accountID), "peer_id": .integer(peer), "max_id": .integer(maximum)])
                guard scope == currentUpdateScope, selectedChat?.id == peer else { return }
                lastReadPeer = peer; lastReadID = maximum
            } catch is CancellationError {} catch { liveMessage = "Read status could not be updated. It will not be reported as confirmed." }
        }
    }
    func markDisplayedConversationRead() {
        guard selectedChat?.contentAvailable == true else { return }
        scheduleReadFrontier(explicit: true)
    }
    func userEditedConversation(_ text: String, focused: Bool) {
        chatDraft = text
        if let peer = selectedChat?.id, draftRecovery[draftRecoveryKey(peer)] != nil { draftRecovery[draftRecoveryKey(peer)] = text }
        invalidateChatPreview(); scheduleChatDraftSave()
        guard focused, conversationFocused, selectedChat?.allowsPersonalSend == true, !text.isEmpty,
              let peer = selectedChat?.id, let scope = currentUpdateScope, !isUIFixture else { stopTyping(); return }
        typingIdleTask?.cancel()
        if typingPeer != peer || Date().timeIntervalSince1970 - lastTypingSent >= 4 {
            typingPeer = peer; lastTypingSent = Date().timeIntervalSince1970
            typingSendTask?.cancel()
            typingSendTask = Task {
                guard scope == currentUpdateScope, typingPeer == peer, conversationFocused else { return }
                _ = try? await backend.request("messages.typing", params: ["account_id": .integer(scope.accountID), "peer_id": .integer(peer), "active": .bool(true)])
            }
        }
        typingIdleTask = Task {
            do { try await Task.sleep(nanoseconds: 5_000_000_000) } catch { return }
            stopTyping()
        }
    }
    private func stopTyping() {
        typingIdleTask?.cancel(); typingSendTask?.cancel()
        guard let peer = typingPeer, let scope = currentUpdateScope else { typingPeer = nil; return }
        typingPeer = nil; lastTypingSent = 0
        if !isUIFixture {
            Task { _ = try? await backend.request("messages.typing", params: ["account_id": .integer(scope.accountID), "peer_id": .integer(peer), "active": .bool(false)]) }
        }
    }
}

extension AppModel {
    var canPreviewMessageAction: Bool {
        guard let target = messageActionTarget, target.scope == currentUpdateScope, selectedChat?.id == target.peerID,
              !messageActionBusy, !messageActionSubmitted, !messageActionUnavailable else { return false }
        return target.action == "delete" || ComposerValidation.error(messageActionDraft) == nil
    }
    var canCommitMessageAction: Bool {
        guard canPreviewMessageAction, let target = messageActionTarget, let preview = messageActionPreview else { return false }
        return preview["account_id"].int == target.scope.accountID && preview["destination"].int == target.peerID
            && preview["message_id"].int == target.messageID && preview["action"].string == target.action
            && (target.action != "delete" || preview["delete_for_everyone"] == .bool(false))
            && (target.action == "delete" || preview["message"].string == messageActionDraft)
            && !messageActionConfirmation.isEmpty && messageActionConfirmation == preview["confirmation"].string
            && preview["expires_at"].doubleValue > Date().timeIntervalSince1970
    }
    func beginMessageAction(_ action: String, message: ChatMessage) {
        guard !busy, !messageActionBusy, let scope = currentUpdateScope, let chat = selectedChat, chat.allowsPersonalSend,
              (action == "edit" && message.canRequestEdit) || (action == "delete" && message.canRequestDelete) else { return }
        closeMessageAction(force: true)
        messageActionTarget = MessageActionContext(scope: scope, peerID: chat.id, peerName: chat.title, messageID: message.id, action: action)
        messageActionOriginalText = message.text; messageActionDraft = action == "edit" ? message.text : ""
    }
    func invalidateMessageActionPreview() {
        guard !messageActionSubmitted else { return }
        messageActionRevision += 1; messageActionPreview = nil; messageActionConfirmation = ""; messageActionExpiryTask?.cancel()
    }
    private func invalidateActionTarget() {
        messageActionOriginalText = ""; messageActionUnavailable = true
        if !messageActionSubmitted {
            invalidateMessageActionPreview(); messageActionError = "The original message is no longer available. No action was submitted."
        }
    }
    func previewMessageAction() {
        guard canPreviewMessageAction, let target = messageActionTarget else { return }
        let text = messageActionDraft, revision = messageActionRevision
        messageActionBusy = true; messageActionError = nil
        messageActionTask = Task {
            defer { if target.id == messageActionTarget?.id { messageActionBusy = false } }
            do {
                var params: [String: JSONValue] = ["account_id": .integer(target.scope.accountID), "destination": .integer(target.peerID), "message_id": .integer(target.messageID), "action": .string(target.action)]
                if target.action == "edit" { params["message"] = .string(text) }
                let result = try await backend.request("message.action.preview", params: params)
                guard !Task.isCancelled, target.id == messageActionTarget?.id, target.scope == currentUpdateScope,
                      revision == messageActionRevision, text == messageActionDraft, !messageActionUnavailable else { return }
                guard result["expires_at"].doubleValue.isFinite, result["expires_at"].doubleValue <= Date().timeIntervalSince1970 + 300, target.scope.matches(result), result["account_id"].int == target.scope.accountID, result["destination"].int == target.peerID,
                      result["message_id"].int == target.messageID, result["action"].string == target.action else {
                    throw BackendFailure(code: "protocol_error", message: "The exact action destination could not be verified.")
                }
                messageActionPreview = result; messageActionConfirmation = ""
                messageActionExpiryTask?.cancel()
                messageActionExpiryTask = Task {
                    do { try await Task.sleep(nanoseconds: UInt64(max(0, result["expires_at"].doubleValue - Date().timeIntervalSince1970) * 1_000_000_000)) }
                    catch { return }
                    guard target.id == messageActionTarget?.id, messageActionPreview?["token"] == result["token"], !messageActionSubmitted else { return }
                    invalidateMessageActionPreview(); messageActionError = "The action preview expired. Verify again before confirming."
                }
            } catch is CancellationError {} catch {
                if target.id == messageActionTarget?.id { messageActionError = error.localizedDescription }
            }
        }
    }
    func commitMessageAction() {
        guard canCommitMessageAction, let target = messageActionTarget, let preview = messageActionPreview else { return }
        let token = preview["token"].string, confirmation = messageActionConfirmation
        messageActionSubmitted = true; messageActionBusy = true; messageActionPreview = nil; messageActionConfirmation = ""
        messageActionExpiryTask?.cancel()
        messageActionTask = Task {
            defer { if target.id == messageActionTarget?.id { messageActionBusy = false } }
            do {
                let result = try await backend.request("message.action.commit", params: ["account_id": .integer(target.scope.accountID), "token": .string(token), "confirmation": .string(confirmation)], timeout: 180)
                guard target.scope == currentUpdateScope, target.id == messageActionTarget?.id else { return }
                guard result["profile_id"].string == target.scope.profileID, result["account_generation"].int == target.scope.generation,
                      result["operation"]["account"].int == target.scope.accountID, result["operation"]["destination"].int == target.peerID,
                      result["operation"]["message_id"].int == target.messageID, result["operation"]["action"].string == target.action,
                      ["acknowledged", "uncertain", "rejected"].contains(result["operation"]["status"].string) else {
                    throw BackendFailure(code: "protocol_error", message: "The operation scope could not be verified.")
                }
                messageActionResult = result["operation"]
                addActivity("Own-message \(target.action) \(result["operation"]["status"].string)")
                await loadMessageOperations()
            } catch {
                guard target.scope == currentUpdateScope, target.id == messageActionTarget?.id else { return }
                messageActionError = "The outcome could not be confirmed. Do not repeat the action; review Message Actions."
            }
        }
    }
    func closeMessageAction(force: Bool = false) {
        guard force || !messageActionBusy else { return }
        messageActionTask?.cancel(); messageActionExpiryTask?.cancel(); messageActionRevision += 1
        messageActionTarget = nil; messageActionDraft = ""; messageActionOriginalText = ""; messageActionConfirmation = ""
        messageActionPreview = nil; messageActionResult = nil; messageActionError = nil; messageActionBusy = false
        messageActionSubmitted = false; messageActionUnavailable = false
    }
    func loadMessageOperations() async {
        guard !isUIFixture, accountID != 0 else { messageOperations = []; return }
        if let result = await cachedRequest("message.operations", screen: .messageOperations) { messageOperations = result["operations"].array }
    }

}

extension AppModel {
    func scheduleContactSearch() {
        contactPage = 0; contactListTask?.cancel()
        contactListTask = Task {
            do { try await Task.sleep(nanoseconds: 250_000_000) } catch { return }
            await loadContacts()
        }
    }
    func loadContacts() async {
        guard !isUIFixture, accountID != 0 else { return }
        contactRevision += 1
        let revision = contactRevision, epoch = accountEpoch, query = contactQuery, page = contactPage
        contactsLoading = true; contactsError = nil
        defer { if revision == contactRevision { contactsLoading = false } }
        do {
            let result = try await backend.request("contacts.list", params: ["query": .string(query), "page": .integer(page), "size": .integer(pageSize)])
            guard !Task.isCancelled, revision == contactRevision, epoch == accountEpoch, query == contactQuery, page == contactPage else { return }
            contacts = result["contacts"].array.map(TelegramContact.init); contactTotal = result["total"].int
        } catch is CancellationError {} catch {
            guard !Task.isCancelled, revision == contactRevision, epoch == accountEpoch else { return }
            contactsError = error.localizedDescription
        }
    }
    func refreshContacts() {
        #if DEBUG
        if isUIFixture { contacts = fixtureContactSource; contactTotal = contacts.count; contactsError = nil; return }
        #endif
        guard let scope = currentUpdateScope else { return }
        operationTask = Task { await run("Refreshing Telegram contacts") {
            let result = try await self.backend.request("contacts.refresh", params: ["account_id": .integer(scope.accountID)])
            guard scope == self.currentUpdateScope else { return }
            self.contactNotice = result["truncated"].bool ? "The Telegram response exceeded the supported 1,000-contact refresh limit. Only the bounded supported set was cached; existing records were preserved." : ""
            await self.loadContacts()
        } }
    }
    func openContact(_ userID: Int) {
        guard let scope = currentUpdateScope else { return }
        operationTask = Task {
            var opened: ChatSummary?
            await run("Opening contact conversation") {
                let result = try await self.backend.request("contacts.open", params: ["account_id": .integer(scope.accountID), "user_id": .integer(userID)])
                guard scope == self.currentUpdateScope else { return }
                opened = ChatSummary(data: result["chat"])
            }
            guard scope == currentUpdateScope, let opened else { return }
            screen = .chats; chatKind = "all"; chatPage = 0
            await loadChats(); selectChat(opened)
        }
    }
    func showProfile(_ peerID: Int) {
        guard let scope = currentUpdateScope else { return }
        operationTask = Task { await run("Loading profile") {
            let result = try await self.backend.request("profile.get", params: ["account_id": .integer(scope.accountID), "peer_id": .integer(peerID)])
            guard scope == self.currentUpdateScope, result["profile"]["id"].int == peerID else { return }
            self.profileTarget = PeerProfile(data: result["profile"])
        } }
    }
    func openProfileConversation(_ peerID: Int) {
        profileTarget = nil
        if peerID == accountID { openSavedMessages() }
        else if let chat = chats.first(where: { $0.id == peerID }) { screen = .chats; chatKind = "all"; selectChat(chat) }
        else { openContact(peerID) }
    }
    func loadFolders() async {
        guard !isUIFixture, accountID != 0 else { return }
        let epoch = accountEpoch
        if let result = try? await backend.request("folders.list"), epoch == accountEpoch { telegramFolders = result["folders"].array }
    }
    func refreshFolders() {
        guard let scope = currentUpdateScope else { return }
        operationTask = Task { await run("Reading Telegram folder definitions") {
            let result = try await self.backend.request("folders.refresh", params: ["account_id": .integer(scope.accountID)])
            guard scope == self.currentUpdateScope else { return }
            self.telegramFolders = result["folders"].array
        } }
    }
    func openMediaPreview(_ message: ChatMessage) {
        guard !busy, !mediaPreviewPreparing, message.contentAvailable, let chat = selectedChat, chat.contentAvailable, let scope = currentUpdateScope else { return }
        closeMediaPreview()
        let revision = mediaPreviewRevision, requestedAt = Date().timeIntervalSince1970
        pendingMediaMessage = (chat.id, message.id)
        mediaPreviewPreparing = true
        operationTask = Task { await run("Preparing private image preview") {
            var issued: String?
            defer { if revision == self.mediaPreviewRevision { self.pendingMediaMessage = nil; self.mediaPreviewPreparing = false } }
            do {
                let result = try await self.backend.request("media.preview.get", params: ["account_id": .integer(scope.accountID), "destination": .integer(chat.id), "message_id": .integer(message.id)], timeout: 180)
                issued = result["token"].string
                guard scope == self.currentUpdateScope, result["profile_id"].string == scope.profileID, result["account_generation"].int == scope.generation,
                      result["destination"].int == chat.id, result["message_id"].int == message.id, !result["token"].string.isEmpty, revision == self.mediaPreviewRevision, self.liveProjection?.dirty != true else { throw BackendFailure.disconnected }
                let path = result["path"].string, bytes = result["bytes"].int, mime = result["mime_type"].string
                let decoding = Task.detached { try ImagePreviewReader.decode(path: path, expectedBytes: bytes, mimeType: mime) }
                let decoded = try await withTaskCancellationHandler { try await decoding.value } onCancel: { decoding.cancel() }
                try Task.checkCancellation()
                guard scope == self.currentUpdateScope, self.selectedChat?.id == chat.id, revision == self.mediaPreviewRevision,
                      self.liveProjection?.dirty != true, self.chatMessages.contains(where: { $0.id == message.id && $0.contentAvailable }) else { throw CancellationError() }
                self.previewImage = NSImage(cgImage: decoded.image, size: NSSize(width: CGFloat(decoded.image.width), height: CGFloat(decoded.image.height)))
                self.mediaPreview = MediaPreviewContext(scope: scope, token: result["token"].string, peerID: chat.id, messageID: message.id, bytes: bytes, mimeType: mime)
                self.heldMediaPreview = self.mediaPreview
                self.mediaPreviewExpiryTask = Task {
                    do { try await Task.sleep(nanoseconds: UInt64(max(0, requestedAt + 900 - Date().timeIntervalSince1970) * 1_000_000_000)) } catch { return }
                    if self.mediaPreview?.token == result["token"].string { self.closeMediaPreview() }
                }
            } catch {
                if let token = issued { await self.releaseMediaToken(token, account: scope.accountID) }
                throw error
            }
        } }
    }
    private func releaseMediaToken(_ token: String, account: Int) async {
        _ = try? await backend.request("media.preview.release", params: ["account_id": .integer(account), "token": .string(token)])
    }
    func closeMediaPreview() {
        mediaPreviewRevision += 1; pendingMediaMessage = nil; mediaPreviewPreparing = false
        mediaPreviewExpiryTask?.cancel(); previewImage = nil
        if let preview = mediaPreview ?? heldMediaPreview { Task { await releaseMediaToken(preview.token, account: preview.scope.accountID) } }
        mediaPreview = nil; heldMediaPreview = nil
    }
    func savePreviewAttachment() {
        guard let preview = mediaPreview, preview.scope == currentUpdateScope,
              let message = chatMessages.first(where: { $0.id == preview.messageID }), message.contentAvailable else { return }
        downloadAttachment(message)
    }
}
