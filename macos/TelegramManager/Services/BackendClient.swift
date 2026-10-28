import Foundation
import Darwin

actor BackendClient {
    typealias EventHandler = @Sendable (JSONValue) -> Void
    private let runtimeOverride: (URL, URL)?
    init(runtime: (URL, URL)? = nil) { runtimeOverride = runtime }
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var errorOutput: FileHandle?
    private var buffer = Data()
    private var pending: [String: CheckedContinuation<JSONValue, Error>] = [:]
    private var timeouts: [String: Task<Void, Never>] = [:]
    private var events: EventHandler?
    private(set) var latestRequest: String?
    private var stderrBytes = 0
    private var generation = UUID()
    private var startupFailure: BackendFailure?
    private var readTask: Task<Void, Never>?
    private var readContinuation: AsyncStream<Data>.Continuation?

    func setEventHandler(_ handler: @escaping EventHandler) { events = handler }

    static func runtimeLocation() throws -> (URL, URL) {
        let fm = FileManager.default
        // A relocatable runtime may be supplied by a future signed distribution build.
        if let resources = Bundle.main.resourceURL {
            let runtime = resources.appendingPathComponent("Python/bin/python3")
            let source = resources.appendingPathComponent("Backend/src")
            if fm.isExecutableFile(atPath: runtime.path), fm.fileExists(atPath: source.path) { return (runtime, source) }
        }
        let configuration = Bundle.main.object(forInfoDictionaryKey: "TGMDevelopmentRoot") as? String
        let root = ProcessInfo.processInfo.environment["TGM_PROJECT_ROOT"] ?? configuration ?? ""
        guard !root.isEmpty, root.hasPrefix("/") else { throw BackendFailure(code: "runtime_missing", message: "The development Python runtime was not found. Build from the project checkout or configure TGM_PROJECT_ROOT.") }
        let directory = URL(fileURLWithPath: root, isDirectory: true)
        let python = directory.appendingPathComponent(".venv/bin/python")
        guard fm.isExecutableFile(atPath: python.path) else { throw BackendFailure(code: "runtime_missing", message: "Project .venv is missing. Run python3 main.py once to complete guided dependency setup, then reopen the app.") }
        let bundled = Bundle.main.resourceURL?.appendingPathComponent("Backend/src")
        return (python, bundled != nil && fm.fileExists(atPath: bundled!.path) ? bundled! : directory.appendingPathComponent("src"))
    }

    func start() throws {
        if process?.isRunning == true { return }
        if process != nil { failAll(BackendFailure.disconnected); cleanup() }
        signal(SIGPIPE, SIG_IGN)
        generation = UUID()
        startupFailure = nil
        let token = generation
        let (python, source) = try runtimeOverride ?? Self.runtimeLocation()
        let task = Process(), stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
        task.executableURL = python
        task.arguments = ["-u", "-m", "telegram_manager.ipc"]
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = source.path
        environment["PYTHONUNBUFFERED"] = "1"
        task.environment = environment
        task.currentDirectoryURL = source.deletingLastPathComponent()
        task.standardInput = stdin; task.standardOutput = stdout; task.standardError = stderr
        input = stdin.fileHandleForWriting; output = stdout.fileHandleForReading; errorOutput = stderr.fileHandleForReading
        buffer.removeAll(keepingCapacity: true); stderrBytes = 0
        let stream = AsyncStream<Data>(bufferingPolicy: .bufferingOldest(64)) { continuation in
            readContinuation = continuation
        }
        let continuation = readContinuation!
        readTask = Task { [weak self] in
            for await data in stream { await self?.receive(data, generation: token) }
        }
        stdout.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil }
            let result = continuation.yield(data)
            if data.isEmpty { continuation.finish() }
            if case .dropped = result { Task { await self?.overflow(generation: token) } }
        }
        stderr.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil }
            Task { await self?.recordDiagnostics(data.count, generation: token) }
        }
        task.terminationHandler = { [weak self] _ in Task { await self?.terminated(generation: token) } }
        do { try task.run(); process = task }
        catch { cleanup(); throw BackendFailure(code: "launch_failed", message: "Could not launch the project Python backend. Verify its runtime and file permissions.") }
    }

    private func recordDiagnostics(_ count: Int, generation token: UUID) { guard token == generation else { return }; stderrBytes = min(stderrBytes + count, 1_000_000) }
    private func overflow(generation token: UUID) { guard token == generation else { return }; terminateMalformed() }

    func request(_ method: String, params: [String: JSONValue] = [:], timeout: TimeInterval = 120) async throws -> JSONValue {
        try Task.checkCancellation()
        try start()
        let id = UUID().uuidString
        latestRequest = id
        let request = JSONValue.object(["id": .string(id), "method": .string(method), "params": .object(params)])
        var data = try JSONEncoder().encode(request); data.append(10)
        guard data.count <= 1_048_576, let input else { throw BackendFailure.disconnected }
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                pending[id] = continuation
                timeouts[id] = Task { [weak self] in
                    do { try await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000)) }
                    catch { return }
                    await self?.expire(id)
                }
                do { try input.write(contentsOf: data) }
                catch { failAll(BackendFailure.disconnected); process?.terminate() }
            }
        } onCancel: { [weak self] in Task { await self?.cancel(id) } }
    }

    private func receive(_ data: Data, generation token: UUID) {
        guard token == generation else { return }
        if data.isEmpty {
            failAll(BackendFailure.disconnected)
            process?.terminate()
            return
        }
        buffer.append(data)
        guard buffer.count <= 2_097_152 else { terminateMalformed(); return }
        while let end = buffer.firstIndex(of: 10) {
            let line = buffer.prefix(upTo: end)
            buffer.removeSubrange(...end)
            guard !line.isEmpty else { continue }
            guard let message = try? JSONDecoder().decode(JSONValue.self, from: Data(line)) else { terminateMalformed(); return }
            guard case .object = message else { terminateMalformed(); return }
            if !message["event"].string.isEmpty { events?(message); continue }
            if message["id"] == .null && !message["ok"].bool && !message["error"]["code"].string.isEmpty {
                let failure = BackendFailure(code: message["error"]["code"].string, message: safeDisplay(message["error"]["message"].string))
                startupFailure = failure
                failAll(failure)
                continue
            }
            guard case .string = message["id"], case .bool = message["ok"] else { terminateMalformed(); return }
            let id = message["id"].string
            guard let continuation = pending.removeValue(forKey: id) else { continue }
            timeouts.removeValue(forKey: id)?.cancel()
            if message["ok"].bool { continuation.resume(returning: message["result"]) }
            else { continuation.resume(throwing: BackendFailure(code: message["error"]["code"].string, message: safeDisplay(message["error"]["message"].string))) }
        }
    }

    private func terminateMalformed() {
        process?.terminate()
        failAll(BackendFailure(code: "protocol_error", message: "The backend returned invalid protocol data. Restart it before continuing; uncertain deliveries must be checked in history."))
    }
    private func fail(_ id: String, _ error: Error) {
        timeouts.removeValue(forKey: id)?.cancel()
        pending.removeValue(forKey: id)?.resume(throwing: error)
    }
    private func failAll(_ error: Error) {
        let waiting = pending; pending.removeAll()
        for task in timeouts.values { task.cancel() }; timeouts.removeAll()
        for continuation in waiting.values { continuation.resume(throwing: error) }
    }
    private func expire(_ id: String) {
        fail(id, BackendFailure(code: "timeout", message: "The operation timed out. No retry was attempted. Check delivery history before another send."))
        sendCancel(id)
    }
    func cancelCurrent() { if let id = latestRequest { cancel(id) } }
    private func cancel(_ id: String) {
        sendCancel(id)
        fail(id, CancellationError())
    }
    private func sendCancel(_ id: String) {
        guard let input, let data = try? JSONEncoder().encode(JSONValue.object([
            "id": .string(UUID().uuidString), "method": .string("cancel"), "params": .object(["request_id": .string(id)])])) else { return }
        try? input.write(contentsOf: data + Data([10]))
    }
    private func terminated(generation token: UUID) {
        guard token == generation else { return }
        let failure = startupFailure ?? BackendFailure.disconnected
        failAll(failure)
        cleanup(); process = nil
        events?(.object(["event": .string("backend_stopped"), "data": .object(["error": .object(["code": .string(failure.code), "message": .string(failure.message)])])]))
    }
    private func cleanup() {
        readContinuation?.finish(); readContinuation = nil; readTask?.cancel(); readTask = nil
        output?.readabilityHandler = nil; errorOutput?.readabilityHandler = nil
        try? input?.close(); try? output?.close(); try? errorOutput?.close()
        input = nil; output = nil; errorOutput = nil
    }
    func shutdown() async {
        guard let task = process, task.isRunning else {
            failAll(BackendFailure.disconnected)
            cleanup(); process = nil
            return
        }
        _ = try? await request("shutdown", timeout: 2)
        try? input?.close()
        if task.isRunning {
            try? await Task.sleep(nanoseconds: 500_000_000)
            if task.isRunning { task.terminate() }
        }
        failAll(BackendFailure.disconnected); cleanup(); process = nil
    }
}
