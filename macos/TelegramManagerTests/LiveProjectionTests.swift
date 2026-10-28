import XCTest
@testable import TelegramManager

final class LiveProjectionTests: XCTestCase {
    private let scope = UpdateScope(profileID: "profile-a", accountID: 13, generation: 4)
    private func data(_ values: [String: JSONValue] = [:]) -> JSONValue {
        var fields: [String: JSONValue] = ["profile_id": .string("profile-a"), "account_id": .integer(13), "account_generation": .integer(4), "stream_id": .string("stream-one"), "peer_id": .integer(91)]
        fields.merge(values) { _, newest in newest }; return .object(fields)
    }
    private func row(_ id: Int, text: String = "සිංහල தமிழ் 👩🏽‍💻") -> JSONValue {
        .object(["id": .integer(id), "text": .string(text), "content_available": .bool(true)])
    }
    func testAccountGenerationAndStreamRejectStaleEvents() {
        var projection = LiveProjection(scope: scope, streamID: "stream-one", peerID: 91, sequence: 0)
        for fields in [["account_id": JSONValue.integer(99)], ["profile_id": .string("profile-b")], ["account_generation": .integer(3)], ["stream_id": .string("old-stream")]] {
            var values = fields; values["sequence"] = .integer(1); values["message"] = row(1)
            XCTAssertEqual(projection.accept(.object(["event": .string("message.changed"), "data": data(values)])), .ignored)
        }
        XCTAssertTrue(projection.messages.isEmpty); XCTAssertEqual(projection.sequence, 0)
    }
    func testGapRequiresScopedSnapshotWithoutApplyingUncertainEvent() {
        var projection = LiveProjection(scope: scope, streamID: "stream-one", peerID: 91, sequence: 0)
        XCTAssertEqual(projection.accept(.object(["event": .string("message.changed"), "data": data(["sequence": .integer(2), "message": row(2)])])), .repairRequired)
        XCTAssertTrue(projection.dirty); XCTAssertTrue(projection.messages.isEmpty)
        XCTAssertFalse(projection.replace(with: data(["sequence": .integer(3), "stream_id": .string("old-stream"), "messages": .array([row(3)])])))
        XCTAssertTrue(projection.replace(with: data(["sequence": .integer(3), "dirty": .bool(false), "messages": .array([row(3)])])))
        XCTAssertFalse(projection.dirty); XCTAssertEqual(projection.visibleMessages.first?.id, 3)
    }
    func testInsertEditDeleteDeduplicateAndCapTwoHundred() {
        var projection = LiveProjection(scope: scope, streamID: "stream-one", peerID: 91, sequence: 0)
        projection.seedMessages((1...200).map { ChatMessage(data: row($0)) })
        XCTAssertEqual(projection.accept(.object(["event": .string("message.changed"), "data": data(["sequence": .integer(1), "message": row(201)])])), .applied)
        XCTAssertEqual(projection.messages.count, 200); XCTAssertNil(projection.messages[1])
        _ = projection.accept(.object(["event": .string("message.changed"), "data": data(["sequence": .integer(2), "message": row(201, text: "edited")])]))
        XCTAssertEqual(projection.messages[201]?.text, "edited"); XCTAssertEqual(projection.messages.count, 200)
        _ = projection.accept(.object(["event": .string("message.deleted"), "data": data(["sequence": .integer(3), "message_ids": .array([.integer(201)])])]))
        XCTAssertNil(projection.messages[201])
    }
    func testOtherPeerCannotChangeActiveMessages() {
        var projection = LiveProjection(scope: scope, streamID: "stream-one", peerID: 91, sequence: 0)
        _ = projection.accept(.object(["event": .string("message.changed"), "data": data(["sequence": .integer(1), "peer_id": .integer(92), "message": row(1)])]))
        XCTAssertTrue(projection.messages.isEmpty); XCTAssertEqual(projection.sequence, 1)
    }
    func testReadMarkersComeOnlyFromServerOutboxFrontier() {
        var projection = LiveProjection(scope: scope, streamID: "stream-one", peerID: 91, sequence: 0)
        XCTAssertNil(projection.readOutboxMaxID)
        _ = projection.accept(.object(["event": .string("read.changed"), "data": data(["sequence": .integer(1), "outbox": .bool(false), "max_id": .integer(10)])]))
        XCTAssertNil(projection.readOutboxMaxID)
        _ = projection.accept(.object(["event": .string("read.changed"), "data": data(["sequence": .integer(2), "outbox": .bool(true), "max_id": .integer(8)])]))
        XCTAssertEqual(projection.readOutboxMaxID, 8)
    }
    func testMissingMetadataDoesNotFabricateRichState() {
        let message = ChatMessage(data: row(1))
        XCTAssertFalse(message.edited); XCTAssertNil(message.replyID); XCTAssertTrue(message.reactions.isEmpty)
        let unknown = ChatSummary(data: .object(["kind": .string("private"), "last_message": .string("legacy preview")]))
        XCTAssertFalse(unknown.contentAvailable); XCTAssertFalse(unknown.allowsPersonalSend); XCTAssertEqual(unknown.lastMessage, "")
        let protected = ChatMessage(data: .object(["text": .string("must not display"), "content_available": .bool(false)]))
        XCTAssertEqual(protected.text, "")
    }
    func testServerReactionAndEditMetadataAreOptionalAndPreserved() {
        let message = ChatMessage(data: .object(["edit_date": .integer(123), "reply_to_id": .integer(7), "reactions": .array([.object(["emoji": .string("👍"), "count": .integer(3), "chosen": .bool(true)])])]))
        XCTAssertTrue(message.edited); XCTAssertEqual(message.replyID, 7)
        XCTAssertEqual(message.reactions.first?.count, 3); XCTAssertEqual(message.reactions.first?.emoji, "👍")
    }
    func testTypingStatePurgesExpiredAndCapsDistinctUsers() {
        var projection = LiveProjection(scope: scope, streamID: "stream-one", peerID: 91, sequence: 0)
        for index in 1...300 {
            _ = projection.accept(.object(["event": .string("typing.changed"), "data": data(["sequence": .integer(index), "user_id": .integer(index), "active": .bool(true), "expires_at": .number(Date().timeIntervalSince1970 + 5)])]))
        }
        XCTAssertEqual(projection.typing.count, 128)
        projection.typing[999] = Date().timeIntervalSince1970 - 1
        _ = projection.accept(.object(["event": .string("typing.changed"), "data": data(["sequence": .integer(301), "user_id": .integer(999), "active": .bool(false)])]))
        XCTAssertNil(projection.typing[999]); XCTAssertLessThanOrEqual(projection.typing.count, 128)
    }
    @MainActor func testLegacyVisibleFractionUsesActualViewportIntersection() {
        let viewport = CGRect(x: 0, y: 0, width: 100, height: 100)
        XCTAssertEqual(ChatsView.visibleFraction(CGRect(x: 0, y: 50, width: 100, height: 100), viewport: viewport), 0.5)
        XCTAssertEqual(ChatsView.visibleFraction(CGRect(x: 0, y: 110, width: 100, height: 100), viewport: viewport), 0)
        XCTAssertEqual(ChatsView.visibleFraction(.zero, viewport: viewport), 0)
    }
}

final class RichMessagePresentationTests: XCTestCase {
    @MainActor func testUnicodeEntitiesPreserveTextAndDropInvalidSurrogateRanges() {
        let text = "👩‍💻 සිංහල தமிழ்"
        let message = ChatMessage(data: .object(["text": .string(text), "content_available": .bool(true), "entities": .array([
            .object(["type": .string("bold"), "offset": .integer(6), "length": .integer(6)]),
            .object(["type": .string("link"), "offset": .integer(1), "length": .integer(1), "url": .string("https://example.com")]),
            .object(["type": .string("italic"), "offset": .integer(-1), "length": .integer(2)])])]))
        let attributed = MessagePresentation.attributed(message)
        XCTAssertEqual(String(attributed.characters), text)
        XCTAssertTrue(attributed.runs.compactMap(\.link).isEmpty)
    }
    @MainActor func testSafeLinksAllowOnlyAbsoluteNoncredentialWebURLs() {
        XCTAssertNotNil(MessagePresentation.safeLink("https://example.com/path"))
        for value in ["javascript:alert(1)", "file:///tmp/a", "tg://resolve?domain=x", "https://user:password@example.com", "relative/path"] { XCTAssertNil(MessagePresentation.safeLink(value)) }
    }
    func testActionsRequireServerCapabilityAndOwnAvailablePlainMessage() {
        XCTAssertFalse(ChatMessage(data: .object(["outgoing": .bool(true), "content_available": .bool(true)])).canRequestEdit)
        let allowed = ChatMessage(data: .object(["outgoing": .bool(true), "content_available": .bool(true), "can_request_edit": .bool(true), "can_request_delete": .bool(true)]))
        XCTAssertTrue(allowed.canRequestEdit); XCTAssertTrue(allowed.canRequestDelete)
        XCTAssertFalse(ChatMessage(data: .object(["outgoing": .bool(false), "content_available": .bool(true), "can_request_delete": .bool(true)])).canRequestDelete)
        XCTAssertFalse(ChatMessage(data: .object(["outgoing": .bool(true), "content_available": .bool(false), "can_request_edit": .bool(true)])).canRequestEdit)
    }
    func testForwardAndPinnedStateAreNotInvented() {
        let plain = ChatMessage(data: .object(["content_available": .bool(true)]))
        XCTAssertNil(plain.forwarded); XCTAssertFalse(plain.pinned)
    }
}
