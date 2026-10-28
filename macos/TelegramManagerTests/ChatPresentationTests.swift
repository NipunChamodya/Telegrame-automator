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
    if method=='chats.list':
        query=params.get('query','').casefold()
        if query=='slow':time.sleep(.15)
        rows=[r for r in records if query in r['name'].casefold() and params.get('kind','all') in ('all',r['kind'])]
        start=params.get('page',0)*params.get('size',50)
        result={'chats':rows[start:start+params.get('size',50)],'total':len(rows)}
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
        app.selectedChat = ChatSummary(data: .object(["id": .integer(202), "kind": .string("private")]))
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
        let chat = ChatSummary(data: .object(["id": .integer(202), "kind": .string("private")]))
        app.selectedChat = chat; app.chatDraft = "Preserve this local draft 👩🏽‍💻"
        app.selectChat(chat)
        XCTAssertEqual(app.chatDraft, "Preserve this local draft 👩🏽‍💻")
        XCTAssertEqual(app.selectedChat?.id, 202)
        await app.shutdown()
    }
}
