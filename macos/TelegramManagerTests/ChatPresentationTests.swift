import XCTest
@testable import TelegramManager

final class ChatPresentationTests: XCTestCase {
    private func fixture() async throws -> (URL, BackendClient) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("tgm-chat-presentation-" + UUID().uuidString)
        let source = directory.appendingPathComponent("src")
        let package = source.appendingPathComponent("telegram_manager")
        try FileManager.default.createDirectory(at: package, withIntermediateDirectories: true)
        try Data().write(to: package.appendingPathComponent("__init__.py"))
        let script = #"""
import json,sys,pathlib,time
records=[{'id':202+i,'name':f'Community {i+1} ශ්‍රී தமிழ் 👩🏽‍💻','kind':'private' if i%2==0 else 'supergroup'} for i in range(198)]
for line in sys.stdin:
    request=json.loads(line); method=request['method']; params=request['params']
    with open(pathlib.Path(__file__).with_name('requests'),'a') as log:log.write(json.dumps(request)+'\n')
    result={}
    if (method in ('chatdraft.get','chatdraft.save') and params.get('destination')==909 and params.get('message')!='Resolved recovery') or (method=='messages.list' and params.get('destination') in (910,911)) or method=='contacts.list' or (method=='approvals' and params.get('query')=='failure'):
        if params.get('destination')==911:time.sleep(.15)
        print(json.dumps({'id':request['id'],'ok':False,'error':{'code':'fixture_failure','message':'Synthetic operation failed safely.'}}),flush=True)
        continue
    if method=='chats.list':
        query=params.get('query','').casefold()
        if query=='slow':time.sleep(.15)
        rows=[r for r in records if query in r['name'].casefold() and params.get('kind','all') in ('all',r['kind'])]
        start=params.get('page',0)*params.get('size',50)
        result={'chats':rows[start:start+params.get('size',50)],'total':len(rows)}
    if method=='chatdraft.get' and params.get('destination')==912:
        time.sleep(.15);result={'message':'An older saved draft'}
    if method=='messages.list':
        ids=[2,1] if params.get('offset_id',0) else [3,2]
        result={'messages':[{'id':i,'text':'needle','sender_name':'Synthetic sender','outgoing':False} for i in ids],'next_offset_id':ids[-1],'has_more':True}
    print(json.dumps({'id':request['id'],'ok':True,'result':result},ensure_ascii=False),flush=True)
    if method=='shutdown':break
"""#
        try script.write(to: package.appendingPathComponent("ipc.py"), atomically: true, encoding: .utf8)
        let python = URL(fileURLWithPath: "/opt/homebrew/bin/python3")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { throw XCTSkip("Fixture Python unavailable") }
        let client = BackendClient(runtime: (python, source))
        try await client.start()
        return (directory, client)
    }
    @MainActor private func model(_ client: BackendClient) -> AppModel {
        let model = AppModel(backend: client)
        model.backendOnline = true
        model.status = .object(["connected": .bool(true), "bound_account_id": .integer(101)])
        return model
    }
    private func requests(_ directory: URL) throws -> [[String: Any]] {
        let file = directory.appendingPathComponent("src/telegram_manager/requests")
        return try String(contentsOf: file, encoding: .utf8).split(separator: "\n").map { try JSONSerialization.jsonObject(with: Data($0.utf8)) as! [String: Any] }
    }
    @MainActor func testCached198RowsPaginateAndFilterWithoutTelegramRequests() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = model(client)
        await app.loadChats()
        XCTAssertEqual(app.chatTotal, 198); XCTAssertEqual(app.chats.count, 50)
        let first = app.chats.first?.id
        app.chatPage = 3; await app.loadChats()
        XCTAssertEqual(app.chats.count, 48); XCTAssertNotEqual(app.chats.first?.id, first)
        app.chatPage = 0; app.chatKind = "supergroup"; await app.loadChats()
        XCTAssertEqual(app.chatTotal, 99)
        app.chatKind = "all"; app.chatQuery = "Community 198"; await app.loadChats()
        XCTAssertEqual(app.chats.count, 1); XCTAssertTrue(app.chats[0].title.contains("தமிழ்"))
        XCTAssertTrue(try requests(directory).allSatisfy { $0["method"] as? String == "chats.list" })
        XCTAssertFalse(app.chatsLoading)
        await client.shutdown()
    }
    @MainActor func testStaleSearchResultDoesNotReplaceCurrentRows() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = model(client)
        await app.loadChats()
        let original = app.chats
        app.chatQuery = "slow"
        let pending = Task { await app.loadChats() }
        try await Task.sleep(nanoseconds: 30_000_000)
        app.chatQuery = "தமிழ்"
        await pending.value
        XCTAssertEqual(app.chats, original)
        await app.loadChats(); XCTAssertEqual(app.chatTotal, 198)
        await client.shutdown()
    }
    @MainActor func testMessageContinuationRetainsSearchAndDeduplicatesIDs() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = model(client)
        app.selectedChat = ChatSummary(data: .object(["id": .integer(202), "content_available": .bool(true), "kind": .string("private")]))
        await app.loadMessages(search: "needle")
        await app.loadMessages(older: true)
        XCTAssertEqual(app.chatMessages.map(\.id), [3,2,1])
        XCTAssertFalse(app.messagesLoading)
        let records = try requests(directory).filter { $0["method"] as? String == "messages.list" }
        XCTAssertEqual(records.count, 2)
        XCTAssertTrue(records.allSatisfy { ($0["params"] as? [String: Any])?["search"] as? String == "needle" })
        await client.shutdown()
    }
    @MainActor func testSelectingCurrentConversationDoesNotReloadOrClearDraft() async {
        let app = AppModel()
        let chat = ChatSummary(data: .object(["id": .integer(202), "content_available": .bool(true), "kind": .string("private")]))
        app.selectedChat = chat; app.chatDraft = "Preserve this local draft 👩🏽‍💻"
        app.selectChat(chat)
        XCTAssertEqual(app.chatDraft, "Preserve this local draft 👩🏽‍💻")
        XCTAssertEqual(app.selectedChat?.id, 202)
        await app.shutdown()
    }
    @MainActor func testNavigationRestorationIsLocalAndKeepsConversationScopes() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = model(client)
        for screen in Screen.allCases {
            app.restoreNavigation(to: screen)
            XCTAssertEqual(app.screen, screen)
            XCTAssertEqual(app.chatKind, screen == .groupChats ? "groups" : screen == .channels ? "channel" : "all")
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.appendingPathComponent("src/telegram_manager/requests").path))
        await client.shutdown()
    }
    @MainActor func testDraftReadFailureDoesNotPreventHistoryLoading() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = model(client)
        app.selectChat(ChatSummary(data: .object(["id": .integer(909), "content_available": .bool(true), "kind": .string("private")])))
        for _ in 0..<100 where app.chatMessages.isEmpty { try await Task.sleep(nanoseconds: 10_000_000) }
        XCTAssertEqual(app.chatMessages.map(\.id), [3,2]); XCTAssertFalse(app.messagesLoading)
        XCTAssertNotNil(app.errorMessage); XCTAssertNil(app.messagesError)
        XCTAssertTrue(try requests(directory).contains { $0["method"] as? String == "messages.list" })
        await app.shutdown()
    }
    @MainActor func testPreviousDraftSaveFailureDoesNotPreventNewConversationHistory() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = model(client)
        app.selectedChat = ChatSummary(data: .object(["id": .integer(909), "content_available": .bool(true), "kind": .string("private")]))
        app.chatDraft = "Synthetic unsaved draft සිංහල"
        app.selectChat(ChatSummary(data: .object(["id": .integer(202), "content_available": .bool(true), "kind": .string("private")])))
        for _ in 0..<100 where app.chatMessages.isEmpty { try await Task.sleep(nanoseconds: 10_000_000) }
        XCTAssertEqual(app.selectedChat?.id, 202); XCTAssertEqual(app.chatMessages.count, 2)
        XCTAssertFalse(app.messagesLoading); XCTAssertNotNil(app.errorMessage)
        app.selectChat(ChatSummary(data: .object(["id": .integer(909), "content_available": .bool(true), "kind": .string("private")])))
        XCTAssertEqual(app.chatDraft, "Synthetic unsaved draft සිංහල", "Failed writes retain account-scoped in-memory recovery")
        await app.shutdown()
    }
    @MainActor func testHistoryFailureHasScopedInlineErrorAndStopsLoading() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = model(client)
        app.selectedChat = ChatSummary(data: .object(["id": .integer(910), "content_available": .bool(true), "kind": .string("private")]))
        await app.loadMessages()
        XCTAssertEqual(app.messagesError, "Synthetic operation failed safely.")
        XCTAssertNil(app.errorMessage); XCTAssertFalse(app.messagesLoading)
        app.selectedChat = ChatSummary(data: .object(["id": .integer(202), "content_available": .bool(true), "kind": .string("private")]))
        await app.loadMessages()
        XCTAssertNil(app.messagesError); XCTAssertEqual(app.chatMessages.count, 2)
        await client.shutdown()
    }
    @MainActor func testStaleHistoryFailureDoesNotContaminateAnotherSelection() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = model(client)
        app.selectedChat = ChatSummary(data: .object(["id": .integer(911), "content_available": .bool(true), "kind": .string("private")]))
        let pending = Task { await app.loadMessages() }
        try await Task.sleep(nanoseconds: 30_000_000)
        app.selectedChat = ChatSummary(data: .object(["id": .integer(202), "content_available": .bool(true), "kind": .string("private")]))
        await pending.value
        XCTAssertNil(app.messagesError); XCTAssertFalse(app.messagesLoading)
        await client.shutdown()
    }
    @MainActor func testCachedContactsFailureIsVisibleWithoutReplacingData() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = model(client)
        await app.loadContacts()
        XCTAssertEqual(app.contactsError, "Synthetic operation failed safely.")
        XCTAssertFalse(app.contactsLoading); XCTAssertTrue(app.contacts.isEmpty)
        XCTAssertEqual(try requests(directory).filter { $0["method"] as? String == "contacts.refresh" }.count, 0)
        await client.shutdown()
    }

    @MainActor func testApprovalFailurePreservesCachedRecordsAndShowsRetryState() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = model(client)
        app.approvals = [TelegramGroup(data: .object(["id": .integer(-1001), "name": .string("Synthetic approved destination")]))]
        app.approvedSearch = "failure"
        await app.loadApprovals()
        XCTAssertEqual(app.approvals.count, 1)
        XCTAssertEqual(app.cachedErrors[.destinations], "Synthetic operation failed safely.")
        XCTAssertFalse(app.cachedLoading.contains(.destinations))
        app.approvedSearch = ""; await app.loadApprovals()
        XCTAssertNil(app.cachedErrors[.destinations])
        await client.shutdown()
    }
    @MainActor func testDelayedDraftHydrationDoesNotRestoreTextDeletedByTheUser() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = model(client)
        app.selectChat(ChatSummary(data: .object(["id": .integer(912), "content_available": .bool(true), "kind": .string("private")])))
        try await Task.sleep(nanoseconds: 30_000_000)
        app.userEditedConversation("New text", focused: false)
        app.userEditedConversation("", focused: false)
        for _ in 0..<100 where app.chatMessages.isEmpty { try await Task.sleep(nanoseconds: 10_000_000) }
        XCTAssertEqual(app.chatDraft, "")
        XCTAssertEqual(app.chatMessages.count, 2)
        XCTAssertFalse(app.messagesLoading)
        await app.shutdown()
    }
    @MainActor func testSuccessfulRecoveryAutosaveCannotResurrectAnOlderDraft() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = model(client)
        let broken = ChatSummary(data: .object(["id": .integer(909), "content_available": .bool(true), "kind": .string("private")]))
        let other = ChatSummary(data: .object(["id": .integer(202), "content_available": .bool(true), "kind": .string("private")]))
        app.selectedChat = broken; app.chatDraft = "Original unsaved text"
        app.selectChat(other)
        for _ in 0..<100 where app.chatMessages.isEmpty { try await Task.sleep(nanoseconds: 10_000_000) }
        app.selectChat(broken)
        for _ in 0..<100 where app.chatMessages.isEmpty { try await Task.sleep(nanoseconds: 10_000_000) }
        XCTAssertEqual(app.chatDraft, "Original unsaved text")
        app.userEditedConversation("Resolved recovery", focused: false)
        try await Task.sleep(nanoseconds: 1_000_000_000)
        app.selectChat(other)
        for _ in 0..<100 where app.chatMessages.isEmpty { try await Task.sleep(nanoseconds: 10_000_000) }
        app.selectChat(broken)
        XCTAssertEqual(app.chatDraft, "", "A successful write retires the stale transient recovery entry")
        await app.shutdown()
    }
    @MainActor func testOversizedUnsavedDraftDoesNotEnterRecoveryOrDiscardEditor() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = model(client)
        app.selectedChat = ChatSummary(data: .object(["id": .integer(202), "content_available": .bool(true), "kind": .string("private")]))
        app.chatDraft = String(repeating: "a", count: 4097)
        app.selectChat(ChatSummary(data: .object(["id": .integer(203), "content_available": .bool(true), "kind": .string("private")])))
        XCTAssertEqual(app.selectedChat?.id, 202); XCTAssertEqual(app.chatDraft.count, 4097)
        XCTAssertNotNil(app.errorMessage)
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.appendingPathComponent("src/telegram_manager/requests").path))
        await client.shutdown()
    }
}
