import Foundation
import Darwin

enum MCPClient: String, CaseIterable, Sendable {
    case codex, claudeCode

    var executableName: String { self == .codex ? "codex" : "claude" }
}

enum MCPAccessMode: String, Sendable {
    case readOnly, applyEnabled
}

enum MCPClientRegistration {
    static let serverID = "ios-homescreen-mcp"

    static func arguments(client: MCPClient, executablePath: String) -> [String] {
        arguments(client: client, executablePath: executablePath, mode: .readOnly)
    }

    static func arguments(client: MCPClient, executablePath: String, mode: MCPAccessMode) -> [String] {
        var arguments = ["mcp", "add"]
        if client == .codex { arguments += [serverID] }
        else { arguments += ["--scope", "user"] }
        arguments += ["--env", "HOMESCREEN_READ_ONLY=\(mode == .readOnly ? "1" : "0")"]
        if mode == .applyEnabled { arguments += ["--env", "HOMESCREEN_ALLOW_APPLY=1"] }
        // Claude's --env is variadic; the transport option ends that argument group.
        if client == .claudeCode { arguments += ["--transport", "stdio", serverID] }
        return arguments + ["--", executablePath, "mcp"]
    }
}

enum MCPClientAvailability: String, Sendable { case available, notFound, notExecutable }
enum MCPConfigurationState: String, Sendable { case configured, notConfigured, unknown }
enum MCPConnectionState: String, Sendable { case connected, disconnected, unknown }
enum MCPClientScope: String, Sendable { case user, other, unknown }
enum MCPClientOperationCode: String, Sendable {
    case success, notFound, notExecutable, launchFailed, timedOut, commandFailed, invalidResponse
    case snapshotReadFailed, recoveryFailed
}
enum MCPRegistrationRecovery: String, Sendable { case notNeeded, restored, failed }

struct MCPClientDetection: Sendable {
    let client: MCPClient
    let availability: MCPClientAvailability
    let executablePath: String?
}

struct MCPClientQuery: Sendable {
    let client: MCPClient
    let code: MCPClientOperationCode
    let configuration: MCPConfigurationState
    let connection: MCPConnectionState
    var mode: MCPAccessMode? = nil
    var scope: MCPClientScope = .unknown
}

struct MCPClientRegistrationResult: Sendable {
    let client: MCPClient
    let mode: MCPAccessMode
    let code: MCPClientOperationCode
    let query: MCPClientQuery?
    var recovery: MCPRegistrationRecovery = .notNeeded
}

struct MCPCommandResult: Sendable {
    let exitStatus: Int32
    var stdout: String = ""
    var stderr: String = ""
    var failure: MCPClientOperationCode? = nil
}

typealias MCPCommandRunner = (String, [String], [String: String], TimeInterval) async -> MCPCommandResult
typealias MCPUserEntrySnapshotProvider = ([String: String], URL) throws -> String?

/// Locates executables without invoking a login shell or evaluating paths as code.
struct MCPExecutableLocator {
    let environment: [String: String]
    let homeDirectory: URL
    var systemDirectories = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    var applicationDirectories: [String]? = nil

    func locate(_ client: MCPClient) -> String? {
        let home = homeDirectory.path
        let inherited = (environment["PATH"] ?? "").split(separator: ":").map(String.init)
        var directories = inherited + ["\(home)/.local/bin", "\(home)/.npm-global/bin",
            "\(home)/.npm/bin", "\(home)/.bun/bin", "\(home)/.volta/bin", "\(home)/bin"] + systemDirectories
        let nvm = homeDirectory.appendingPathComponent(".nvm/versions/node")
        if let versions = try? FileManager.default.contentsOfDirectory(atPath: nvm.path) {
            directories += versions.sorted().reversed().map { nvm.appendingPathComponent($0).appendingPathComponent("bin").path }
        }
        var candidates = directories.map { URL(fileURLWithPath: $0).appendingPathComponent(client.executableName).path }
        if client == .codex {
            for root in applicationDirectories ?? ["\(home)/Applications", "/Applications"] {
                candidates += ["\(root)/Codex.app/Contents/Resources/codex",
                    "\(root)/Codex.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
                    "\(root)/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"]
            }
        }
        return candidates.first(where: Self.isExecutable)
    }

    static func isExecutable(_ path: String) -> Bool {
        var isDirectory: ObjCBool = false
        return FileManager.default.fileExists(atPath: path, isDirectory: &isDirectory) &&
            !isDirectory.boolValue && FileManager.default.isExecutableFile(atPath: path)
    }
}

struct MCPClientManager {
    private let environment: [String: String]
    private let homeDirectory: URL
    private let timeout: TimeInterval
    private let executableLocator: (MCPClient) -> String?
    private let runner: MCPCommandRunner
    private let snapshotProvider: MCPUserEntrySnapshotProvider

    init(environment: [String: String] = ProcessInfo.processInfo.environment,
         homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser,
         timeout: TimeInterval = 15,
         executableLocator: ((MCPClient) -> String?)? = nil,
         runner: @escaping MCPCommandRunner = MCPProcessRunner.run,
         snapshotProvider: @escaping MCPUserEntrySnapshotProvider = MCPClientManager.claudeUserEntry) {
        self.environment = environment
        self.homeDirectory = homeDirectory
        self.timeout = max(0.01, timeout)
        self.executableLocator = executableLocator ?? MCPExecutableLocator(environment: environment, homeDirectory: homeDirectory).locate
        self.runner = runner
        self.snapshotProvider = snapshotProvider
    }

    func detect(client: MCPClient, executablePath: String? = nil) async -> MCPClientDetection {
        let path = executablePath ?? executableLocator(client)
        return MCPClientDetection(client: client, availability: path.map {
            MCPExecutableLocator.isExecutable($0) ? .available : .notExecutable
        } ?? .notFound, executablePath: path)
    }

    func query(client: MCPClient, executablePath: String? = nil) async -> MCPClientQuery {
        let detection = await detect(client: client, executablePath: executablePath)
        guard detection.availability == .available, let path = detection.executablePath else {
            return queryFailure(client, detection.availability == .notFound ? .notFound : .notExecutable)
        }
        let arguments = ["mcp", "get", MCPClientRegistration.serverID] + (client == .codex ? ["--json"] : [])
        let result = await runner(path, arguments, environment, timeout)
        if let failure = result.failure { return queryFailure(client, failure) }
        if result.exitStatus != 0 {
            let text = (result.stdout + result.stderr).lowercased()
            let absent = text.contains("no mcp server found") || text.contains("no mcp server named") ||
                text.contains("no server named") || text.contains("not found with name")
            return MCPClientQuery(client: client, code: absent ? .success : .commandFailed,
                configuration: absent ? .notConfigured : .unknown, connection: .unknown)
        }
        if client == .codex {
            guard let data = result.stdout.data(using: .utf8),
                  let entry = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
                  entry["name"] as? String == MCPClientRegistration.serverID,
                  let transport = entry["transport"] as? [String: Any], transport["command"] is String else {
                return queryFailure(client, .invalidResponse)
            }
            let env = transport["env"] as? [String: String] ?? [:]
            return MCPClientQuery(client: client, code: .success, configuration: .configured,
                connection: .unknown, mode: accessMode(env), scope: .user)
        }
        let lines = result.stdout.components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespaces) }
        guard lines.contains("\(MCPClientRegistration.serverID):"), lines.contains(where: { $0.hasPrefix("Command:") || $0.hasPrefix("URL:") }) else {
            return queryFailure(client, .invalidResponse)
        }
        let status = lines.first(where: { $0.hasPrefix("Status:") })?.dropFirst("Status:".count)
            .trimmingCharacters(in: .whitespaces).lowercased() ?? ""
        let connection: MCPConnectionState = status.contains("failed") || status.contains("disconnected") ||
            status.contains("not connected") || status.contains("needs authentication") ? .disconnected :
            (["connected", "✓ connected"].contains(status) ? .connected : .unknown)
        let scope = lines.first(where: { $0.hasPrefix("Scope:") })?.lowercased() ?? ""
        let env = Dictionary(lines.compactMap { line -> (String, String)? in
            let pair = line.split(separator: "=", maxSplits: 1).map(String.init)
            return pair.count == 2 && pair[0].hasPrefix("HOMESCREEN_") ? (pair[0], pair[1]) : nil
        }, uniquingKeysWith: { _, last in last })
        return MCPClientQuery(client: client, code: .success, configuration: .configured, connection: connection,
            mode: accessMode(env), scope: scope.contains("user") ? .user : (scope.isEmpty ? .unknown : .other))
    }

    func register(client: MCPClient, executablePath: String? = nil, enginePath: String,
                  mode: MCPAccessMode = .readOnly) async -> MCPClientRegistrationResult {
        let detection = await detect(client: client, executablePath: executablePath)
        guard detection.availability == .available, let path = detection.executablePath else {
            return MCPClientRegistrationResult(client: client, mode: mode,
                code: detection.availability == .notFound ? .notFound : .notExecutable, query: nil)
        }
        var snapshot: String?
        if client == .claudeCode {
            let previous = await query(client: client, executablePath: path)
            guard previous.code == .success else {
                return MCPClientRegistrationResult(client: client, mode: mode, code: previous.code, query: previous)
            }
            do { snapshot = try readUserEntrySnapshot() }
            catch { return MCPClientRegistrationResult(client: client, mode: mode, code: .snapshotReadFailed, query: previous) }
            if previous.configuration == .configured && previous.scope == .user && snapshot == nil {
                return MCPClientRegistrationResult(client: client, mode: mode, code: .snapshotReadFailed, query: previous)
            }
            if let snapshot {
                let removal = await runner(path, ["mcp", "remove", "--scope", "user", MCPClientRegistration.serverID], environment, timeout)
                if let failure = operationFailure(removal) {
                    let recovery = await restoreUserEntry(snapshot, path: path)
                    return MCPClientRegistrationResult(client: client, mode: mode, code: recovery == .failed ? .recoveryFailed : failure,
                        query: await query(client: client, executablePath: path), recovery: recovery)
                }
            }
        }
        let result = await runner(path, MCPClientRegistration.arguments(client: client, executablePath: enginePath, mode: mode), environment, timeout)
        if let failure = operationFailure(result) {
            var recovery: MCPRegistrationRecovery = .notNeeded
            if let snapshot {
                recovery = await restoreUserEntry(snapshot, path: path)
            }
            return MCPClientRegistrationResult(client: client, mode: mode,
                code: recovery == .failed ? .recoveryFailed : failure,
                query: await query(client: client, executablePath: path), recovery: recovery)
        }
        let verification = await query(client: client, executablePath: path)
        var failure: MCPClientOperationCode? = verification.code == .success ?
            (verification.configuration == .configured ? nil : .invalidResponse) : verification.code
        if failure == nil && client == .claudeCode {
            do {
                if try !userEntryMatches(enginePath: enginePath, mode: mode) { failure = .invalidResponse }
            } catch { failure = .snapshotReadFailed }
        }
        if let failure {
            var recovery: MCPRegistrationRecovery = .notNeeded
            if let snapshot { recovery = await restoreUserEntry(snapshot, path: path) }
            return MCPClientRegistrationResult(client: client, mode: mode,
                code: recovery == .failed ? .recoveryFailed : failure,
                query: await query(client: client, executablePath: path), recovery: recovery)
        }
        return MCPClientRegistrationResult(client: client, mode: mode,
            code: .success, query: verification)
    }

    /// Reads only the user-scoped project entry; CLI commands perform all mutations.
    static func claudeUserEntry(environment: [String: String], homeDirectory: URL) throws -> String? {
        let override = environment["CLAUDE_CONFIG_DIR"].flatMap { $0.isEmpty ? nil : URL(fileURLWithPath: $0) }
        let legacy = (override ?? homeDirectory.appendingPathComponent(".claude")).appendingPathComponent(".config.json")
        let filename = environment["CLAUDE_CODE_CUSTOM_OAUTH_URL"].map { $0.isEmpty ? ".claude.json" : ".claude-custom-oauth.json" } ?? ".claude.json"
        let url = FileManager.default.fileExists(atPath: legacy.path) ? legacy : (override ?? homeDirectory).appendingPathComponent(filename)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        let root = try JSONSerialization.jsonObject(with: Data(contentsOf: url))
        guard let dictionary = root as? [String: Any] else { throw CocoaError(.fileReadCorruptFile) }
        guard let value = (dictionary["mcpServers"] as? [String: Any])?[MCPClientRegistration.serverID] else { return nil }
        guard let entry = value as? [String: Any], JSONSerialization.isValidJSONObject(entry) else { throw CocoaError(.fileReadCorruptFile) }
        return String(decoding: try JSONSerialization.data(withJSONObject: entry, options: [.sortedKeys, .withoutEscapingSlashes]), as: UTF8.self)
    }

    private func readUserEntrySnapshot() throws -> String? {
        guard let snapshot = try snapshotProvider(environment, homeDirectory) else { return nil }
        guard let data = snapshot.data(using: .utf8),
              let entry = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw CocoaError(.fileReadCorruptFile) }
        return String(decoding: try JSONSerialization.data(withJSONObject: entry, options: [.sortedKeys, .withoutEscapingSlashes]), as: UTF8.self)
    }

    private func userEntryMatches(enginePath: String, mode: MCPAccessMode) throws -> Bool {
        guard let snapshot = try readUserEntrySnapshot(), let data = snapshot.data(using: .utf8),
              let entry = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              entry["command"] as? String == enginePath, entry["args"] as? [String] == ["mcp"],
              let environment = entry["env"] as? [String: String] else { return false }
        return accessMode(environment) == mode
    }

    private func restoreUserEntry(_ snapshot: String, path: String) async -> MCPRegistrationRecovery {
        do {
            let current = try readUserEntrySnapshot()
            if current == snapshot { return .restored }
            if current != nil {
                let removal = await runner(path, ["mcp", "remove", "--scope", "user", MCPClientRegistration.serverID], environment, timeout)
                guard operationFailure(removal) == nil else { return .failed }
            }
            let restore = await runner(path, ["mcp", "add-json", "--scope", "user", MCPClientRegistration.serverID, snapshot], environment, timeout)
            guard operationFailure(restore) == nil, try readUserEntrySnapshot() == snapshot else { return .failed }
            return .restored
        } catch { return .failed }
    }

    private func queryFailure(_ client: MCPClient, _ code: MCPClientOperationCode) -> MCPClientQuery {
        MCPClientQuery(client: client, code: code, configuration: .unknown, connection: .unknown)
    }

    private func operationFailure(_ result: MCPCommandResult) -> MCPClientOperationCode? {
        result.failure ?? (result.exitStatus == 0 ? nil : .commandFailed)
    }

    private func accessMode(_ environment: [String: String]) -> MCPAccessMode? {
        if environment["HOMESCREEN_READ_ONLY"] == "1" { return .readOnly }
        if environment["HOMESCREEN_READ_ONLY"] == "0" && environment["HOMESCREEN_ALLOW_APPLY"] == "1" { return .applyEnabled }
        return nil
    }
}

enum MCPProcessRunner {
    static func run(executablePath: String, arguments: [String], environment: [String: String], timeout: TimeInterval) async -> MCPCommandResult {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                continuation.resume(returning: runBlocking(executablePath, arguments, environment, timeout))
            }
        }
    }

    private static func runBlocking(_ path: String, _ arguments: [String], _ environment: [String: String], _ timeout: TimeInterval) -> MCPCommandResult {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("mcp-client-\(UUID().uuidString)")
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            defer { try? FileManager.default.removeItem(at: directory) }
            let stdoutURL = directory.appendingPathComponent("stdout")
            let stderrURL = directory.appendingPathComponent("stderr")
            _ = FileManager.default.createFile(atPath: stdoutURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
            _ = FileManager.default.createFile(atPath: stderrURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
            let stdout = try FileHandle(forWritingTo: stdoutURL)
            let stderr = try FileHandle(forWritingTo: stderrURL)
            defer { try? stdout.close(); try? stderr.close() }
            let process = Process()
            let finished = DispatchSemaphore(value: 0)
            process.executableURL = URL(fileURLWithPath: path)
            process.arguments = arguments
            process.environment = environment
            process.standardInput = FileHandle.nullDevice
            process.standardOutput = stdout
            process.standardError = stderr
            process.terminationHandler = { _ in finished.signal() }
            try process.run()
            let timedOut = finished.wait(timeout: .now() + max(0.01, timeout)) == .timedOut
            MCPSubprocess.stop(process, finished: finished)
            return MCPCommandResult(exitStatus: process.terminationStatus,
                stdout: String(decoding: (try? Data(contentsOf: stdoutURL)) ?? Data(), as: UTF8.self),
                stderr: String(decoding: (try? Data(contentsOf: stderrURL)) ?? Data(), as: UTF8.self),
                failure: timedOut ? .timedOut : nil)
        } catch { return MCPCommandResult(exitStatus: -1, failure: .launchFailed) }
    }
}

enum MCPSubprocess {
    static func stop(_ process: Process, finished: DispatchSemaphore) {
        if process.isRunning {
            process.terminate()
            if finished.wait(timeout: .now() + 0.2) == .timedOut && process.isRunning {
                kill(process.processIdentifier, SIGKILL)
            }
        }
        process.waitUntilExit()
    }
}
