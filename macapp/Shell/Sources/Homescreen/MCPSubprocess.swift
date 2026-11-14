import Darwin
import Foundation

/// Owns one child's lifetime. Cancellation before launch is latched and cancellation
/// during I/O wakes poll. Only the worker closes descriptors and reaps the child.
final class MCPChildCancellation: @unchecked Sendable {
    private let lock = NSLock()
    private var cancelled = false
    private var process: Process?
    private let wake = Pipe()
    var descriptor: Int32 { wake.fileHandleForReading.fileDescriptor }

    func launch(_ child: Process) throws {
        lock.lock()
        defer { lock.unlock() }
        if cancelled { throw MCPClientOperationCode.cancelled }
        do { try child.run() } catch { throw MCPClientOperationCode.launchFailed }
        process = child
    }

    func cancel() {
        lock.lock()
        defer { lock.unlock() }
        guard !cancelled else { return }
        cancelled = true
        if let child = process, child.isRunning { kill(child.processIdentifier, SIGKILL) }
        try? wake.fileHandleForWriting.write(contentsOf: Data([1]))
    }

    func reap(_ child: Process) {
        lock.lock()
        process = nil
        if child.isRunning { kill(child.processIdentifier, SIGKILL) }
        lock.unlock()
        child.waitUntilExit()
    }
}

struct MCPChildIO {
    let cancellation: MCPChildCancellation
    let input: FileHandle
    let output: FileHandle
    let deadline: TimeInterval
    var pending = Data()
    var received = 0
    static let limit = 8 * 1024 * 1024

    func wait(_ fd: Int32, events: Int16) throws {
        while true {
            let remaining = deadline - ProcessInfo.processInfo.systemUptime
            guard remaining > 0 else { throw MCPClientOperationCode.timedOut }
            var descriptors = [pollfd(fd: fd, events: events, revents: 0),
                               pollfd(fd: cancellation.descriptor, events: Int16(POLLIN), revents: 0)]
            let ready = poll(&descriptors, 2, Int32(min(remaining * 1000 + 1, Double(Int32.max))))
            if ready < 0 && errno == EINTR { continue }
            guard ready > 0 else { throw ready == 0 ? MCPClientOperationCode.timedOut : .invalidResponse }
            guard descriptors[1].revents == 0 else { throw MCPClientOperationCode.cancelled }
            return
        }
    }

    func send(_ object: [String: Any]) throws {
        var bytes = try JSONSerialization.data(withJSONObject: object)
        bytes.append(10)
        guard bytes.count <= Self.limit else { throw MCPClientOperationCode.invalidResponse }
        let fd = input.fileDescriptor
        try bytes.withUnsafeBytes { buffer in
            var offset = 0
            while offset < buffer.count {
                try wait(fd, events: Int16(POLLOUT))
                let count = write(fd, buffer.baseAddress!.advanced(by: offset), buffer.count - offset)
                if count < 0 && (errno == EINTR || errno == EAGAIN) { continue }
                guard count > 0 else { throw MCPClientOperationCode.invalidResponse }
                offset += count
            }
        }
    }

    mutating func receive(_ id: Int, mcp: Bool) throws -> [String: Any] {
        while true {
            if let newline = pending.firstIndex(of: 10) {
                let line = pending.prefix(upTo: newline)
                pending.removeSubrange(...newline)
                guard let message = try JSONSerialization.jsonObject(with: line) as? [String: Any],
                      !mcp || message["jsonrpc"] as? String == "2.0" else { throw MCPClientOperationCode.invalidResponse }
                if message["id"] == nil, message["method"] is String { continue }
                guard let number = message["id"] as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
                      number == NSNumber(value: id), message["method"] == nil else {
                    throw MCPClientOperationCode.invalidResponse
                }
                if let failure = message["error"] {
                    guard !mcp, let error = failure as? [String: Any], message["result"] == nil else {
                        throw MCPClientOperationCode.invalidResponse
                    }
                    if error["code"] as? Int == -32601 { throw MCPClientOperationCode.unsupportedClient }
                    if error["message"] as? String == "Configuration was modified since last read. Fetch latest version and retry." {
                        throw MCPClientOperationCode.versionConflict
                    }
                    throw MCPClientOperationCode.commandFailed
                }
                guard let result = message["result"] as? [String: Any] else { throw MCPClientOperationCode.invalidResponse }
                return result
            }
            try wait(output.fileDescriptor, events: Int16(POLLIN))
            var bytes = [UInt8](repeating: 0, count: 65536)
            let count = read(output.fileDescriptor, &bytes, bytes.count)
            if count < 0 && errno == EINTR { continue }
            guard count > 0, received + count <= Self.limit else { throw MCPClientOperationCode.invalidResponse }
            received += count
            pending.append(contentsOf: bytes.prefix(count))
        }
    }
}

enum MCPSubprocess {
    static func work<T>(_ operation: @escaping (MCPChildCancellation) throws -> T) async throws -> T {
        let token = MCPChildCancellation()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                DispatchQueue.global(qos: .userInitiated).async {
                    continuation.resume(with: Result { try operation(token) })
                }
            }
        } onCancel: { token.cancel() }
    }

    static func session<T>(_ path: String, _ arguments: [String], _ environment: [String: String], _ timeout: TimeInterval,
                           _ body: @escaping (inout MCPChildIO) throws -> T) async throws -> T {
        try await work { token in
            let process = Process()
            let input = Pipe(), output = Pipe()
            process.executableURL = URL(fileURLWithPath: path)
            process.environment = environment
            process.arguments = arguments
            process.standardInput = input
            process.standardOutput = output
            process.standardError = FileHandle.nullDevice
            try token.launch(process)
            defer { token.reap(process) }
            try? input.fileHandleForReading.close()
            try? output.fileHandleForWriting.close()
            let fd = input.fileHandleForWriting.fileDescriptor
            _ = fcntl(fd, F_SETNOSIGPIPE, 1)
            _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK)
            var io = MCPChildIO(cancellation: token, input: input.fileHandleForWriting,
                                output: output.fileHandleForReading, deadline: ProcessInfo.processInfo.systemUptime + timeout)
            return try body(&io)
        }
    }
}

enum MCPProcessRunner {
    static func run(executablePath: String, arguments: [String], environment: [String: String], timeout: TimeInterval) async -> MCPCommandResult {
        do {
            return try await MCPSubprocess.work { token in
                let process = Process()
                let stdout = Pipe(), stderr = Pipe()
                process.executableURL = URL(fileURLWithPath: executablePath)
                process.arguments = arguments
                process.environment = environment
                process.standardInput = FileHandle.nullDevice
                process.standardOutput = stdout
                process.standardError = stderr
                let ended = Pipe()
                process.terminationHandler = { _ in try? ended.fileHandleForWriting.write(contentsOf: Data([1])) }
                try token.launch(process)
                defer { token.reap(process) }
                try? stdout.fileHandleForWriting.close()
                try? stderr.fileHandleForWriting.close()
                var descriptors = [stdout.fileHandleForReading, stderr.fileHandleForReading, ended.fileHandleForReading].map { pollfd(fd: $0.fileDescriptor, events: Int16(POLLIN), revents: 0) }
                descriptors.append(pollfd(fd: token.descriptor, events: Int16(POLLIN), revents: 0))
                var output = [Data(), Data()]
                let deadline = ProcessInfo.processInfo.systemUptime + timeout
                while descriptors.prefix(3).contains(where: { $0.fd >= 0 }) {
                    let left = deadline - ProcessInfo.processInfo.systemUptime
                    guard left > 0 else { throw MCPClientOperationCode.timedOut }
                    let ready = poll(&descriptors, 4, Int32(min(left * 1000 + 1, Double(Int32.max))))
                    if ready < 0 && errno == EINTR { continue }
                    guard ready > 0 else { throw ready == 0 ? MCPClientOperationCode.timedOut : .commandFailed }
                    if descriptors[3].revents != 0 { throw MCPClientOperationCode.cancelled }
                    if descriptors[2].revents != 0 { descriptors[2].fd = -1 }
                    for i in 0..<2 where descriptors[i].revents != 0 {
                        var bytes = [UInt8](repeating: 0, count: 65536)
                        let count = read(descriptors[i].fd, &bytes, bytes.count)
                        if count < 0 && errno == EINTR { continue }
                        guard count >= 0, output[i].count + count <= MCPChildIO.limit else { throw MCPClientOperationCode.invalidResponse }
                        if count == 0 { descriptors[i].fd = -1 }
                        else { output[i].append(contentsOf: bytes.prefix(count)) }
                    }
                }
                return MCPCommandResult(exitStatus: process.terminationStatus, stdout: String(decoding: output[0], as: UTF8.self),
                                        stderr: String(decoding: output[1], as: UTF8.self))
            }
        } catch { return MCPCommandResult(exitStatus: -1, failure: error as? MCPClientOperationCode ?? .commandFailed) }
    }
}
