import Foundation

struct TelegramContact: Identifiable, Equatable, Sendable {
    let data: JSONValue
    var id: Int { data["id"].int }
    var name: String { safeDisplay(data["name"].string) }
    var username: String { safeDisplay(data["username"].string) }
    var available: Bool { data["content_available"].bool }
}
struct PeerProfile: Identifiable, Equatable, Sendable {
    let data: JSONValue
    var id: Int { data["id"].int }
    var name: String { safeDisplay(data["name"].string) }
}
struct MediaPreviewContext: Identifiable, Equatable, Sendable {
    let scope: UpdateScope
    let token: String
    let peerID: Int
    let messageID: Int
    let bytes: Int
    let mimeType: String
    var id: String { token }
}
