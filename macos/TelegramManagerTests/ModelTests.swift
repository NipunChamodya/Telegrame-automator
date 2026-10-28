import XCTest
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
    private func fixture() throws -> (URL, BackendClient) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("tgm-swift-fixture-" + UUID().uuidString)
        let source = directory.appendingPathComponent("src")
        let package = source.appendingPathComponent("telegram_manager")
        try FileManager.default.createDirectory(at: package, withIntermediateDirectories: true)
        try Data().write(to: package.appendingPathComponent("__init__.py"))
        let script = #"""
import json,sys,time,pathlib
with open(pathlib.Path(__file__).with_name('starts'),'a') as marker: marker.write('x')
approved=[]
draft='saved draft'
records=[{'id':-1,'name':'ශ්‍රී ලංකා','kind':'group','permission':'unknown','effective_permission':'unknown'}, {'id':-2,'name':'Python Developers','kind':'supergroup','permission':'allowed','effective_permission':'allowed'}]
for line in sys.stdin:
    request=json.loads(line); method=request['method']
    if method=='crash': sys.exit(0)
    if method=='hang': continue
    if method=='bad': print('invalid frame',flush=True);continue
    if method=='progress':
        print(json.dumps({'event':'progress','request_id':request['id'],'data':{'phase':'basic','index':1}},ensure_ascii=False),flush=True)
    params=request['params']
    result={'method':method,'unicode':'ශ්‍රී தமிழ் 👩🏽‍💻','params':params}
    if method=='status': result={'connected':True,'account':{'id':13,'display_name':'Fixture account'},'bound_account_id':13,'cooldown_until':time.time()+16,'overview':{'total':2,'allowed':1,'unknown':1,'denied':0,'pending':1}}
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
        return (directory, BackendClient(runtime: (python, source)))
    }
    @MainActor func testCooldownFailureReloadsCommittedStatusWithoutRetry() async throws {
        let (directory, client) = try fixture()
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
        let (directory, client) = try fixture()
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
        let (directory, client) = try fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        do { _ = try await client.request("hang", timeout: 0.1); XCTFail("Expected timeout") }
        catch let error as BackendFailure { XCTAssertEqual(error.code, "timeout") }
        await client.shutdown()
    }
    func testUnexpectedShutdownAndMalformedResponse() async throws {
        for method in ["crash", "bad"] {
            let (directory, client) = try fixture()
            do { _ = try await client.request(method, timeout: 2); XCTFail("Expected failure") }
            catch let error as BackendFailure { XCTAssertTrue(["backend_unavailable", "protocol_error"].contains(error.code)) }
            await client.shutdown()
            try? FileManager.default.removeItem(at: directory)
        }
    }
    func testCancellationAndProgress() async throws {
        let (directory, client) = try fixture()
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
        let (directory, client) = try fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(backend: client)
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
        let (directory, client) = try fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(backend: client)
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
    func testShutdownDoesNotRestartTerminatedBackend() async throws {
        let (directory, client) = try fixture()
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
