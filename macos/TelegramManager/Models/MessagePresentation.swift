import Foundation
import SwiftUI

struct MessageActionContext: Identifiable, Equatable {
    let id = UUID()
    let scope: UpdateScope
    let peerID: Int
    let peerName: String
    let messageID: Int
    let action: String
}

extension ChatMessage {
    var canRequestEdit: Bool { contentAvailable && outgoing && !hasAttachment && data["can_request_edit"].bool }
    var canRequestDelete: Bool { contentAvailable && outgoing && !hasAttachment && data["can_request_delete"].bool }
    var forwarded: JSONValue? { data["forward"] == .null ? nil : data["forward"] }
    var pinned: Bool { contentAvailable && data["pinned"].bool }
}

@MainActor enum MessagePresentation {
    static func attributed(_ message: ChatMessage) -> AttributedString {
        guard message.contentAvailable else { return AttributedString("Content unavailable") }
        let text = message.text
        var result = AttributedString(text)
        let utf16Count = text.utf16.count
        for entity in message.data["entities"].array.prefix(32) {
            let offset = entity["offset"].int, length = entity["length"].int
            let (end, overflow) = offset.addingReportingOverflow(length)
            guard !overflow, offset >= 0, length > 0, end <= utf16Count,
                  let range = Range(NSRange(location: offset, length: length), in: text),
                  let lower = AttributedString.Index(range.lowerBound, within: result),
                  let upper = AttributedString.Index(range.upperBound, within: result) else { continue }
            let span = lower..<upper
            switch entity["type"].string {
            case "bold", "italic":
                let intention: InlinePresentationIntent = entity["type"].string == "bold" ? .stronglyEmphasized : .emphasized
                for run in Array(result[span].runs) {
                    var value = run.inlinePresentationIntent ?? []
                    value.insert(intention); result[run.range].inlinePresentationIntent = value
                }
            case "code", "pre": result[span].font = .body.monospaced()
            case "link":
                if let url = safeLink(entity["url"].string) { result[span].link = url }
            default: break
            }
        }
        return result
    }
    static func safeLink(_ value: String) -> URL? {
        guard value.utf8.count <= 2048, let parts = URLComponents(string: value),
              let scheme = parts.scheme?.lowercased(), ["https", "http"].contains(scheme),
              let host = parts.host, !host.isEmpty, parts.user == nil, parts.password == nil else { return nil }
        return parts.url
    }
}
