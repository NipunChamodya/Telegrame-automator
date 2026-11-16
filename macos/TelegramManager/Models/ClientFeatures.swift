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
    var path: String = ""
    var kind: String = "photo"
    var expiresAt: Double = 0
    var canSave: Bool = true
    var category: String = "ordinary"
    var id: String { token }
    var playbackSupported: Bool {
        ["video/mp4", "video/quicktime", "audio/mpeg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/ogg"].contains(mimeType)
    }
    var documentSupported: Bool { ["application/pdf", "text/plain"].contains(mimeType) }

}


enum MediaFilename {
    static func suggested(_ name: String, mime: String) -> String {
        let extensions = ["image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "video/mp4": "mp4", "video/quicktime": "mov", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "application/pdf": "pdf", "text/plain": "txt"]
        let ext = extensions[mime] ?? "bin"
        let leaf = name.replacingOccurrences(of: "\\", with: "/").split(separator: "/").last.map(String.init) ?? "Attachment"
        let base = String(safeDisplay((leaf as NSString).deletingPathExtension).prefix(120)).trimmingCharacters(in: .whitespacesAndNewlines)
        return (base.isEmpty || base.hasPrefix(".") ? "Attachment" : base) + "." + ext
    }
    static func available(_ name: String, in folder: URL) -> String {
        let stem = (name as NSString).deletingPathExtension, ext = (name as NSString).pathExtension
        for number in 0...999 {
            let candidate = number == 0 ? name : "\(stem) (\(number)).\(ext)"
            if !FileManager.default.fileExists(atPath: folder.appendingPathComponent(candidate).path) { return candidate }
        }
        return UUID().uuidString + "." + ext
    }
}
