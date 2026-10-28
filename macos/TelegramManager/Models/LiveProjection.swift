import Foundation

struct UpdateScope: Equatable, Sendable {
    let profileID: String
    let accountID: Int
    let generation: Int
    func matches(_ value: JSONValue) -> Bool {
        !profileID.isEmpty && accountID != 0 && value["profile_id"].string == profileID
            && value["account_id"].int == accountID && value["account_generation"] != .null
            && value["account_generation"].int == generation
    }
}

enum ProjectionEffect: Equatable { case ignored, applied, repairRequired }

/// A bounded projection of one account and selected peer, never a Telegram client.
struct LiveProjection: Equatable, Sendable {
    let scope: UpdateScope
    let streamID: String
    var peerID: Int?
    var sequence: Int
    var dirty = false
    var messages: [Int: ChatMessage] = [:]
    var readOutboxMaxID: Int?
    var typing: [Int: TimeInterval] = [:]

    var visibleMessages: [ChatMessage] { messages.values.sorted { $0.id > $1.id } }
    mutating func seedMessages(_ rows: [ChatMessage]) {
        guard !dirty else { messages = [:]; return }
        messages = Dictionary(rows.prefix(200).map { ($0.id, $0) }, uniquingKeysWith: { _, newest in newest })
    }
    mutating func accept(_ event: JSONValue) -> ProjectionEffect {
        let data = event["data"]
        guard scope.matches(data), data["stream_id"].string == streamID, data["sequence"] != .null else { return .ignored }
        let incoming = data["sequence"].int
        guard incoming > sequence else { return .ignored }
        let gap = incoming != sequence + 1
        sequence = incoming
        if gap || dirty || event["event"].string == "sync.required" { dirty = true; messages = [:]; typing = [:]; return .repairRequired }
        guard data["peer_id"].int == peerID else { return .applied }
        switch event["event"].string {
        case "message.changed":
            let row = ChatMessage(data: data["message"])
            guard row.id > 0 else { dirty = true; return .repairRequired }
            messages[row.id] = row
            if messages.count > 200 {
                for id in messages.keys.sorted().prefix(messages.count - 200) { messages.removeValue(forKey: id) }
            }
        case "message.deleted":
            for id in data["message_ids"].array { messages.removeValue(forKey: id.int) }
        case "read.changed":
            if data["outbox"].bool { readOutboxMaxID = max(readOutboxMaxID ?? 0, data["max_id"].int) }
        case "typing.changed":
            let userID = data["user_id"].int
            let now = Date().timeIntervalSince1970
            typing = typing.filter { $0.key > 0 && $0.value > now }
            if userID > 0 && data["active"].bool && data["expires_at"].doubleValue > now && data["expires_at"].doubleValue <= now + 30 {
                typing[userID] = data["expires_at"].doubleValue
                if typing.count > 128 {
                    for key in typing.sorted(by: { $0.value < $1.value }).prefix(typing.count - 128).map(\.key) { typing.removeValue(forKey: key) }
                }
            }
            else { typing.removeValue(forKey: userID) }
        default: break
        }
        return .applied
    }
    mutating func replace(with snapshot: JSONValue) -> Bool {
        guard scope.matches(snapshot), snapshot["stream_id"].string == streamID, snapshot["peer_id"].int == (peerID ?? 0), snapshot["sequence"] != .null,
              snapshot["sequence"].int >= sequence else { return false }
        sequence = snapshot["sequence"].int; dirty = snapshot["dirty"].bool
        seedMessages(snapshot["messages"].array.map(ChatMessage.init))
        if snapshot["read_outbox_max_id"] != .null { readOutboxMaxID = snapshot["read_outbox_max_id"].int }
        typing = [:]
        return true
    }
}

struct MessageReaction: Identifiable, Equatable, Sendable {
    let data: JSONValue
    var emoji: String { data["emoji"].string }
    var id: String { !emoji.isEmpty ? emoji : "custom_" + data["custom_emoji_id"].string }
    var count: Int { max(0, data["count"].int) }
    var chosen: Bool { data["chosen"].bool }
}
