import Foundation
import Darwin

indirect enum JSONValue: Codable, Equatable, Sendable {
    case object([String: JSONValue]), array([JSONValue]), string(String), integer(Int64), number(Double), bool(Bool), null
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Int64.self) { self = .integer(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let v): try c.encode(v)
        case .integer(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .string(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        }
    }
    subscript(_ key: String) -> JSONValue { if case .object(let value) = self { return value[key] ?? .null }; return .null }
    var string: String { switch self { case .string(let v): return v; case .integer(let v): return String(v); case .number(let v): return String(format: "%.0f", v); case .bool(let v): return v ? "Yes" : "No"; default: return "" } }
    var int: Int { switch self { case .integer(let v): return Int(exactly: v) ?? 0; case .number(let v): return Int(exactly: v) ?? 0; default: return Int(string) ?? 0 } }
    var bool: Bool { if case .bool(let v) = self { return v }; return false }
    var array: [JSONValue] { if case .array(let v) = self { return v }; return [] }
    var object: [String: JSONValue] { if case .object(let v) = self { return v }; return [:] }
    static func integer(_ v: Int) -> JSONValue { .integer(Int64(v)) }
}

struct TelegramGroup: Identifiable, Equatable, Sendable {
    let data: JSONValue
    var id: Int { data["id"].int }
    var name: String { safeDisplay(data["name"].string) }
    var username: String { safeDisplay(data["username"].string) }
    var kind: String { data["kind"].string }
    var members: String { data["members"] == .null ? "Unknown" : data["members"].string }
    var permission: String { let p = data["effective_permission"].string; return p.isEmpty ? data["permission"].string : p }
    var checked: String { data["permissions_checked_at"].string }
    var freshness: String {
        if data["metadata_fresh"].bool { return "Fresh" }
        let completeness = data["metadata_status"].string
        return completeness == "complete" ? "Expired" : completeness.isEmpty ? "Unknown" : completeness.capitalized
    }
    var completeness: String { data["metadata_status"].string.capitalized }
    var reasons: [String] { data["reasons"].array.map { safeDisplay($0.string) } }
}

struct Delivery: Identifiable, Equatable, Sendable {
    let data: JSONValue
    var id: Int { data["id"].int }
    var destination: String { data["destination"].string }
    var status: String { data["status"].string }
    var date: String { data["created_at"].string }
    var detail: String { safeDisplay(data["detail"].string) }
}

struct BackendFailure: Error, LocalizedError, Sendable {
    let code: String
    let message: String
    var errorDescription: String? { message }
    static let disconnected = BackendFailure(code: "backend_unavailable", message: "The backend is unavailable. Reconnect to restore the existing session; no delivery is retried.")
}

func safeDisplay(_ input: String) -> String {
    input.unicodeScalars.filter { scalar in
        let v = scalar.value
        return !(v < 32 || (127...159).contains(v) || (0x202A...0x202E).contains(v) || (0x2066...0x2069).contains(v))
    }.map(String.init).joined()
}

struct ComposerValidation {
    static func units(_ text: String) -> Int { text.utf16.count }
    static func error(_ text: String) -> String? {
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Enter a message before previewing." }
        if units(text) > 4096 { return "Messages must be no longer than 4096 UTF-16 units." }
        return nil
    }
}

func readBoundedUTF8File(_ url: URL) throws -> String {
    let fd = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
    guard fd >= 0 else { throw BackendFailure(code: "file_access", message: "Choose a regular UTF-8 file you can read; symbolic links are not imported.") }
    defer { Darwin.close(fd) }
    var info = stat()
    guard fstat(fd, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG, info.st_size <= 65_536 else {
        throw BackendFailure(code: "file_size", message: "Choose a regular UTF-8 text file no larger than 64 KiB.")
    }
    var data = Data(), chunk = [UInt8](repeating: 0, count: 8192)
    while true {
        let count = Darwin.read(fd, &chunk, chunk.count)
        if count < 0 { if errno == EINTR { continue }; throw BackendFailure(code: "file_read", message: "The selected file could not be read safely.") }
        if count == 0 { break }
        data.append(contentsOf: chunk.prefix(count))
        guard data.count <= 65_536 else { throw BackendFailure(code: "file_size", message: "The selected file exceeds 64 KiB.") }
    }
    guard let text = String(data: data, encoding: .utf8) else { throw BackendFailure(code: "encoding", message: "The selected file must contain valid UTF-8 text.") }
    if let problem = ComposerValidation.error(text) { throw BackendFailure(code: "message_validation", message: problem) }
    return text
}


struct AccountProfile: Identifiable, Equatable, Sendable {
    let data: JSONValue
    var id: String { data["profile_id"].string.isEmpty ? data["id"].string : data["profile_id"].string }
    var title: String { safeDisplay(data["display_name"].string.isEmpty ? data["label"].string : data["display_name"].string) }
    var active: Bool { data["is_active"].bool }
    var legacy: Bool { data["legacy"].bool }
    var archived: Bool { data["archived"].bool }
    var state: String { data["auth_state"].string }
    var accountID: String { data["telegram_id"] == .null ? "Not authenticated" : data["telegram_id"].int.description }
}

struct ChatSummary: Identifiable, Equatable, Sendable {
    let data: JSONValue
    var id: Int { data["id"].int }
    var title: String { safeDisplay(data["name"].string) }
    var kind: String { data["kind"].string }
    var lastMessage: String { contentAvailable ? safeDisplay(data["last_message"].string) : "" }
    var allowsPersonalSend: Bool { contentAvailable && (kind == "private" || kind == "saved") }
}
struct ChatMessage: Identifiable, Equatable, Sendable {
    let data: JSONValue
    var id: Int { data["id"].int }
    var text: String { contentAvailable ? data["text"].string : "" }
    var sender: String { safeDisplay(data["sender_name"].string) }
    var outgoing: Bool { data["outgoing"].bool }
    var hasAttachment: Bool { data["media"] != .null && !data["media"].object.isEmpty }
}

extension ChatSummary {
    var contentAvailable: Bool { data["content_available"].bool && kind != "channel" }
    var contentReason: String {
        let reason = safeDisplay(data["content_reason"].string)
        return reason.isEmpty ? "Refresh conversations to verify whether this content is supported." : reason
    }
}
extension ChatMessage {
    var contentAvailable: Bool { data["content_available"].bool }
    var edited: Bool { data["edit_date"] != .null && data["edit_date"].doubleValue > 0 }
    var replyID: Int? { data["reply_to_id"].int > 0 ? data["reply_to_id"].int : nil }
    var reactions: [MessageReaction] { data["reactions"].array.map(MessageReaction.init).filter { $0.count > 0 } }
}
