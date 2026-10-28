import Foundation

actor Events {
    var count = 0
    func add() { count += 1 }
}

@main struct TransportSmoke {
    static func require(_ value: Bool, _ message: String) throws {
        if !value { throw BackendFailure(code: "test_failure", message: message) }
    }
    static func main() async throws {
        guard CommandLine.arguments.count == 3 else {
            print("Usage: TransportSmoke /path/to/python /path/to/fixture-src")
            return
        }
        let runtime = (URL(fileURLWithPath: CommandLine.arguments[1]), URL(fileURLWithPath: CommandLine.arguments[2]))
        let client = BackendClient(runtime: runtime)
        let events = Events()
        await client.setEventHandler { _ in Task { await events.add() } }
        let unicode = "ශ්‍රී ලංකා தமிழ் 👩🏽‍💻 🇱🇰"
        let echo = try await client.request("echo", params: ["text": .string(unicode)], timeout: 3)
        try require(echo["text"].string == unicode, "Unicode echo")
        try await withThrowingTaskGroup(of: Int.self) { group in
            for i in 0..<12 {
                group.addTask {
                    let response = try await client.request("echo", params: ["index": .integer(i)], timeout: 3)
                    return response["index"].int
                }
            }
            var seen = Set<Int>()
            for try await value in group { seen.insert(value) }
            try require(seen.count == 12, "Concurrent request correlation")
        }
        _ = try await client.request("progress", timeout: 3)
        try await Task.sleep(nanoseconds: 30_000_000)
        let eventCount = await events.count
        try require(eventCount > 0, "Progress events")
        do {
            _ = try await client.request("wait", timeout: 0.1)
            throw BackendFailure(code: "test_failure", message: "Missing timeout")
        } catch let failure as BackendFailure {
            try require(failure.code == "timeout", "Typed timeout")
        }
        let waiting = Task { try await client.request("wait", timeout: 3) }
        try await Task.sleep(nanoseconds: 30_000_000)
        waiting.cancel()
        do {
            _ = try await waiting.value
            throw BackendFailure(code: "test_failure", message: "Missing cancellation")
        } catch is CancellationError { }
        await client.shutdown()
        let broken = BackendClient(runtime: runtime)
        do {
            _ = try await broken.request("malformed", timeout: 3)
            throw BackendFailure(code: "test_failure", message: "Malformed frame accepted")
        } catch let failure as BackendFailure {
            try require(["protocol_error", "backend_unavailable"].contains(failure.code), "Malformed frame failure")
        }
        await broken.shutdown()
        let inputClosed = BackendClient(runtime: runtime)
        _ = try await inputClosed.request("close_input", timeout: 3)
        try await Task.sleep(nanoseconds: 30_000_000)
        do {
            _ = try await inputClosed.request("echo", timeout: 2)
            throw BackendFailure(code: "test_failure", message: "Closed input accepted write")
        } catch let failure as BackendFailure {
            try require(failure.code == "backend_unavailable", "Closed input is a typed failure, not SIGPIPE termination")
        }
        await inputClosed.shutdown()
        let eof = BackendClient(runtime: runtime)
        do {
            _ = try await eof.request("close_output", timeout: 3)
            throw BackendFailure(code: "test_failure", message: "Missing EOF failure")
        } catch let failure as BackendFailure {
            try require(failure.code == "backend_unavailable", "Output EOF detection")
        }
        await eof.shutdown()
        print("Transport smoke passed: Unicode, 12 concurrent requests, progress, timeout, cancellation, malformed frame, closed-input/SIGPIPE, EOF, shutdown.")
    }
}
