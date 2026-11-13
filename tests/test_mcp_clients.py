"""Native client operations and startup checks use isolated executable fixtures."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def native_mcp_binary(tmp_path_factory):
    if shutil.which("swiftc") is None:
        pytest.skip("Swift compiler unavailable")
    folder = tmp_path_factory.mktemp("native-mcp")
    sources = [ROOT / "macapp/Shell/Sources/Homescreen" / name for name in
               ("MCPClientManager.swift", "MCPServiceCheck.swift")]
    assert all(source.is_file() for source in sources), "Native client and service-check modules are required"
    harness = folder / "Harness.swift"
    harness.write_text('''import Foundation
@main struct Harness {
    static func main() async {
        let args = CommandLine.arguments
        let client: MCPClient = args[2] == "codex" ? .codex : .claudeCode
        let environment = ProcessInfo.processInfo.environment
        let timeout = Double(environment["TEST_TIMEOUT"] ?? "2")!
        let home = URL(fileURLWithPath: environment["HOME"]!)
        let locator = MCPExecutableLocator(environment: environment, homeDirectory: home,
            systemDirectories: [], applicationDirectories: [home.appendingPathComponent("Applications").path])
        let manager = MCPClientManager(environment: environment,
            homeDirectory: home, timeout: timeout, executableLocator: locator.locate)
        let path: String? = args[3] == "auto" ? nil : args[3]
        var output: [String: Any] = [:]
        if args[1] == "detect" {
            let result = await manager.detect(client: client, executablePath: path)
            output = ["availability": result.availability.rawValue, "path": result.executablePath as Any? ?? NSNull()]
        } else if args[1] == "query" {
            let result = await manager.query(client: client, executablePath: path)
            output = queryJSON(result)
        } else if args[1] == "register" {
            let mode: MCPAccessMode = args.count > 5 && args[5] == "apply" ? .applyEnabled : .readOnly
            let result = await manager.register(client: client, executablePath: path, enginePath: args[4], mode: mode)
            output = ["code": result.code.rawValue, "mode": result.mode.rawValue, "recovery": result.recovery.rawValue,
                      "query": result.query.map(queryJSON) as Any? ?? NSNull()]
        } else {
            let result = await MCPServiceCheck(timeout: timeout, environment: environment).run(executablePath: args[3])
            output = ["code": result.code.rawValue, "tools": result.tools.sorted()]
        }
        print(String(decoding: try! JSONSerialization.data(withJSONObject: output), as: UTF8.self))
    }
    static func queryJSON(_ result: MCPClientQuery) -> [String: Any] {
        ["code": result.code.rawValue, "configuration": result.configuration.rawValue,
         "connection": result.connection.rawValue, "mode": result.mode?.rawValue as Any? ?? NSNull()]
    }
}
''')
    binary = folder / "native-mcp"
    result = subprocess.run(["swiftc", "-parse-as-library", "-module-cache-path", str(folder / "modules"),
                             *map(str, sources), str(harness), "-o", str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.fixture
def sandbox(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"CLAUDE_CONFIG_DIR", "CLAUDE_CODE_CUSTOM_OAUTH_URL"}}
    return {**environment, "HOME": str(home), "PATH": str(tmp_path / "empty-path"),
            "TEST_STORE": str(tmp_path / "clients.json"), "TEST_LOG": str(tmp_path / "commands.jsonl"),
            "TEST_PID": str(tmp_path / "child.pid"), "TEST_TIMEOUT": "3"}


def execute(binary, sandbox, action, client="codex", executable="auto", *args):
    result = subprocess.run([str(binary), action, client, str(executable), *map(str, args)],
                            env=sandbox, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def fake_client(tmp_path, name="client"):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n" + '''import json, os, signal, sys, time
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
store = Path(os.environ["TEST_STORE"])
config = Path(os.environ["TEST_CONFIG_PATH"]) if "TEST_CONFIG_PATH" in os.environ else Path(os.environ.get("CLAUDE_CONFIG_DIR", os.environ["HOME"])) / ".claude.json"
entries = json.loads(store.read_text()) if store.exists() else {"unrelated": {"command": "keep me"}}
def save():
    store.write_text(json.dumps(entries))
    if not os.environ.get("TEST_NO_SNAPSHOT"):
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"mcpServers": entries, "unrelatedSetting": True}))
action = args[1]
if os.environ.get("TEST_FAIL") == action:
    print("synthetic command failure", file=sys.stderr)
    sys.exit(7)
if os.environ.get("TEST_HANG") == action:
    Path(os.environ["TEST_PID"]).write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(60)
if action == "get":
    if os.environ.get("TEST_GET_MALFORMED"):
        print("unexpected output")
        sys.exit(0)
    if "ios-homescreen-mcp" not in entries:
        print("No MCP server named 'ios-homescreen-mcp' found." if "--json" in args else "No MCP server found with name: ios-homescreen-mcp", file=sys.stderr)
        sys.exit(1)
    entry = entries["ios-homescreen-mcp"]
    if "--json" in args:
        print(json.dumps({"name": "ios-homescreen-mcp", "enabled": True, "transport": {"type": "stdio", **entry}}))
    else:
        print("ios-homescreen-mcp:\\n  Scope: User config (available in all projects)\\n  Status: " + os.environ.get("TEST_CONNECTION", "✓ Connected") + "\\n  Type: stdio\\n  Command: " + entry["command"] + "\\n  Args: mcp\\n  Environment:\\n" + "\\n".join("    " + key + "=" + value for key, value in entry["env"].items()))
elif action == "remove":
    assert args == ["mcp", "remove", "--scope", "user", "ios-homescreen-mcp"]
    entries.pop("ios-homescreen-mcp", None)
    save()
elif action == "add-json":
    assert args[:5] == ["mcp", "add-json", "--scope", "user", "ios-homescreen-mcp"]
    if "ios-homescreen-mcp" in entries:
        sys.exit(2)
    entries["ios-homescreen-mcp"] = json.loads(args[5])
    save()
elif action == "add":
    if "--scope" in args and "ios-homescreen-mcp" in entries:
        sys.exit(2)
    if os.environ.get("TEST_SKIP_ADD"):
        sys.exit(0)
    separator = args.index("--")
    env = {}
    for index, argument in enumerate(args):
        if argument == "--env":
            key, value = args[index + 1].split("=", 1)
            env[key] = value
    entries["ios-homescreen-mcp"] = {"command": args[separator + 1], "args": args[separator + 2:], "env": env}
    if os.environ.get("TEST_WRONG_ADD"):
        entries["ios-homescreen-mcp"]["command"] = "/unexpected-engine"
    save()
    if os.environ.get("TEST_PARTIAL_ADD"):
        sys.exit(7)
''')
    path.chmod(0o755)
    return path


def commands(sandbox):
    return [json.loads(line) for line in Path(sandbox["TEST_LOG"]).read_text().splitlines()]


@pytest.mark.parametrize("client", ["codex", "claudeCode"])
def test_register_and_update_preserve_arguments_and_unrelated_entries(native_mcp_binary, sandbox, tmp_path, client):
    executable = fake_client(tmp_path, 'client "引用" folder\'s')
    engine = '/Applications/Screen "引用" folder\'s $(false) `false`.app/engine'
    result = execute(native_mcp_binary, sandbox, "register", client, executable, engine)
    assert result["code"] == "success"
    assert result["mode"] == "readOnly"
    assert result["query"]["configuration"] == "configured"
    assert result["query"]["connection"] == ("unknown" if client == "codex" else "connected")
    expected = (["mcp", "add", "ios-homescreen-mcp", "--env", "HOMESCREEN_READ_ONLY=1", "--", engine, "mcp"]
                if client == "codex" else ["mcp", "add", "--scope", "user", "--env", "HOMESCREEN_READ_ONLY=1",
                                           "--transport", "stdio", "ios-homescreen-mcp", "--", engine, "mcp"])
    assert expected in commands(sandbox)
    replacement = engine + " newer"
    result = execute(native_mcp_binary, sandbox, "register", client, executable, replacement, "apply")
    assert result["code"] == "success"
    assert result["mode"] == "applyEnabled"
    assert result["query"]["mode"] == "applyEnabled"
    entries = json.loads(Path(sandbox["TEST_STORE"]).read_text())
    assert entries == {"unrelated": {"command": "keep me"}, "ios-homescreen-mcp": {
        "command": replacement, "args": ["mcp"], "env": {"HOMESCREEN_READ_ONLY": "0", "HOMESCREEN_ALLOW_APPLY": "1"}}}
    assert all(command[1] in {"get", "add", "remove"} for command in commands(sandbox))


def test_detection_uses_path_user_locations_and_selected_executable(native_mcp_binary, sandbox, tmp_path):
    assert execute(native_mcp_binary, sandbox, "detect")["availability"] == "notFound"
    selected = fake_client(tmp_path, 'selected "引用" client')
    assert execute(native_mcp_binary, sandbox, "detect", "codex", selected)["path"] == str(selected)
    assert execute(native_mcp_binary, sandbox, "detect", "codex", tmp_path)["availability"] == "notExecutable"
    path_client = fake_client(tmp_path / "bin", "codex")
    sandbox["PATH"] = str(path_client.parent)
    assert execute(native_mcp_binary, sandbox, "detect")["path"] == str(path_client)
    sandbox["PATH"] = ""
    user_client = fake_client(Path(sandbox["HOME"]) / ".local/bin", "claude")
    assert execute(native_mcp_binary, sandbox, "detect", "claudeCode")["path"] == str(user_client)
    bundled = fake_client(Path(sandbox["HOME"]) / "Applications/Codex.app/Contents/Resources", "codex")
    assert execute(native_mcp_binary, sandbox, "detect")["path"] == str(bundled)


def test_absence_failures_and_reported_connection_are_distinct(native_mcp_binary, sandbox, tmp_path):
    assert execute(native_mcp_binary, sandbox, "query")["code"] == "notFound"
    client = fake_client(tmp_path)
    assert execute(native_mcp_binary, sandbox, "query", "codex", client)["configuration"] == "notConfigured"
    sandbox["TEST_FAIL"] = "add"
    assert execute(native_mcp_binary, sandbox, "register", "codex", client, "/engine")["code"] == "commandFailed"
    del sandbox["TEST_FAIL"]
    execute(native_mcp_binary, sandbox, "register", "claudeCode", client, "/engine")
    sandbox["TEST_CONNECTION"] = "✗ Failed to connect"
    result = execute(native_mcp_binary, sandbox, "query", "claudeCode", client)
    assert result == {"code": "success", "configuration": "configured", "connection": "disconnected", "mode": "readOnly"}
    sandbox["TEST_FAIL"] = "get"
    result = execute(native_mcp_binary, sandbox, "query", "claudeCode", client)
    assert result["configuration"] == "unknown"
    assert result["code"] == "commandFailed"


def test_malformed_query_and_launch_failure_are_typed(native_mcp_binary, sandbox, tmp_path):
    client = fake_client(tmp_path)
    sandbox["TEST_GET_MALFORMED"] = "1"
    for name in ("codex", "claudeCode"):
        result = execute(native_mcp_binary, sandbox, "query", name, client)
        assert result["code"] == "invalidResponse"
        assert result["configuration"] == "unknown"
        assert result["connection"] == "unknown"
    broken = tmp_path / "broken-executable"
    broken.write_text("#!/absent-synthetic-interpreter\n")
    broken.chmod(0o755)
    assert execute(native_mcp_binary, sandbox, "register", "codex", broken, "/engine")["code"] == "launchFailed"


def test_unrecognized_connection_status_does_not_claim_connected(native_mcp_binary, sandbox, tmp_path):
    client = fake_client(tmp_path)
    execute(native_mcp_binary, sandbox, "register", "claudeCode", client, "/engine")
    sandbox["TEST_CONNECTION"] = "Not connected"
    result = execute(native_mcp_binary, sandbox, "query", "claudeCode", client)
    assert result["configuration"] == "configured"
    assert result["connection"] == "disconnected"
    sandbox["TEST_CONNECTION"] = "Connected status unavailable"
    assert execute(native_mcp_binary, sandbox, "query", "claudeCode", client)["connection"] == "unknown"


def assert_child_stopped(sandbox):
    pid = int(Path(sandbox["TEST_PID"]).read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_client_timeout_cleans_up_and_next_registration_recovers(native_mcp_binary, sandbox, tmp_path):
    client = fake_client(tmp_path)
    sandbox["TEST_TIMEOUT"] = "1"
    sandbox["TEST_HANG"] = "add"
    result = execute(native_mcp_binary, sandbox, "register", "codex", client, "/engine")
    assert result["code"] == "timedOut"
    assert_child_stopped(sandbox)
    del sandbox["TEST_HANG"]
    assert execute(native_mcp_binary, sandbox, "register", "codex", client, "/engine")["code"] == "success"


@pytest.mark.parametrize("failure", ["failure", "timeout"])
@pytest.mark.parametrize("layout", ["default", "custom", "legacy", "customOAuth"])
def test_claude_failed_update_restores_exact_user_entry(native_mcp_binary, sandbox, tmp_path, failure, layout):
    client = fake_client(tmp_path)
    if layout == "custom":
        sandbox["CLAUDE_CONFIG_DIR"] = str(tmp_path / 'config "引用"')
    old = {"type": "stdio", "command": '/old "引用" engine', "args": ["mcp", "quote ' and spaces", "\\引用"],
           "env": {"HOMESCREEN_READ_ONLY": "1", "SYNTHETIC": "quote ' \\\"引用"}}
    entries = {"unrelated": {"command": "keep me"}, "ios-homescreen-mcp": old}
    Path(sandbox["TEST_STORE"]).write_text(json.dumps(entries))
    config = Path(sandbox.get("CLAUDE_CONFIG_DIR", sandbox["HOME"])) / ".claude.json"
    if layout == "legacy":
        config = Path(sandbox["HOME"]) / ".claude/.config.json"
    if layout == "customOAuth":
        sandbox["CLAUDE_CODE_CUSTOM_OAUTH_URL"] = "https://synthetic.example"
        config = Path(sandbox["HOME"]) / ".claude-custom-oauth.json"
    sandbox["TEST_CONFIG_PATH"] = str(config)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"mcpServers": entries, "unrelatedSetting": True}))
    sandbox["TEST_FAIL" if failure == "failure" else "TEST_HANG"] = "add"
    sandbox["TEST_TIMEOUT"] = "1"
    result = execute(native_mcp_binary, sandbox, "register", "claudeCode", client, "/new-engine")
    assert result["code"] == ("commandFailed" if failure == "failure" else "timedOut")
    assert result["recovery"] == "restored"
    assert json.loads(Path(sandbox["TEST_STORE"]).read_text()) == entries
    assert json.loads(config.read_text()) == {"mcpServers": entries, "unrelatedSetting": True}
    restore = [command for command in commands(sandbox) if command[1] == "add-json"]
    assert json.loads(restore[0][5]) == old
    if failure == "timeout":
        assert_child_stopped(sandbox)


def test_claude_partial_failed_add_restores_previous_entry(native_mcp_binary, sandbox, tmp_path):
    client = fake_client(tmp_path)
    execute(native_mcp_binary, sandbox, "register", "claudeCode", client, "/old-engine")
    previous = json.loads(Path(sandbox["TEST_STORE"]).read_text())
    sandbox["TEST_PARTIAL_ADD"] = "1"
    result = execute(native_mcp_binary, sandbox, "register", "claudeCode", client, "/new-engine")
    assert result["code"] == "commandFailed"
    assert result["recovery"] == "restored"
    assert json.loads(Path(sandbox["TEST_STORE"]).read_text()) == previous


@pytest.mark.parametrize("behavior", ["TEST_SKIP_ADD", "TEST_WRONG_ADD"])
def test_claude_unverified_success_restores_previous_entry(native_mcp_binary, sandbox, tmp_path, behavior):
    client = fake_client(tmp_path)
    execute(native_mcp_binary, sandbox, "register", "claudeCode", client, "/old-engine")
    previous = json.loads(Path(sandbox["TEST_STORE"]).read_text())
    sandbox[behavior] = "1"
    result = execute(native_mcp_binary, sandbox, "register", "claudeCode", client, "/new-engine")
    assert result["code"] == "invalidResponse"
    assert result["recovery"] == "restored"
    assert result["query"]["configuration"] == "configured"
    assert json.loads(Path(sandbox["TEST_STORE"]).read_text()) == previous


def test_claude_unreadable_snapshot_does_not_remove_registration(native_mcp_binary, sandbox, tmp_path):
    client = fake_client(tmp_path)
    sandbox["TEST_NO_SNAPSHOT"] = "1"
    execute(native_mcp_binary, sandbox, "register", "claudeCode", client, "/engine")
    previous = Path(sandbox["TEST_STORE"]).read_text()
    result = execute(native_mcp_binary, sandbox, "register", "claudeCode", client, "/new-engine")
    assert result["code"] == "snapshotReadFailed"
    assert Path(sandbox["TEST_STORE"]).read_text() == previous
    assert not any(command[1] == "remove" for command in commands(sandbox))


def fake_engine(tmp_path):
    path = tmp_path / 'engine "引用" folder\'s'
    path.write_text(f"#!{sys.executable}\n" + '''import json, os, signal, sys, time
from pathlib import Path
Path(os.environ["TEST_PID"]).write_text(str(os.getpid()))
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps({"args": sys.argv[1:], "data": os.environ["HOMESCREEN_DATA"], "readonly": os.environ.get("HOMESCREEN_READ_ONLY"), "apply": os.environ.get("HOMESCREEN_ALLOW_APPLY")}) + "\\n")
signal.signal(signal.SIGTERM, signal.SIG_IGN)
for line in sys.stdin:
    message = json.loads(line)
    with open(os.environ["TEST_LOG"], "a") as log:
        log.write(json.dumps(message) + "\\n")
    if os.environ.get("TEST_ENGINE") == "timeout":
        time.sleep(60)
    if os.environ.get("TEST_ENGINE") == "closed":
        sys.exit(0)
    if message["method"] == "initialize":
        result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "wrong" if os.environ.get("TEST_ENGINE") == "identity" else "ios-homescreen-mcp", "version": "1.3.0"}}
    elif message["method"] == "tools/list":
        tools = ["read_phone", "show_layout", "move", "diff"]
        result = {"tools": [{"name": name, "inputSchema": {"type": "object"}} for name in (tools[:1] if os.environ.get("TEST_ENGINE") == "tools" else tools)]}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
time.sleep(60)
''')
    path.chmod(0o755)
    return path


@pytest.mark.parametrize("behavior,code", [("success", "passed"), ("identity", "unexpectedServer"),
                                           ("tools", "missingTools"), ("timeout", "timedOut"),
                                           ("closed", "protocolError")])
def test_service_check_protocol_isolated_environment_and_cleanup(native_mcp_binary, sandbox, tmp_path, behavior, code):
    engine = fake_engine(tmp_path)
    sandbox.update(TEST_ENGINE=behavior, TEST_TIMEOUT="1.5", HOMESCREEN_READ_ONLY="0", HOMESCREEN_ALLOW_APPLY="1",
                   HOMESCREEN_DATA=str(tmp_path / "user-data"))
    result = execute(native_mcp_binary, sandbox, "check", "codex", engine)
    assert result["code"] == code
    assert_child_stopped(sandbox)
    log = commands(sandbox)
    assert log[0]["args"] == ["mcp"]
    assert log[0]["readonly"] == "1"
    assert log[0]["apply"] is None
    assert log[0]["data"] != sandbox["HOMESCREEN_DATA"]
    assert not Path(log[0]["data"]).exists()
    assert all(message.get("method") in {"initialize", "notifications/initialized", "tools/list"} for message in log[1:])
    if behavior == "success":
        assert [message["method"] for message in log[1:]] == ["initialize", "notifications/initialized", "tools/list"]
        assert result["tools"] == ["diff", "move", "read_phone", "show_layout"]


def test_service_check_launch_failure(native_mcp_binary, sandbox, tmp_path):
    result = execute(native_mcp_binary, sandbox, "check", "codex", tmp_path / "absent-engine")
    assert result["code"] == "launchFailed"
