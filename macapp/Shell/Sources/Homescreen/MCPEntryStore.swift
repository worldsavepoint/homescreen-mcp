import Darwin
import Foundation

/// A canonical JSON object (including unknown fields) or an observed missing key.
enum MCPOwnedEntry: Equatable, Codable {
    case absent
    case present(String)

    init(_ object: Any?) throws {
        guard let object else { self = .absent; return }
        guard object is [String: Any] else { throw MCPClientOperationCode.snapshotReadFailed }
        self = .present(String(decoding: try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes]), as: UTF8.self))
    }

    func object() throws -> [String: Any]? {
        guard case .present(let json) = self else { return nil }
        guard let value = try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any] else {
            throw MCPClientOperationCode.snapshotReadFailed
        }
        return value
    }

    static func from(_ container: [String: Any], table: String) throws -> Self {
        guard let value = container[table] else { return .absent }
        guard let entries = value as? [String: Any] else { throw MCPClientOperationCode.snapshotReadFailed }
        return try Self(entries[MCPClientRegistration.serverID])
    }
}

struct MCPUserSnapshot {
    let file: String
    let entry: MCPOwnedEntry
    var version: String? = nil
    var scope: MCPClientScope = .unknown
}

struct MCPEntryStore {
    let client: MCPClient
    let executable: String
    let environment: [String: String]
    let home: URL
    let timeout: TimeInterval
    let runner: MCPCommandRunner
    var readOverride: (() async throws -> MCPUserSnapshot)? = nil
    var preflightOverride: (() async throws -> Void)? = nil

    func command(_ args: [String]) async throws {
        let result = await runner(executable, args, environment, timeout)
        if let failure = result.failure { throw failure }
        guard result.exitStatus == 0 else { throw MCPClientOperationCode.commandFailed }
    }

    private var codexFile: URL {
        (environment["CODEX_HOME"].flatMap { $0.hasPrefix("/") ? URL(fileURLWithPath: $0) : nil }
            ?? home.appendingPathComponent(".codex")).appendingPathComponent("config.toml").standardizedFileURL
    }

    private func exists(_ file: URL) throws -> Bool {
        var info = stat()
        if lstat(file.path, &info) == 0 { return true }
        if errno == ENOENT { return false }
        throw MCPClientOperationCode.snapshotReadFailed
    }

    /// Verify the selected binary's own schema, including the versioned restore method,
    /// before launching a CLI add that might need compensation.
    func preflight() async throws {
        if let preflightOverride { try await preflightOverride(); return }
        guard client == .codex else { return }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("mcp-schema-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let result = await runner(executable, ["app-server", "generate-json-schema", "--out", directory.path], environment, timeout)
        if let failure = result.failure { throw failure }
        guard result.exitStatus == 0,
              let data = try? Data(contentsOf: directory.appendingPathComponent("ClientRequest.json"), options: .mappedIfSafe),
              data.count <= MCPChildIO.limit, let schema = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let defs = schema["definitions"] as? [String: [String: Any]], let variants = schema["oneOf"] as? [[String: Any]] else {
            throw MCPClientOperationCode.unsupportedClient
        }
        func resolve(_ raw: Any?) -> [String: Any] {
            guard let value = raw as? [String: Any] else { return [:] }
            guard let ref = value["$ref"] as? String, ref.hasPrefix("#/definitions/") else { return value }
            return defs[String(ref.dropFirst("#/definitions/".count))] ?? [:]
        }
        func fields(_ method: String) -> [String: Any] {
            for variant in variants {
                let props = variant["properties"] as? [String: Any]
                if resolve(props?["method"])["enum"] as? [String] == [method] {
                    return resolve(props?["params"])["properties"] as? [String: Any] ?? [:]
                }
            }
            return [:]
        }
        let read = fields("config/read"), batch = fields("config/batchWrite")
        let edit = resolve(resolve(batch["edits"])["items"])["properties"] as? [String: Any]
        guard read["includeLayers"] != nil, read["cwd"] != nil, batch["filePath"] != nil, batch["expectedVersion"] != nil,
              edit?["value"] != nil, edit?["keyPath"] != nil, let strategies = resolve(edit?["mergeStrategy"])["enum"] as? [String],
              strategies.contains("replace") else { throw MCPClientOperationCode.unsupportedClient }
    }

    func read() async throws -> MCPUserSnapshot {
        if let readOverride { return try await readOverride() }
        if client == .claudeCode {
            let override = environment["CLAUDE_CONFIG_DIR"].flatMap { $0.isEmpty ? nil : URL(fileURLWithPath: $0) }
            let legacy = (override ?? home.appendingPathComponent(".claude")).appendingPathComponent(".config.json")
            let customOAuth = !(environment["CLAUDE_CODE_CUSTOM_OAUTH_URL"] ?? "").isEmpty
            let url = try exists(legacy) ? legacy : (override ?? home).appendingPathComponent(customOAuth ? ".claude-custom-oauth.json" : ".claude.json")
            guard try exists(url) else { return MCPUserSnapshot(file: url.path, entry: .absent) }
            guard let root = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any] else { throw MCPClientOperationCode.snapshotReadFailed }
            return try MCPUserSnapshot(file: url.path, entry: .from(root, table: "mcpServers"))
        }
        let result = try await rpc("config/read", ["includeLayers": true, "cwd": NSNull()])
        guard let layers = result["layers"] as? [[String: Any]] else { throw MCPClientOperationCode.unsupportedClient }
        var user: MCPUserSnapshot?
        var sawUser = false
        let key = "mcp_servers." + MCPClientRegistration.serverID
        let origins = result["origins"] as? [String: [String: Any]] ?? [:]
        let relevant = origins.filter { $0.key == key || $0.key.hasPrefix(key + ".") }
        let projectOrigins = relevant.values.compactMap { $0["name"] as? [String: Any] }.filter { $0["type"] as? String == "project" }
        let userOrigin = !relevant.isEmpty && relevant.values.allSatisfy {
            guard let source = $0["name"] as? [String: Any] else { return false }
            return source["type"] as? String == "user" && source["file"] as? String == codexFile.path &&
                (source["profile"] == nil || source["profile"] is NSNull)
        }
        var projectEntry = false
        for layer in layers {
            guard let name = layer["name"] as? [String: Any], let kind = name["type"] as? String else { throw MCPClientOperationCode.unsupportedClient }
            if kind == "user" { sawUser = true }
            if let disabled = layer["disabledReason"], !(disabled is NSNull) { continue }
            if let profile = name["profile"], !(profile is NSNull) { continue }
            guard kind == "user" || kind == "project" else { continue }
            guard let config = layer["config"] as? [String: Any] else { throw MCPClientOperationCode.unsupportedClient }
            let entry = try MCPOwnedEntry.from(config, table: "mcp_servers")
            if kind == "project" {
                if let folder = name["dotCodexFolder"] as? String, entry != .absent,
                   projectOrigins.contains(where: { $0["dotCodexFolder"] as? String == folder }) { projectEntry = true }
                continue
            }
            guard user == nil, let file = name["file"] as? String, file.hasPrefix("/"),
                  URL(fileURLWithPath: file).standardizedFileURL.path == codexFile.path,
                  let version = layer["version"] as? String, !version.isEmpty else { throw MCPClientOperationCode.unsupportedClient }
            if case .present(let json) = entry, json.contains("\"<redacted>\"") || json.contains("\"[REDACTED]\"") {
                throw MCPClientOperationCode.unsupportedClient
            }
            user = MCPUserSnapshot(file: file, entry: entry, version: version)
        }
        let scope: MCPClientScope = projectEntry ? .other : (userOrigin ? .user : .unknown)
        if var user {
            user.scope = scope
            return user
        }
        guard !sawUser, try !exists(codexFile) else { throw MCPClientOperationCode.unsupportedClient }
        return MCPUserSnapshot(file: codexFile.path, entry: .absent, scope: scope)
    }

    func rpc(_ method: String, _ params: [String: Any]) async throws -> [String: Any] {
        try await MCPSubprocess.session(executable, ["app-server"], environment, timeout) { io in
            try io.send(["id": 1, "method": "initialize", "params": ["clientInfo": [
                "name": "screen_organizer", "title": "Screen Organizer", "version": "1.3.0"]]])
            let handshake = try io.receive(1, mcp: false)
            guard handshake["userAgent"] is String else { throw MCPClientOperationCode.unsupportedClient }
            try io.send(["method": "initialized", "params": [:]])
            try io.send(["id": 2, "method": method, "params": params])
            return try io.receive(2, mcp: false)
        }
    }

    func replaceCodex(_ snapshot: MCPUserSnapshot, with desired: MCPOwnedEntry) async throws {
        do { try await write(snapshot, desired) }
        catch MCPClientOperationCode.versionConflict {
            let fresh = try await read()
            guard fresh.file == snapshot.file, fresh.entry == snapshot.entry, fresh.version != snapshot.version else {
                throw MCPClientOperationCode.recoveryConflict
            }
            do { try await write(fresh, desired) }
            catch MCPClientOperationCode.versionConflict { throw MCPClientOperationCode.recoveryConflict }
        }
    }

    private func write(_ snapshot: MCPUserSnapshot, _ prior: MCPOwnedEntry) async throws {
        guard let version = snapshot.version else { throw MCPClientOperationCode.recoveryConflict }
        let edit: [String: Any] = ["keyPath": "mcp_servers." + MCPClientRegistration.serverID,
                                   "mergeStrategy": "replace", "value": try prior.object() as Any? ?? NSNull()]
        let result = try await rpc("config/batchWrite", ["edits": [edit], "expectedVersion": version, "filePath": snapshot.file])
        guard ["ok", "okOverridden"].contains(result["status"] as? String ?? ""),
              result["filePath"] as? String == snapshot.file, result["version"] is String else { throw MCPClientOperationCode.recoveryFailed }
    }
}
