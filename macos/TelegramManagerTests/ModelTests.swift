import XCTest
import ImageIO
import CoreGraphics
@testable import TelegramManager

final class ModelTests: XCTestCase {
    func testUnicodeProtocolRoundTrip() throws {
        let names = ["ශ්‍රී ලංකා", "தமிழ் குழு", "👩🏽‍💻 🇱🇰 e\u{301}"]
        for name in names {
            let value = JSONValue.object(["name": .string(name), "id": .integer(-1001234567890)])
            let decoded = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(value))
            XCTAssertEqual(decoded, value)
            XCTAssertEqual(TelegramGroup(data: value).name, name)
            XCTAssertEqual(TelegramGroup(data: value).id, -1001234567890)
        }
    }
    func testComposerValidation() {
        XCTAssertNotNil(ComposerValidation.error(" \n"))
        XCTAssertNil(ComposerValidation.error("ශ්‍රී ලංකා 👩🏽‍💻"))
        XCTAssertEqual(ComposerValidation.units("😀"), 2)
        XCTAssertNil(ComposerValidation.error(String(repeating: "a", count: 4096)))
        XCTAssertNotNil(ComposerValidation.error(String(repeating: "😀", count: 2049)))
    }
    func testUnknownPermissionAndMissingMetadata() {
        let group = TelegramGroup(data: .object(["id": .integer(-1), "name": .string("Test"), "permission": .string("allowed"), "effective_permission": .string("unknown")]))
        XCTAssertEqual(group.permission, "unknown")
        XCTAssertEqual(group.members, "Unknown")
        XCTAssertTrue(group.reasons.isEmpty)
    }
    func testMetadataCompletenessDoesNotImplyFreshness() {
        let stale = TelegramGroup(data: .object(["metadata_status": .string("complete"), "metadata_fresh": .bool(false)]))
        XCTAssertEqual(stale.completeness, "Complete")
        XCTAssertEqual(stale.freshness, "Expired")
        let fresh = TelegramGroup(data: .object(["metadata_status": .string("complete"), "metadata_fresh": .bool(true)]))
        XCTAssertEqual(fresh.freshness, "Fresh")
        XCTAssertEqual(TelegramGroup(data: .object([:])).freshness, "Unknown")
    }
    func testControlsNeverDestroyValidJoiners() {
        XCTAssertEqual(safeDisplay("a\u{1b}\u{202e}👩\u{200d}💻"), "a👩‍💻")
    }
    @MainActor func testPreviewRequiresExactConfirmationAndConnection() {
        let model = AppModel()
        model.draft = "hello"
        model.destination = -1
        XCTAssertFalse(model.canPreview)
        model.backendOnline = true
        model.status = .object(["connected": .bool(true)])
        XCTAssertTrue(model.canPreview)
        model.preview = .object(["confirmation": .string("SEND -1"), "token": .string("opaque"), "message": .string("hello"), "destination": .integer(-1), "expires_at": .number(Date().timeIntervalSince1970 + 120)])
        model.confirmation = "yes"
        XCTAssertFalse(model.canSend)
        model.confirmation = "SEND -1"
        XCTAssertTrue(model.canSend)
        model.invalidatePreview()
        XCTAssertFalse(model.canSend)
    }
    @MainActor func testBackendStoppedClearsPreviewAndBusyState() {
        let model = AppModel()
        model.busy = true; model.backendOnline = true
        model.backendOnline = true
        model.status = .object(["connected": .bool(true)])
        model.preview = .object(["token": .string("opaque")])
        model.handle(.object(["event": .string("backend_stopped")]))
        XCTAssertFalse(model.busy)
        XCTAssertFalse(model.backendOnline)
        XCTAssertFalse(model.connected)
        XCTAssertNil(model.preview)
        XCTAssertNotNil(model.errorMessage)
    }
}

final class TransportTests: XCTestCase {
    private func fixture() async throws -> (URL, BackendClient) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("tgm-swift-fixture-" + UUID().uuidString)
        let source = directory.appendingPathComponent("src")
        let package = source.appendingPathComponent("telegram_manager")
        try FileManager.default.createDirectory(at: package, withIntermediateDirectories: true)
        try Data().write(to: package.appendingPathComponent("__init__.py"))
        let script = #"""
import json,sys,time,pathlib,os,signal
with open(pathlib.Path(__file__).with_name('starts'),'a') as marker: marker.write('x')
approved=[]
profile='a'
live=False
live_peer=0
action_status='acknowledged'
last_action='edit'
operations=[]
draft='saved draft'
records=[{'id':-1,'name':'ශ්‍රී ලංකා','kind':'group','permission':'unknown','effective_permission':'unknown'}, {'id':-2,'name':'Python Developers','kind':'supergroup','permission':'allowed','effective_permission':'allowed'}]
for line in sys.stdin:
    request=json.loads(line); method=request['method']
    with open(pathlib.Path(__file__).with_name('requests'),'a') as trace: trace.write(json.dumps(request)+'\n')
    if method=='startup_error':
        print(json.dumps({'id':None,'ok':False,'error':{'code':'already_running','message':'Another synthetic instance holds the lock.'}}),flush=True); sys.exit(0)
    if method=='crash': sys.exit(0)
    if method=='close_stdout':
        os.close(1); time.sleep(10); sys.exit(0)
    if method=='ignore_shutdown':
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        print(json.dumps({'id':request['id'],'ok':True,'result':{'pid':os.getpid()}}),flush=True)
        while True: time.sleep(1)
    if method=='hang': continue
    if method=='bad': print('invalid frame',flush=True);continue
    if method=='progress':
        print(json.dumps({'event':'progress','request_id':request['id'],'data':{'phase':'basic','index':1}},ensure_ascii=False),flush=True)
    params=request['params']
    if method=='enable_live': live=True
    if method=='enable_uncertain_actions': action_status='uncertain'
    result={'method':method,'unicode':'ශ්‍රී தமிழ் 👩🏽‍💻','params':params}
    if method in ('status','connect'): result={'connected':True,'account':{'id':13,'display_name':'Fixture account'},'bound_account_id':13,'cooldown_until':time.time()+16,'overview':{'total':2,'allowed':1,'unknown':1,'denied':0,'pending':1}}
    if method in ('status','connect'):
        result['profile_id']=profile
        if live: result['account_generation']=0
    if method=='updates.watch':
        pathlib.Path(__file__).with_name('watching').write_text('watch entered')
        if live: time.sleep(0.1)
        live_peer=params.get('peer_id',0)
        result={'profile_id':profile,'account_id':13,'account_generation':0,'stream_id':'fixture-stream','peer_id':live_peer,'watching':True,'sequence':0,'dirty':False}
    if method=='sync.snapshot':
        result={'profile_id':profile,'account_id':13,'account_generation':0,'stream_id':'fixture-stream','peer_id':live_peer,'sequence':0,'dirty':False,'chats':[],'messages':[{'id':1,'text':'current','content_available':True}]}
    if method=='messages.list':
        time.sleep(0.15)
        result={'messages':[{'id':1,'text':'stale old body','content_available':True}],'has_more':False,'next_offset_id':1}
    if method=='accounts.switch':
        profile=params['profile_id']; draft='other account draft'; approved=[]
        result={'profiles':[], 'status':{'profile_id':profile,'connected':False,'bound_account_id':13}}
    if method=='accounts.list': result={'profiles':[]}
    if method=='chatdraft.get': result={'message':'personal saved draft','updated_at':'now'}
    if method=='message.action.preview':
        time.sleep(0.04)
        action=params['action']; last_action=action; destination=params['destination']; identity=params['message_id']
        result={'profile_id':profile,'account_generation':0,'account_id':13,'token':'mutation-fixture','action':action,'destination':destination,'message_id':identity,'original_text':'original','message':params.get('message',''),'expires_at':time.time()+120,'delete_for_everyone':False,'confirmation':('EDIT '+str(identity)+' IN '+str(destination)) if action=='edit' else ('DELETE '+str(identity)+' FROM '+str(destination))}
    if method=='message.action.commit':
        operation={'id':len(operations)+1,'account':13,'destination':91,'message_id':1,'action':last_action,'status':action_status,'detail':'synthetic fixture only'}
        operations.append(operation)
        result={'profile_id':profile,'account_generation':0,'operation':operation}
    if method=='message.operations': result={'operations':operations}
    if method=='contacts.list':
        contacts=[{'id':202,'name':'தமிழ் Contact','username':'tamil_contact','mutual':True,'verified':False,'has_photo':False,'content_available':True}, {'id':203,'name':'ශ්‍රී ලංකා Contact','username':'sinhala_contact','mutual':False,'verified':False,'has_photo':True,'content_available':True}]
        contacts=[r for r in contacts if params.get('query','').casefold() in (r['name']+' '+r['username']).casefold()]
        page=params.get('page',0); size=params.get('size',50)
        result={'contacts':contacts[page*size:(page+1)*size],'total':len(contacts),'page':page,'size':size}
    if method=='contacts.refresh': result={'processed':2,'cached_count':2,'truncated':False}
    if method=='contacts.open': result={'chat':{'id':params['user_id'],'name':'தமிழ் Contact','kind':'private','content_available':True}}
    if method=='profile.get': result={'profile':{'id':params['peer_id'],'name':'தமிழ் Contact','kind':'private','username':'tamil_contact','about':'A real-shape synthetic profile','verified':False,'has_photo':True,'checked_at':'2026-10-28T00:00:00+00:00','content_available':True}}
    if method in ('folders.list','folders.refresh'): result={'folders':[{'id':2,'title':'Work','contacts':True,'include_peer_ids':[202],'exclude_peer_ids':[],'pinned_peer_ids':[]}],'source':'telegram_read_only','membership_supported':False}
    if method=='media.preview.get':
        path=pathlib.Path(__file__).with_name('preview.png')
        result={'token':'image-fixture','path':str(path),'bytes':path.stat().st_size,'mime_type':'image/png','profile_id':profile,'account_generation':0,'destination':params['destination'],'message_id':params['message_id']}
    if method=='media.preview.release': result={'released':True}
    if method=='groups':
        rows=[r for r in records if params.get('query','').casefold() in r['name'].casefold() and params.get('permission','all') in ('all',r['permission']) and params.get('kind','all') in ('all',r['kind'])]
        result={'groups':rows,'total':len(rows)}
    if method=='detail': result={'group':next(r for r in records if r['id']==params['destination'])}
    if method=='approvals': result={'groups':[r for r in records if r['id'] in approved]}
    if method=='approval.set':
        if params['approved']: approved.append(params['destination'])
        else: approved=[v for v in approved if v!=params['destination']]
        result={'approved':params['approved']}
    if method=='draft.get': result={'message':draft,'updated_at':'2026-10-28T00:00:00+00:00'}
    if method=='draft.save': draft=params['message']; result={'message':draft,'updated_at':'2026-10-28T00:00:00+00:00'}
    if method=='history': result={'deliveries':[]}
    if method=='settings': result={'inspection_limit':10,'cache_policy':{'basic':86400,'permissions':900,'members':3600,'metadata':21600}}
    if method=='preview':
        time.sleep(0.05)
        result={'token':'fixture-token','destination':params['destination'],'message':params['message'],'confirmation':'SEND '+str(params['destination']),'expires_at':time.time()+120}
    print(json.dumps({'id':request['id'],'ok':True,'result':result},ensure_ascii=False),flush=True)
    if method=='shutdown': break
"""#
        try script.write(to: package.appendingPathComponent("ipc.py"), atomically: true, encoding: .utf8)
        let python = URL(fileURLWithPath: "/opt/homebrew/bin/python3")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { throw XCTSkip("Fixture Python is unavailable") }
        let client = BackendClient(runtime: (python, source))
        try await client.start()
        return (directory, client)
    }
    @MainActor func testCooldownFailureReloadsCommittedStatusWithoutRetry() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(backend: client)
        model.backendOnline = true
        var attempts = 0
        await model.run("Discovery") {
            attempts += 1
            throw BackendFailure(code: "cooldown", message: "Telegram requested a cooldown.")
        }
        XCTAssertEqual(attempts, 1)
        XCTAssertGreaterThan(model.status["cooldown_until"].doubleValue, Date().timeIntervalSince1970)
        XCTAssertFalse(model.busy)
        XCTAssertEqual(model.errorMessage, "Telegram requested a cooldown.")
        await client.shutdown()
    }
    func testConcurrentRequestsUnicodeAndGracefulShutdown() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        async let one = client.request("one", params: ["id": .integer(-1001234567890)])
        async let two = client.request("two")
        let values = try await [one, two]
        XCTAssertEqual(values[0]["method"].string, "one")
        XCTAssertEqual(values[1]["method"].string, "two")
        XCTAssertEqual(values[0]["unicode"].string, "ශ්‍රී தமிழ் 👩🏽‍💻")
        XCTAssertEqual(values[0]["params"]["id"].int, -1001234567890)
        await client.shutdown()
    }
    func testTimeoutIsReportedWithoutRetry() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        do { _ = try await client.request("hang", timeout: 0.1); XCTFail("Expected timeout") }
        catch let error as BackendFailure { XCTAssertEqual(error.code, "timeout") }
        await client.shutdown()
    }
    func testUnexpectedShutdownAndMalformedResponse() async throws {
        for method in ["crash", "bad"] {
            let (directory, client) = try await fixture()
            do { _ = try await client.request(method, timeout: 2); XCTFail("Expected failure") }
            catch let error as BackendFailure { XCTAssertTrue(["backend_unavailable", "protocol_error"].contains(error.code)) }
            await client.shutdown()
            try? FileManager.default.removeItem(at: directory)
        }
    }
    func testCancellationAndProgress() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let expectation = expectation(description: "Progress received")
        await client.setEventHandler { event in if event["event"].string == "progress" { expectation.fulfill() } }
        _ = try await client.request("progress")
        await fulfillment(of: [expectation], timeout: 2)
        let task = Task { try await client.request("hang", timeout: 10) }
        try await Task.sleep(nanoseconds: 50_000_000)
        task.cancel()
        do { _ = try await task.value; XCTFail("Expected cancellation") } catch is CancellationError {} catch { XCTFail("Wrong cancellation error") }
        await client.shutdown()
    }
    @MainActor func testGroupSearchFilteringSelectionAndApprovalState() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(backend: client)
        model.backendOnline = true
        model.status = .object(["connected": .bool(true), "account": .object(["id": .integer(13)])])
        model.search = "ශ්‍රී"; model.permissionFilter = "unknown"
        await model.loadGroups()
        XCTAssertEqual(model.groups.count, 1)
        XCTAssertEqual(model.groups.first?.name, "ශ්‍රී ලංකා")
        model.select(-1)
        for _ in 0..<50 { if model.detail != nil { break }; try await Task.sleep(nanoseconds: 10_000_000) }
        XCTAssertEqual(model.detail?.id, -1)
        model.setApproval(-1, approved: true)
        for _ in 0..<50 { if !model.approvals.isEmpty { break }; try await Task.sleep(nanoseconds: 10_000_000) }
        XCTAssertEqual(model.approvals.map(\.id), [-1])
        model.destination = -1
        model.setApproval(-1, approved: false)
        for _ in 0..<50 { if model.approvals.isEmpty && !model.busy { break }; try await Task.sleep(nanoseconds: 10_000_000) }
        XCTAssertTrue(model.approvals.isEmpty)
        XCTAssertNil(model.destination)
        model.search = "no matching group"; await model.loadGroups()
        XCTAssertTrue(model.groups.isEmpty)
        await client.shutdown()
    }
    @MainActor func testLatePreviewIsDiscardedAndReconnectPreservesUnsavedDraft() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(backend: client)
        model.backendOnline = true
        model.status = .object(["connected": .bool(true), "account": .object(["id": .integer(13)])])
        model.draft = "first message"; model.destination = -1
        model.preparePreview()
        model.draft = "changed while checking"; model.invalidatePreview()
        for _ in 0..<50 { try await Task.sleep(nanoseconds: 10_000_000); if !model.busy { break } }
        XCTAssertNil(model.preview)
        XCTAssertFalse(model.canSend)
        await model.refreshAll()
        XCTAssertEqual(model.draft, "changed while checking")
        XCTAssertTrue(model.draftDirty)
        XCTAssertEqual(model.status["overview"]["total"].int, 2)
        await client.shutdown()
    }
    @MainActor func testAccountSwitchSavesOldDraftThenClearsContext() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(backend: client)
        model.backendOnline = true
        model.status = .object(["connected": .bool(true), "profile_id": .string("a"), "bound_account_id": .integer(13)])
        model.draft = "old account unsaved draft"
        model.selectedChat = ChatSummary(data: .object(["id": .integer(91), "content_available": .bool(true), "kind": .string("private")]))
        model.chatDraft = "old conversation unsaved draft"
        model.chatConfirmation = "SEND 91"
        model.switchProfile(AccountProfile(data: .object(["profile_id": .string("b")])) )
        try await Task.sleep(nanoseconds: 300_000_000)
        XCTAssertFalse(model.busy)
        XCTAssertEqual(model.activeProfileID, "b")
        XCTAssertNil(model.selectedChat)
        XCTAssertNil(model.chatPreview)
        XCTAssertEqual(model.chatConfirmation, "")
        XCTAssertEqual(model.draft, "other account draft")
        let trace = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/requests"), encoding: .utf8).split(separator: "\n").map { try JSONDecoder().decode(JSONValue.self, from: Data($0.utf8)) }
        let methods = trace.map { $0["method"].string }
        XCTAssertLessThan(try XCTUnwrap(methods.firstIndex(of: "draft.save")), try XCTUnwrap(methods.firstIndex(of: "accounts.switch")))
        XCTAssertLessThan(try XCTUnwrap(methods.firstIndex(of: "chatdraft.save")), try XCTUnwrap(methods.firstIndex(of: "accounts.switch")))
        await client.shutdown()
    }
    @MainActor func testDebouncedUnicodeDraftSave() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(backend: client)
        model.backendOnline = true; model.status = .object(["bound_account_id": .integer(13)])
        model.draft = "தமிழ் 👩‍💻"; model.scheduleDraftSave()
        model.draft = "ශ්‍රී ලංකා 👩‍💻"; model.scheduleDraftSave()
        try await Task.sleep(nanoseconds: 1_000_000_000)
        let saved = try await client.request("draft.get")
        XCTAssertEqual(saved["message"].string, "ශ්‍රී ලංකා 👩‍💻")
        XCTAssertFalse(model.draftDirty)
        await client.shutdown()
    }
    @MainActor func testRepeatedReconnectHasOneHealthAndConnect() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(backend: client); model.backendOnline = true
        for _ in 0..<10 { model.reconnect() }
        try await Task.sleep(nanoseconds: 350_000_000)
        let trace = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/requests"), encoding: .utf8).split(separator: "\n").map { try JSONDecoder().decode(JSONValue.self, from: Data($0.utf8))["method"].string }
        XCTAssertEqual(trace.filter { $0 == "health" }.count, 1)
        XCTAssertEqual(trace.filter { $0 == "connect" }.count, 1)
        XCTAssertFalse(model.isConnecting)
        await client.shutdown()
    }
    @MainActor func testContactsCachedSearchOpenAndProfileUseRealShapeWithoutSending() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(backend: client); model.backendOnline = true
        model.status = .object(["connected": .bool(true), "profile_id": .string("a"), "account_generation": .integer(0), "bound_account_id": .integer(13)])
        await model.loadContacts()
        XCTAssertEqual(model.contactTotal, 2)
        model.contactQuery = "tamil_contact"; await model.loadContacts()
        XCTAssertEqual(model.contacts.map(\.id), [202])
        model.openContact(202)
        try await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertEqual(model.selectedChat?.id, 202); XCTAssertEqual(model.screen, .chats)
        model.showProfile(202)
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(model.profileTarget?.id, 202); XCTAssertEqual(model.profileTarget?.name, "தமிழ் Contact")
        let trace = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/requests"), encoding: .utf8)
        XCTAssertFalse(trace.contains("chat.send")); XCTAssertFalse(trace.contains("contacts.refresh"))
        await model.shutdown()
    }
    @MainActor func testFoldersAreCachedDefinitionsUntilExplicitRefresh() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(backend: client); model.backendOnline = true
        model.status = .object(["connected": .bool(true), "profile_id": .string("a"), "account_generation": .integer(0), "bound_account_id": .integer(13)])
        await model.loadFolders()
        XCTAssertEqual(model.telegramFolders.first?["title"].string, "Work")
        var trace = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/requests"), encoding: .utf8)
        XCTAssertFalse(trace.contains("folders.refresh"))
        model.refreshFolders(); try await Task.sleep(nanoseconds: 100_000_000)
        trace = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/requests"), encoding: .utf8)
        XCTAssertEqual(trace.components(separatedBy: "folders.refresh").count - 1, 1)
        await model.shutdown()
    }
    @MainActor func testImagePreviewExplicitDownloadAndDismissReleasesHeldToken() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("src/telegram_manager/preview.png")
        let context = try XCTUnwrap(CGContext(data: nil, width: 32, height: 32, bitsPerComponent: 8, bytesPerRow: 128, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(file as CFURL, "public.png" as CFString, 1, nil))
        CGImageDestinationAddImage(destination, try XCTUnwrap(context.makeImage()), nil)
        XCTAssertTrue(CGImageDestinationFinalize(destination)); XCTAssertEqual(chmod(file.path, 0o600), 0)
        let model = AppModel(backend: client); model.backendOnline = true
        model.status = .object(["connected": .bool(true), "profile_id": .string("a"), "account_generation": .integer(0), "bound_account_id": .integer(13)])
        model.selectedChat = ChatSummary(data: .object(["id": .integer(91), "kind": .string("private"), "content_available": .bool(true)]))
        let message = ChatMessage(data: .object(["id": .integer(1), "content_available": .bool(true), "media": .object(["mime_type": .string("image/png")])]))
        model.chatMessages = [message]
        model.openMediaPreview(message)
        try await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertNotNil(model.previewImage); XCTAssertEqual(model.mediaPreview?.messageID, 1)
        model.mediaPreview = nil // SwiftUI clears an item binding before onDismiss.
        model.closeMediaPreview(); try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertNil(model.previewImage)
        let trace = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/requests"), encoding: .utf8)
        XCTAssertEqual(trace.components(separatedBy: "media.preview.get").count - 1, 1)
        XCTAssertEqual(trace.components(separatedBy: "media.preview.release").count - 1, 1)
        await model.shutdown()
    }
    @MainActor func testMessageActionRequiresExactConfirmationAndCommitsOnceToSeparateLedger() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(backend: client); model.backendOnline = true
        model.status = .object(["connected": .bool(true), "profile_id": .string("a"), "account_generation": .integer(0), "bound_account_id": .integer(13)])
        model.selectedChat = ChatSummary(data: .object(["id": .integer(91), "name": .string("Personal contact"), "kind": .string("private"), "content_available": .bool(true)]))
        let message = ChatMessage(data: .object(["id": .integer(1), "text": .string("original"), "outgoing": .bool(true), "content_available": .bool(true), "can_request_edit": .bool(true)]))
        model.beginMessageAction("edit", message: message)
        model.messageActionDraft = "revised தமிழ் 👩‍💻"
        model.previewMessageAction()
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertNotNil(model.messageActionPreview)
        model.messageActionConfirmation = "yes"
        XCTAssertFalse(model.canCommitMessageAction)
        model.commitMessageAction()
        model.messageActionConfirmation = "EDIT 1 IN 91"
        XCTAssertTrue(model.canCommitMessageAction)
        model.commitMessageAction(); model.commitMessageAction()
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(model.messageActionResult?["status"].string, "acknowledged")
        XCTAssertTrue(model.messageActionSubmitted); XCTAssertFalse(model.canCommitMessageAction)
        XCTAssertEqual(model.messageOperations.count, 1); XCTAssertTrue(model.deliveries.isEmpty)
        let trace = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/requests"), encoding: .utf8)
        XCTAssertEqual(trace.components(separatedBy: "message.action.commit").count - 1, 1)
        await model.shutdown()
    }
    @MainActor func testMessageActionUncertainOutcomeCannotBeRetriedInSameApproval() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        _ = try await client.request("enable_uncertain_actions")
        let model = AppModel(backend: client); model.backendOnline = true
        model.status = .object(["connected": .bool(true), "profile_id": .string("a"), "account_generation": .integer(0), "bound_account_id": .integer(13)])
        model.selectedChat = ChatSummary(data: .object(["id": .integer(91), "kind": .string("private"), "content_available": .bool(true)]))
        model.beginMessageAction("delete", message: ChatMessage(data: .object(["id": .integer(1), "text": .string("original"), "outgoing": .bool(true), "content_available": .bool(true), "can_request_delete": .bool(true)])))
        model.previewMessageAction(); try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(model.messageActionPreview?["delete_for_everyone"].bool, false)
        model.messageActionConfirmation = "DELETE 1 FROM 91"
        model.commitMessageAction(); try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(model.messageActionResult?["status"].string, "uncertain")
        XCTAssertFalse(model.canPreviewMessageAction); XCTAssertFalse(model.canCommitMessageAction)
        await model.shutdown()
    }
    @MainActor func testWatchSnapshotAndLateHistoryCannotResurrectDeletedMessage() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        _ = try await client.request("enable_live")
        let model = AppModel(backend: client); model.backendOnline = true
        await model.refreshAll()
        model.selectChat(ChatSummary(data: .object(["id": .integer(91), "kind": .string("private"), "content_available": .bool(true)])))
        try await Task.sleep(nanoseconds: 400_000_000)
        XCTAssertEqual(model.chatMessages.first?.text, "current")
        XCTAssertEqual(model.liveProjection?.streamID, "fixture-stream")
        model.chatReply = 1
        model.chatPreview = .object(["token": .string("must clear")])
        let history = Task { await model.loadMessages(older: true) }
        try await Task.sleep(nanoseconds: 30_000_000)
        model.handle(.object(["event": .string("message.deleted"), "data": .object(["profile_id": .string("a"), "account_id": .integer(13), "account_generation": .integer(0), "stream_id": .string("fixture-stream"), "peer_id": .integer(91), "sequence": .integer(1), "message_ids": .array([.integer(1)])])]))
        XCTAssertNil(model.chatReply); XCTAssertNil(model.chatPreview)
        await history.value
        XCTAssertTrue(model.chatMessages.isEmpty, "A late page must not resurrect deleted content")
        let trace = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/requests"), encoding: .utf8).split(separator: "\n").map { try JSONDecoder().decode(JSONValue.self, from: Data($0.utf8))["method"].string }
        XCTAssertEqual(trace.filter { $0 == "sync.snapshot" }.count, 1)
        XCTAssertEqual(trace.filter { $0 == "messages.list" }.count, 1, "Only the explicit older-page request fetches separate history")
        await model.shutdown()
    }
    @MainActor func testPreWatchOverflowKeepsRepairRequiredAndClearsEphemeralBodies() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        _ = try await client.request("enable_live")
        let model = AppModel(backend: client); model.backendOnline = true
        model.chatMessages = [ChatMessage(data: .object(["id": .integer(1), "text": .string("stale"), "content_available": .bool(true)]))]
        model.chatReply = 1; model.chatPreview = .object(["token": .string("stale")])
        let refresh = Task { await model.refreshAll() }
        let marker = directory.appendingPathComponent("src/telegram_manager/watching")
        for _ in 0..<30 { if FileManager.default.fileExists(atPath: marker.path) { break }; try await Task.sleep(nanoseconds: 5_000_000) }
        XCTAssertTrue(FileManager.default.fileExists(atPath: marker.path))
        for sequence in 1...140 {
            model.handle(.object(["event": .string("message.deleted"), "data": .object(["profile_id": .string("a"), "account_id": .integer(13), "account_generation": .integer(0), "stream_id": .string("fixture-stream"), "peer_id": .integer(91), "sequence": .integer(sequence), "message_ids": .array([.integer(1)])])]))
        }
        await refresh.value
        XCTAssertTrue(model.liveRepairNeeded); XCTAssertEqual(model.liveProjection?.dirty, true)
        XCTAssertTrue(model.chatMessages.isEmpty); XCTAssertNil(model.chatReply); XCTAssertNil(model.chatPreview)
        await model.shutdown()
    }
    @MainActor func testLoadedHistoryAndHydratedDraftDoNotReportReadOrTyping() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        _ = try await client.request("health")
        let model = AppModel(backend: client); model.backendOnline = true
        model.status = .object(["connected": .bool(true), "profile_id": .string("a"), "account_generation": .integer(0), "bound_account_id": .integer(13)])
        model.selectedChat = ChatSummary(data: .object(["id": .integer(91), "kind": .string("private"), "content_available": .bool(true)]))
        model.chatMessages = [ChatMessage(data: .object(["id": .integer(100), "text": .string("unseen"), "content_available": .bool(true)]))]
        model.chatDraft = "hydrated draft"
        model.setConversationFocused(true, automaticRead: true)
        try await Task.sleep(nanoseconds: 220_000_000)
        let trace = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/requests"), encoding: .utf8)
        XCTAssertFalse(trace.contains("messages.read")); XCTAssertFalse(trace.contains("messages.typing"))
        await client.shutdown()
    }
    @MainActor func testReadFrontierUsesVisibleIncomingAndFocusOnly() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        _ = try await client.request("health")
        let model = AppModel(backend: client); model.backendOnline = true
        model.status = .object(["connected": .bool(true), "profile_id": .string("a"), "account_generation": .integer(0), "bound_account_id": .integer(13)])
        model.selectedChat = ChatSummary(data: .object(["id": .integer(91), "kind": .string("private"), "content_available": .bool(true)]))
        model.chatMessages = [ChatMessage(data: .object(["id": .integer(42), "content_available": .bool(true)])), ChatMessage(data: .object(["id": .integer(100), "content_available": .bool(true), "outgoing": .bool(true)]))]
        model.messageVisibilityChanged(id: 42, peer: 91, incoming: true, visible: true)
        try await Task.sleep(nanoseconds: 200_000_000)
        var trace = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/requests"), encoding: .utf8)
        XCTAssertFalse(trace.contains("messages.read"))
        model.setConversationFocused(true, automaticRead: true)
        model.messageVisibilityChanged(id: 100, peer: 91, incoming: false, visible: true)
        try await Task.sleep(nanoseconds: 220_000_000)
        let rows = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/requests"), encoding: .utf8).split(separator: "\n").map { try JSONDecoder().decode(JSONValue.self, from: Data($0.utf8)) }
        let reads = rows.filter { $0["method"].string == "messages.read" }
        XCTAssertEqual(reads.count, 1); XCTAssertEqual(reads.first?["params"]["max_id"].int, 42)
        model.setConversationFocused(false)
        model.messageVisibilityChanged(id: 99, peer: 91, incoming: true, visible: true)
        try await Task.sleep(nanoseconds: 200_000_000)
        trace = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/requests"), encoding: .utf8)
        XCTAssertEqual(trace.components(separatedBy: "messages.read").count - 1, 1)
        await client.shutdown()
    }
    @MainActor func testTypingRequiresActualFocusedEditorEditsAndCancelsOnBlur() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        _ = try await client.request("health")
        let model = AppModel(backend: client); model.backendOnline = true
        model.status = .object(["connected": .bool(true), "profile_id": .string("a"), "account_generation": .integer(0), "bound_account_id": .integer(13)])
        model.selectedChat = ChatSummary(data: .object(["id": .integer(91), "kind": .string("private"), "content_available": .bool(true)]))
        model.setConversationFocused(true, automaticRead: true)
        model.userEditedConversation("hello", focused: true)
        model.userEditedConversation("hello there", focused: true)
        try await Task.sleep(nanoseconds: 80_000_000)
        model.stopConversationTyping()
        try await Task.sleep(nanoseconds: 80_000_000)
        let rows = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/requests"), encoding: .utf8).split(separator: "\n").map { try JSONDecoder().decode(JSONValue.self, from: Data($0.utf8)) }
        let typing = rows.filter { $0["method"].string == "messages.typing" }
        XCTAssertEqual(typing.count, 2)
        XCTAssertEqual(typing.first?["params"]["active"].bool, true)
        XCTAssertEqual(typing.last?["params"]["active"].bool, false)
        await model.shutdown()
    }
    func testTypedStartupFailureSurvivesImmediateExitWithoutRespawn() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        do { _ = try await client.request("startup_error"); XCTFail("Expected startup error") }
        catch let failure as BackendFailure { XCTAssertEqual(failure.code, "already_running") }
        for _ in 0..<5 {
            do { _ = try await client.request("status"); XCTFail("Must stay stopped") }
            catch let failure as BackendFailure { XCTAssertEqual(failure.code, "already_running") }
        }
        XCTAssertEqual(try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/starts"), encoding: .utf8), "x")
        await client.shutdown()
    }
    func testConcurrentShutdownCompletesWithoutStartingReplacement() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        _ = try await client.request("health")
        await withTaskGroup(of: Void.self) { group in
            for _ in 0..<8 { group.addTask { await client.shutdown() } }
        }
        XCTAssertEqual(try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/starts"), encoding: .utf8), "x")
    }
    func testConcurrentExplicitStartsLaunchOneChild() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        try await withThrowingTaskGroup(of: Void.self) { group in
            for _ in 0..<12 { group.addTask { try await client.start() } }
            try await group.waitForAll()
        }
        _ = try await client.request("health")
        let starts = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/starts"), encoding: .utf8)
        XCTAssertEqual(starts, "x")
        await client.shutdown()
    }
    func testCachedRequestsNeverRespawnAfterFailure() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        do { _ = try await client.request("crash", timeout: 1); XCTFail("Expected exit") } catch {}
        for _ in 0..<8 {
            do { _ = try await client.request("status", timeout: 0.1); XCTFail("Must require explicit restart") } catch {}
        }
        let starts = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/starts"), encoding: .utf8)
        XCTAssertEqual(starts, "x")
        await client.shutdown()
    }
    func testChildClosingStdoutFailsPromptlyWithoutParentWriterLeak() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let began = Date()
        do { _ = try await client.request("close_stdout", timeout: 4); XCTFail("Expected EOF") } catch {}
        XCTAssertLessThan(Date().timeIntervalSince(began), 2)
        await client.shutdown()
    }
    func testShutdownWaitsForUncooperativeOwnedChild() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let reply = try await client.request("ignore_shutdown")
        let pid = Int32(reply["pid"].int)
        await client.shutdown()
        XCTAssertEqual(Darwin.kill(pid, 0), -1)
        XCTAssertEqual(errno, ESRCH)
        do { _ = try await client.request("health"); XCTFail("Stopped client must not restart") } catch {}
    }
    func testShutdownDoesNotRestartTerminatedBackend() async throws {
        let (directory, client) = try await fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        do { _ = try await client.request("crash", timeout: 2); XCTFail("Expected termination") }
        catch { }
        await client.shutdown()
        await client.shutdown()
        let starts = try String(contentsOf: directory.appendingPathComponent("src/telegram_manager/starts"), encoding: .utf8)
        XCTAssertEqual(starts, "x")
    }
    func testLargeIntegersAreExactAndUnsafeNumbersCannotTrap() throws {
        let value = try JSONDecoder().decode(JSONValue.self, from: Data("9223372036854775807".utf8))
        XCTAssertEqual(value.string, "9223372036854775807")
        XCTAssertEqual(value.int, Int.max)
        XCTAssertEqual(JSONValue.number(.infinity).int, 0)
        XCTAssertEqual(JSONValue.number(1e100).int, 0)
    }
    func testSafeFileImportRejectsSymlinksAndOversizedMessages() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("message.txt"), link = directory.appendingPathComponent("link.txt")
        try "ශ්‍රී தமிழ் 👩🏽‍💻".write(to: file, atomically: true, encoding: .utf8)
        XCTAssertEqual(try readBoundedUTF8File(file), "ශ්‍රී தமிழ் 👩🏽‍💻")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: file)
        XCTAssertThrowsError(try readBoundedUTF8File(link))
        try String(repeating: "a", count: 4097).write(to: file, atomically: true, encoding: .utf8)
        XCTAssertThrowsError(try readBoundedUTF8File(file))
    }
}

final class WorkspaceStateTests: XCTestCase {
    func testProfileIdentityDoesNotUseTelegramID() {
        let profile = AccountProfile(data: .object(["profile_id": .string("profile_a"), "telegram_id": .integer(1234567890123), "label": .string("ශ්‍රී ලංකා 👩‍💻")]))
        XCTAssertEqual(profile.id, "profile_a")
        XCTAssertEqual(profile.accountID, "1234567890123")
        XCTAssertEqual(profile.title, "ශ්‍රී ලංකා 👩‍💻")
    }
    func testOnlyPersonalConversationAllowsComposer() {
        for kind in ["group", "supergroup", "channel", "unknown"] {
            XCTAssertFalse(ChatSummary(data: .object(["kind": .string(kind)])).allowsPersonalSend)
        }
        XCTAssertTrue(ChatSummary(data: .object(["content_available": .bool(true), "kind": .string("saved")])).allowsPersonalSend)
    }
    @MainActor func testPersonalPreviewBindsAccountDestinationAndExactText() {
        let model = AppModel()
        model.backendOnline = true
        model.status = .object(["connected": .bool(true), "account": .object(["id": .integer(41)])])
        model.selectedChat = ChatSummary(data: .object(["id": .integer(91), "content_available": .bool(true), "kind": .string("private")]))
        model.chatDraft = "தமிழ் 👩‍💻"
        model.chatPreview = .object(["account_id": .integer(41), "destination": .integer(91), "message": .string(model.chatDraft), "confirmation": .string("SEND 91"), "expires_at": .number(Date().timeIntervalSince1970 + 120)])
        model.chatConfirmation = "SEND 91"
        XCTAssertTrue(model.chatCanSend)
        model.status = .object(["connected": .bool(true), "account": .object(["id": .integer(42)])])
        XCTAssertFalse(model.chatCanSend)
        model.invalidateChatPreview()
        XCTAssertNil(model.chatPreview)
        XCTAssertEqual(model.chatConfirmation, "")
    }
    @MainActor func testDeadBackendPreventsPersonalPreview() {
        let model = AppModel()
        model.status = .object(["connected": .bool(true)])
        model.selectedChat = ChatSummary(data: .object(["id": .integer(91), "content_available": .bool(true), "kind": .string("private")]))
        model.chatDraft = "hello"
        XCTAssertFalse(model.chatCanPreview)
    }
}

final class RecoveryStateTests: XCTestCase {
    @MainActor func testLockConflictHasLocalDiagnosticsWithoutRPC() async {
        let model = AppModel()
        await model.run("Starting") { throw BackendFailure(code: "already_running", message: "Another instance is running.") }
        XCTAssertEqual(model.connectionTitle, "Another instance is running")
        XCTAssertFalse(model.backendOnline)
        XCTAssertTrue(model.connectionActionAvailable)
        model.openDiagnostics()
        XCTAssertTrue(model.diagnosticsPresented)
        XCTAssertTrue(model.diagnosticsSummary.contains("do not delete"))
    }
    @MainActor func testValidationDoesNotClassifyBackendUnavailable() async {
        let model = AppModel(); model.backendOnline = true
        await model.run("Validate") { throw BackendFailure(code: "validation", message: "Select one group.") }
        XCTAssertTrue(model.backendOnline)
        XCTAssertNotEqual(model.connectionTitle, "Backend unavailable")
    }
    @MainActor func testIntentionalShutdownIgnoresTerminationError() async {
        let model = AppModel()
        await model.shutdown()
        model.handle(.object(["event": .string("backend_stopped"), "data": .object(["error": .object(["code": .string("backend_unavailable"), "message": .string("Stopped")])])]))
        XCTAssertNil(model.errorMessage)
        XCTAssertFalse(model.connectionActionAvailable)
    }
}

final class LocalDiagnosticsTests: XCTestCase {
    func testLocalDiagnosticsNeverStartsBackendOrExposesRuntimeEnvironment() async {
        let client = BackendClient()
        let details = await client.localDiagnostics()
        XCTAssertTrue(details.contains("Managed child running: No"))
        XCTAssertTrue(details.contains("Managed child PID: None"))
        XCTAssertTrue(details.contains("Outstanding requests: 0"))
        XCTAssertFalse(details.contains("PYTHONPATH"))
        XCTAssertFalse(details.contains("api_hash"))
        await client.shutdown()
    }
}

final class MessagingShellTests: XCTestCase {
    @MainActor func testDefaultNavigationIsMessagingFirst() {
        XCTAssertEqual(AppModel().screen, .chats)
        XCTAssertEqual(Screen.messaging, [.chats, .contacts, .groupChats, .channels, .savedMessages])
        XCTAssertEqual(Screen.groupChats.rawValue, "Groups")
        XCTAssertEqual(Screen.groups.rawValue, "Group Management")
        XCTAssertEqual(Set(Screen.allCases.map(\.id)).count, Screen.allCases.count)
    }
    func testAllManagedToolsRemainAvailableInAdvancedWorkspace() {
        XCTAssertEqual(Set(Screen.advanced), Set([.dashboard, .groups, .permissions, .composer, .drafts, .destinations, .history, .activity, .messageOperations]))
        XCTAssertFalse(Screen.messaging.contains(.composer))
        XCTAssertFalse(Screen.messaging.contains(.destinations))
    }
    @MainActor func testConversationNavigationChangesCachedFiltersOnly() async {
        let model = AppModel()
        model.navigate(to: .groupChats)
        XCTAssertEqual(model.chatKind, "groups")
        model.navigate(to: .channels)
        XCTAssertEqual(model.chatKind, "channel")
        model.navigate(to: .chats)
        XCTAssertEqual(model.chatKind, "all")
        let request = await model.backend.latestRequest
        XCTAssertNil(request)
    }
    @MainActor func testNewMessagePreservesManagedAndPersonalDrafts() {
        let model = AppModel(); model.draft = "approved group draft"; model.chatDraft = "personal draft"
        model.screen = .composer
        model.composePersonalMessage()
        XCTAssertEqual(model.screen, .chats)
        XCTAssertEqual(model.draft, "approved group draft")
        XCTAssertEqual(model.chatDraft, "personal draft")
        XCTAssertTrue(model.composerFocusRequested)
        XCTAssertNil(model.preview)
        XCTAssertNil(model.chatPreview)
    }
    @MainActor func testChannelSelectionAndRefreshNeverRequestContent() async {
        let model = AppModel(); model.backendOnline = true
        model.status = .object(["connected": .bool(true), "bound_account_id": .integer(42)])
        model.selectChat(ChatSummary(data: .object(["id": .integer(-1001), "name": .string("Channel"), "kind": .string("channel")])))
        await model.loadMessages()
        XCTAssertEqual(model.selectedChat?.kind, "channel")
        XCTAssertTrue(model.chatMessages.isEmpty)
        XCTAssertFalse(model.chatCanPreview)
        XCTAssertFalse(model.chatCanSend)
        let request = await model.backend.latestRequest
        XCTAssertNil(request)
    }
}
