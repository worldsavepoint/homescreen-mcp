import Foundation
import Darwin

enum MCPServiceCheckCode: String, Sendable {
    case passed, launchFailed, timedOut, protocolError, unexpectedServer, missingTools
}

struct MCPServiceCheckResult: Sendable {
    let code: MCPServiceCheckCode
    var tools: Set<String> = []
}

/// Checks protocol startup and discovery using one read-only temporary-data child.
struct MCPServiceCheck {
    var timeout: TimeInterval = 45
    var environment: [String: String] = ProcessInfo.processInfo.environment

    func run(executablePath: String) async -> MCPServiceCheckResult {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                continuation.resume(returning: runBlocking(executablePath: executablePath))
            }
        }
    }

    private func runBlocking(executablePath: String) -> MCPServiceCheckResult {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("homescreen-mcp-check-\(UUID().uuidString)")
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        } catch { return MCPServiceCheckResult(code: .launchFailed) }
        defer { try? FileManager.default.removeItem(at: directory) }
        var childEnvironment = environment
        childEnvironment["HOMESCREEN_DATA"] = directory.path
        childEnvironment["HOMESCREEN_READ_ONLY"] = "1"
        childEnvironment.removeValue(forKey: "HOMESCREEN_ALLOW_APPLY")
        let process = Process()
        let input = Pipe()
        let output = Pipe()
        let finished = DispatchSemaphore(value: 0)
        process.executableURL = URL(fileURLWithPath: executablePath)
        process.arguments = ["mcp"]
        process.environment = childEnvironment
        process.standardInput = input
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        process.terminationHandler = { _ in finished.signal() }
        do { try process.run() }
        catch { return MCPServiceCheckResult(code: .launchFailed) }
        try? input.fileHandleForReading.close()
        try? output.fileHandleForWriting.close()
        _ = fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        defer {
            MCPSubprocess.stop(process, finished: finished)
            try? input.fileHandleForWriting.close()
            try? output.fileHandleForReading.close()
        }
        let deadline = ProcessInfo.processInfo.systemUptime + max(0.01, timeout)
        var pending = Data()

        func send(_ message: [String: Any]) throws {
            var data = try JSONSerialization.data(withJSONObject: ["jsonrpc": "2.0"].merging(message) { _, value in value })
            data.append(0x0a)
            try input.fileHandleForWriting.write(contentsOf: data)
        }

        func receive(_ id: Int) throws -> [String: Any] {
            while true {
                while let newline = pending.firstIndex(of: 0x0a) {
                    let line = pending.prefix(upTo: newline)
                    pending.removeSubrange(...newline)
                    guard let message = try JSONSerialization.jsonObject(with: line) as? [String: Any],
                          message["jsonrpc"] as? String == "2.0" else { throw CheckError.protocolError }
                    guard message["id"] as? Int == id else { continue }
                    guard message["error"] == nil, let result = message["result"] as? [String: Any] else { throw CheckError.protocolError }
                    return result
                }
                let remaining = deadline - ProcessInfo.processInfo.systemUptime
                guard remaining > 0 else { throw CheckError.timedOut }
                var descriptor = pollfd(fd: output.fileHandleForReading.fileDescriptor, events: Int16(POLLIN), revents: 0)
                let ready = poll(&descriptor, 1, Int32(min(remaining * 1000 + 1, Double(Int32.max))))
                if ready < 0 && errno == EINTR { continue }
                guard ready > 0 else { throw ready == 0 ? CheckError.timedOut : CheckError.protocolError }
                var bytes = [UInt8](repeating: 0, count: 65536)
                let count = read(descriptor.fd, &bytes, bytes.count)
                guard count > 0 else { throw CheckError.protocolError }
                pending.append(contentsOf: bytes.prefix(count))
                guard pending.count <= 4 * 1024 * 1024 else { throw CheckError.protocolError }
            }
        }

        do {
            try send(["id": 1, "method": "initialize", "params": ["protocolVersion": "2025-11-25",
                "capabilities": [:], "clientInfo": ["name": "home-screen-organizer-startup-check", "version": "1.0.0"]]])
            let initialization = try receive(1)
            guard initialization["protocolVersion"] is String, initialization["capabilities"] is [String: Any],
                  let info = initialization["serverInfo"] as? [String: Any] else { throw CheckError.protocolError }
            guard info["name"] as? String == MCPClientRegistration.serverID else { return MCPServiceCheckResult(code: .unexpectedServer) }
            try send(["method": "notifications/initialized"])
            try send(["id": 2, "method": "tools/list", "params": [:]])
            let result = try receive(2)
            guard let entries = result["tools"] as? [[String: Any]], entries.allSatisfy({ $0["name"] is String }) else { throw CheckError.protocolError }
            let tools = Set(entries.compactMap { $0["name"] as? String })
            let required: Set<String> = ["read_phone", "show_layout", "move", "diff"]
            return MCPServiceCheckResult(code: required.isSubset(of: tools) ? .passed : .missingTools, tools: tools)
        } catch CheckError.timedOut { return MCPServiceCheckResult(code: .timedOut) }
        catch { return MCPServiceCheckResult(code: .protocolError) }
    }

    private enum CheckError: Error { case timedOut, protocolError }
}
