import XCTest
@testable import TelegramManager

final class ActivityTests: XCTestCase {
    func testHistoryBoundAndChronology() {
        var events: [ActivityEvent] = []
        for index in 0..<125 {
            ActivityHistory.insert(ActivityEvent(kind: .discovery, date: Date(timeIntervalSince1970: Double(index))), into: &events)
        }
        XCTAssertEqual(events.count, 100)
        XCTAssertEqual(events.first?.date, Date(timeIntervalSince1970: 124))
        XCTAssertEqual(events.last?.date, Date(timeIntervalSince1970: 25))
    }
    func testStatusUpdatePreservesIdentityAndAccountContext() {
        var events: [ActivityEvent] = []
        let event = ActivityEvent(kind: .inspection, accountID: "22", profileID: "profile_fixture", accountName: "ශ්‍රී 👩🏽‍💻")
        ActivityHistory.insert(event, into: &events)
        ActivityHistory.update(id: event.id, in: &events, completed: 4)
        XCTAssertNil(events[0].total)
        ActivityHistory.update(id: event.id, in: &events, status: .cancelled)
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events[0].id, event.id)
        XCTAssertEqual(events[0].completed, 4)
        XCTAssertEqual(events[0].status, .cancelled)
        XCTAssertEqual(events[0].accountName, "ශ්‍රී 👩🏽‍💻")
    }
    func testFilteringAndEmptyStates() {
        let events = [ActivityEvent(kind: .delivery, status: .failed, accountName: "தமிழ்"), ActivityEvent(kind: .draft, status: .succeeded)]
        XCTAssertEqual(ActivityHistory.filter(events, query: "தமிழ்").count, 1)
        XCTAssertEqual(ActivityHistory.filter(events, kind: .draft, status: .succeeded).count, 1)
        XCTAssertTrue(ActivityHistory.filter(events, query: "missing").isEmpty)
        XCTAssertTrue(ActivityHistory.filter([], status: .running).isEmpty)
    }
    func testUnknownOperationCannotCaptureMessageOrSecret() {
        let privateText = "secret message API hash login code"
        let kind = ActivityKind.classify(privateText)
        XCTAssertEqual(kind, .system)
        let event = ActivityEvent(kind: kind, status: .failed)
        XCTAssertFalse(event.title.contains(privateText))
        XCTAssertFalse(event.description.contains(privateText))
        XCTAssertEqual(ActivityKind.classify("Discover groups"), .discovery)
        XCTAssertEqual(ActivityKind.classify("Send message"), .delivery)
        XCTAssertEqual(ActivityKind.classify("Discovering groups"), .discovery)
        XCTAssertEqual(ActivityKind.classify("Inspecting selected / pending groups"), .inspection)
        XCTAssertEqual(ActivityKind.classify("Sending one approved message"), .delivery)
        XCTAssertEqual(ActivityKind.classify("Restoring session"), .connection)
        XCTAssertEqual(ActivityKind.classify("Saving conversation draft"), .draft)
        XCTAssertEqual(ActivityKind.classify("Switching account"), .account)
    }
    func testContextSanitizationAndInvalidProgress() {
        var event = ActivityEvent(kind: .account, accountName: "a\u{1b}\u{202e}👩‍💻")
        XCTAssertEqual(event.accountName, "a👩‍💻")
        event.update(completed: -1, total: -1)
        XCTAssertNil(event.completed)
        XCTAssertNil(event.total)
    }
}

final class ActivityIntegrationTests: XCTestCase {
    @MainActor func testModelTracksRunningCompletionAndCooldownWithoutMessageContent() async {
        let model = AppModel()
        model.status = .object(["bound_account_id": .integer(101)])
        await model.run("Discovering groups") {
            XCTAssertEqual(model.activity.first?.status, .running)
            XCTAssertEqual(model.activity.first?.kind, .discovery)
            XCTAssertEqual(model.activity.first?.accountID, "101")
        }
        XCTAssertEqual(model.activity.first?.status, .succeeded)
        await model.run("Inspecting selected / pending groups") {
            throw BackendFailure(code: "cooldown", message: "private synthetic content must not enter activity")
        }
        XCTAssertEqual(model.activity.first?.status, .warning)
        XCTAssertEqual(model.activity.first?.kind, .inspection)
        XCTAssertFalse(model.activity.contains { $0.title.contains("private synthetic") || $0.description.contains("private synthetic") })
        XCTAssertFalse(model.busy)
        await model.shutdown()
    }
}
