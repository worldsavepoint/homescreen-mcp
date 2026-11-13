import Foundation

/// Stdio configuration for the engine included in this app bundle; read-only by default.
struct MCPSetup {
    let executablePath: String
    var mode: MCPAccessMode = .readOnly

    var launchCommand: String {
        let quotedPath = "'" + executablePath.replacingOccurrences(of: "'", with: "'\"'\"'") + "'"
        let environment = mode == .readOnly ? "HOMESCREEN_READ_ONLY=1" : "HOMESCREEN_READ_ONLY=0 HOMESCREEN_ALLOW_APPLY=1"
        return "\(environment) \(quotedPath) mcp"
    }

    var cursorClaudeJSON: String {
        json(["mcpServers": ["ios-homescreen-mcp": server]])
    }

    var codexTOML: String {
        let command = json(executablePath, options: [.fragmentsAllowed, .withoutEscapingSlashes])
            .replacingOccurrences(of: "\u{7f}", with: "\\u007f")
        return """
        [mcp_servers.ios-homescreen-mcp]
        command = \(command)
        args = ["mcp"]

        [mcp_servers.ios-homescreen-mcp.env]
        HOMESCREEN_READ_ONLY = "\(mode == .readOnly ? "1" : "0")"
        """
        + (mode == .applyEnabled ? "\nHOMESCREEN_ALLOW_APPLY = \"1\"" : "")
    }

    var vscodeJSON: String {
        var configuration = server
        configuration["type"] = "stdio"
        configuration["tools"] = ["*"]
        return json(["mcpServers": ["ios-homescreen-mcp": configuration]])
    }

    private var server: [String: Any] {
        ["command": executablePath, "args": ["mcp"], "env": mode == .readOnly
            ? ["HOMESCREEN_READ_ONLY": "1"] : ["HOMESCREEN_READ_ONLY": "0", "HOMESCREEN_ALLOW_APPLY": "1"]]
    }

    private func json(_ value: Any, options: JSONSerialization.WritingOptions = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]) -> String {
        // These values contain only strings, arrays and dictionaries, all valid JSON values.
        let data = try! JSONSerialization.data(withJSONObject: value, options: options)
        return String(decoding: data, as: UTF8.self)
    }
}
