import Foundation

/// Session-only operational activity. Message bodies and backend error strings
/// intentionally have no storage field in this model.
enum ActivityKind: String, CaseIterable, Identifiable {
    case account, connection, discovery, inspection, draft, approval, delivery, conversations, attachment, settings, storage, system
    var id: String { rawValue }
    var title: String {
        switch self {
        case .account: "Account management"
        case .connection: "Telegram connection"
        case .discovery: "Group discovery"
        case .inspection: "Permission inspection"
        case .draft: "Draft management"
        case .approval: "Destination approval"
        case .delivery: "Message delivery"
        case .conversations: "Conversation management"
        case .attachment: "Attachment download"
        case .settings: "Preferences update"
        case .storage: "Storage maintenance"
        case .system: "Application operation"
        }
    }
    var symbol: String {
        switch self {
        case .account: "person.crop.circle"
        case .connection: "network"
        case .discovery: "person.2"
        case .inspection: "checkmark.shield"
        case .draft: "doc.text"
        case .approval: "checkmark.seal"
        case .delivery: "paperplane"
        case .conversations: "bubble.left.and.bubble.right"
        case .attachment: "arrow.down.doc"
        case .settings: "slider.horizontal.3"
        case .storage: "externaldrive"
        case .system: "gearshape"
        }
    }
    /// Convert known operation labels only; unknown strings are never retained.
    static func classify(_ operation: String) -> ActivityKind {
        switch operation.lowercased() {
        case "discover", "discovery", "discover groups", "refresh groups", "discovering groups": .discovery
        case "inspect", "inspection", "inspect permissions", "inspect pending", "refresh metadata", "inspecting permissions", "inspecting selected / pending groups", "verifying destination": .inspection
        case "send", "send message", "message delivery", "send personal message", "sending one approved message", "sending one personal message", "previewing personal message": .delivery
        case "save draft", "draft saved", "draft", "saving draft", "saving conversation draft", "deleting saved conversation draft": .draft
        case "approve", "revoke", "approve destination", "revoke approval", "approving destination", "revoking approval": .approval
        case "connect", "reconnect", "connecting", "authentication", "disconnect", "starting backend", "restoring session", "authenticating", "disconnecting account": .connection
        case "switch account", "add account", "remove account", "log out", "account", "switching account", "adding account", "logging out selected account", "removing local account profile", "restoring account profile": .account
        case "refreshing conversation list", "opening saved messages", "updating local label": .conversations
        case "downloading attachment": .attachment
        case "saving preferences": .settings
        case "exporting safe diagnostics", "creating private database backup": .storage
        default: .system
        }
    }
}

enum ActivityStatus: String, CaseIterable, Identifiable {
    case running, succeeded, failed, cancelled, warning, info
    var id: String { rawValue }
    var title: String { rawValue.capitalized }
}

struct ActivityEvent: Identifiable, Equatable {
    let id: UUID
    let kind: ActivityKind
    var status: ActivityStatus
    let date: Date
    private(set) var updatedAt: Date
    let accountID: String?
    let profileID: String?
    let accountName: String?
    private(set) var completed: Int?
    private(set) var total: Int?
    var title: String { kind.title }
    var description: String {
        switch status {
        case .running: "Operation is in progress."
        case .succeeded: "Operation completed successfully."
        case .failed: "Operation did not complete. Review the application’s current error for recovery options."
        case .cancelled: "Operation was cancelled. Completed records remain saved."
        case .warning: "Operation is paused or needs attention. Review the current cooldown or recovery guidance."
        case .info: "Application activity recorded for this session."
        }
    }
    init(id: UUID = UUID(), kind: ActivityKind, status: ActivityStatus = .running,
         accountID: String? = nil, profileID: String? = nil, accountName: String? = nil,
         date: Date = Date()) {
        self.id = id; self.kind = kind; self.status = status; self.date = date
        self.updatedAt = date; self.accountID = accountID.map { String(safeDisplay($0).prefix(80)) }
        self.profileID = profileID.map { String(safeDisplay($0).prefix(80)) }
        self.accountName = accountName.map { String(safeDisplay($0).prefix(160)) }
    }
    mutating func update(status: ActivityStatus? = nil, completed: Int? = nil, total: Int? = nil) {
        if let status { self.status = status }
        if let completed, completed >= 0 { self.completed = completed }
        if let total, total >= 0 { self.total = total }
        updatedAt = Date()
    }
}

enum ActivityHistory {
    static let limit = 100
    static func insert(_ event: ActivityEvent, into events: inout [ActivityEvent]) {
        events.removeAll { $0.id == event.id }
        events.append(event)
        events.sort { $0.date > $1.date }
        if events.count > limit { events.removeLast(events.count - limit) }
    }
    static func update(id: UUID, in events: inout [ActivityEvent], status: ActivityStatus? = nil,
                       completed: Int? = nil, total: Int? = nil) {
        guard let index = events.firstIndex(where: { $0.id == id }) else { return }
        events[index].update(status: status, completed: completed, total: total)
    }
    static func filter(_ events: [ActivityEvent], query: String = "", kind: ActivityKind? = nil,
                       status: ActivityStatus? = nil) -> [ActivityEvent] {
        let search = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return events.filter { event in
            (kind == nil || event.kind == kind) && (status == nil || event.status == status) &&
            (search.isEmpty || [event.title, event.status.title, event.accountName ?? "", event.accountID ?? "", event.profileID ?? ""]
                .contains { $0.localizedCaseInsensitiveContains(search) })
        }.sorted { $0.date > $1.date }
    }
}
