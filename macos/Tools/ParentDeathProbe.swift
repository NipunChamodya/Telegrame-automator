// Standalone lifecycle control: compile with ProtocolModels.swift + BackendClient.swift.
// Arguments: fixture Python executable, fixture source directory. Never use a live backend.
import Foundation
import Darwin
@main struct ParentDeathProbe {
    static func main() async throws {
        guard CommandLine.arguments.count == 3 else { exit(2) }
        let client = BackendClient(runtime: (URL(fileURLWithPath: CommandLine.arguments[1]), URL(fileURLWithPath: CommandLine.arguments[2])))
        try await client.start()
        _ = try await client.request("health")
        // Simulate abrupt GUI death without a Swift shutdown/deinitializer.
        Darwin._exit(0)
    }
}
