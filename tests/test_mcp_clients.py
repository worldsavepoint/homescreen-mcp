"""Native client operations and startup checks use isolated executable fixtures."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def native_mcp_binary(tmp_path_factory):
    if shutil.which("swiftc") is None:
        pytest.skip("Swift compiler unavailable")
    folder = tmp_path_factory.mktemp("native-mcp")
    sources = [ROOT / "macapp/Shell/Sources/Homescreen" / name for name in
               ("MCPClientManager.swift", "MCPServiceCheck.swift", "MCPSubprocess.swift", "MCPEntryStore.swift", "MCPRegistrationJournal.swift")]
    assert all(source.is_file() for source in sources), "Native client and service-check modules are required"
    harness = folder / "Harness.swift"
    harness.write_text('''import Foundation
final class InterruptibleJournal: MCPRegistrationJournal {
    override func clear() throws {
        let fault = ProcessInfo.processInfo.environment["TEST_CLEANUP"]
        if fault == "before" { throw MCPClientOperationCode.recoveryFailed }
        try super.clear()
        if fault == "after" { throw MCPClientOperationCode.recoveryFailed }
    }
    override func save(_ record: MCPRegistrationRecord) throws {
        try super.save(record)
        if ProcessInfo.processInfo.environment["TEST_JOURNAL_EXIT"] == record.phase.rawValue { _exit(85) }
    }
}
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
            homeDirectory: home, timeout: timeout, executableLocator: locator.locate, journalFactory: InterruptibleJournal.init)
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
                      "cleanupPending":result.cleanupPending, "query": result.query.map(queryJSON) as Any? ?? NSNull()]
        } else if args[1] == "recover" {
            let result = await manager.recover(client:client,executablePath:path)
            output = ["code":result?.code.rawValue ?? "success"]
        } else if args[1] == "scope" {
            let query = await manager.query(client:client,executablePath:path)
            output = ["scope":query.scope.rawValue,"effective":query.mode?.rawValue ?? "", "user":query.userMode?.rawValue ?? "", "connection":query.connection.rawValue]
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
                   if key not in {"CLAUDE_CONFIG_DIR", "CLAUDE_CODE_CUSTOM_OAUTH_URL", "CODEX_HOME", "HOMESCREEN_DATA"}}
    return {**environment, "HOME": str(home), "PATH": str(tmp_path / "empty-path"),
            "TEST_STORE": str(tmp_path / "clients.json"), "TEST_LOG": str(tmp_path / "commands.jsonl"),
            "TEST_LAYER_OMITTED": "1", "TEST_PID": str(tmp_path / "child.pid"), "TEST_TIMEOUT": "3"}


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
key = "ios-homescreen-mcp"
target = Path(os.environ["HOME"]) / ".codex/config.toml"
if args[:2] == ["app-server", "generate-json-schema"]:
    assert args[2] == "--out"
    out = Path(args[3])
    methods = ["config/read", "config/batchWrite"]
    if os.getenv("TEST_NO_WRITE_RPC"):
        methods.pop()
    ref = lambda name: {"$ref": "#/definitions/" + name}
    methods_schema = [{"properties": {"method": {"enum": [m]}, "params": ref("Batch" if "batch" in m else "Read")}} for m in methods]
    defs = {"Batch": {"properties": {"edits": {"items": ref("Edit")}, "filePath": {}, "expectedVersion": {}}},
            "Read": {"properties": {"includeLayers": {}, "cwd": {}}},
            "Edit": {"properties": {"keyPath": {}, "mergeStrategy": ref("Merge"), "value": True}},
            "Merge": {"enum": ["replace", "upsert"]}}
    (out / "ClientRequest.json").write_text(json.dumps({"oneOf": methods_schema, "definitions": defs}))
    sys.exit(0)
if args == ["app-server"]:
    version = lambda: str(store.stat().st_mtime_ns if store.exists() else 0)
    initialized = False
    ready = False
    for line in sys.stdin:
        request = json.loads(line)
        assert "jsonrpc" not in request
        method, params = request["method"], request["params"]
        if method == "initialize":
            assert all(params["clientInfo"][k] for k in ("name", "title", "version"))
            initialized = True
            result = {"userAgent": "fixture"}
        elif method == "initialized":
            assert initialized and "id" not in request and params == {}
            ready = True
            continue
        elif method == "config/read":
            assert ready and params["includeLayers"] and params["cwd"] in (None, os.getcwd())
            effective = dict(entries.get(key, {}))
            origin = {"name":{"type":"project","dotCodexFolder":"/synthetic/.codex"},"version":"p"}
            project = {"command":"/project", "env":{"HOMESCREEN_READ_ONLY":"0","HOMESCREEN_ALLOW_APPLY":"1"}}
            if os.getenv("TEST_PROJECT") == "irrelevant": project = {"tool_timeout_sec":13}
            if os.getenv("TEST_PROJECT") == "remote": project = {"environment_id":"remote-box"}
            if params["cwd"] and os.getenv("TEST_PROJECT"): effective.update(project)
            layer = {"name": {"type": "user", "file": str(target), "profile": None}, "disabledReason": None,
                     "version": version(), "config": {"mcp_servers": entries, "privateSetting": "excluded"}}
            result = {"layers": [layer], "origins": {}, "config": {"mcp_servers": {key: effective} if effective else {}}}
            if os.getenv("TEST_BAD_LAYERS"): result["layers"] = [layer, layer]
            if os.getenv("TEST_LAYER_PATH"): layer["name"]["file"] = "/wrong/config.toml"
            if os.getenv("TEST_LAYER_REDACTED"): layer["config"]["mcp_servers"] = {key:{"command":"/old","env":{"SECRET":"<redacted>"}}}
            if os.getenv("TEST_LAYER_OMITTED") and not store.exists() and not any(os.getenv(k) for k in ("TEST_BAD_LAYERS","TEST_LAYER_PATH","TEST_LAYER_REDACTED")): result["layers"] = []
            if params["cwd"] and os.getenv("TEST_PROJECT") and key in entries:
                for field in project: result["origins"]["mcp_servers." + key + "." + field] = origin
                result["layers"].append({**origin,"disabledReason":None,"config":{"mcp_servers":{key:project}}})
        elif method == "config/batchWrite":
            assert ready and params["filePath"] == str(target) and params["expectedVersion"] == version()
            conflict = store.with_suffix(".conflicted")
            if os.getenv("TEST_CAS") and not conflict.exists():
                conflict.touch()
                if os.environ["TEST_CAS"] == "owned": entries[key]["advanced"] = [1]
                else: entries["unrelated"] = {"command":"/independent"}
                store.write_text(json.dumps(entries))
                print(json.dumps({"id":request["id"],"error":{"code":-32602,"message":"Configuration was modified since last read. Fetch latest version and retry."}}), flush=True)
                continue
            edit, = params["edits"]
            assert edit["keyPath"] == "mcp_servers." + key and edit["mergeStrategy"] == "replace"
            value = edit["value"]
            requested = value is not None and value.get("command") == "/new"
            if requested and os.getenv("TEST_WRONG_ADD"): value["command"] = "/unexpected-engine"
            if value is None: entries.pop(key, None)
            elif not (requested and os.getenv("TEST_SKIP_ADD")): entries[key] = value
            store.write_text(json.dumps(entries))
            if requested and os.getenv("TEST_INTERRUPT") == "add":
                os.kill(os.getppid(), signal.SIGKILL)
                sys.exit(0)
            if requested and os.getenv("TEST_PARTIAL_ADD"):
                print(json.dumps({"id":request["id"],"error":{"code":-32603,"message":"fixture write failure"}}),flush=True)
                continue
            result = {"status": "ok", "filePath": str(target), "version": version()}
            external = os.getenv("TEST_AFTER_ACK")
            if requested and external:
                if external == "ownedError":
                    entries[key] = {"command":"/external","args":["mcp"],"env":{}}
                    store.write_text(json.dumps(entries))
                    print(json.dumps({"id":request["id"],"error":{"code":-32603,"message":"ambiguous write"}}),flush=True)
                    continue
                if external == "owned": entries[key] = {"command":"/external","args":["mcp"],"env":{}}
                else: entries["unrelated"]["independent"] = True
                store.write_text(json.dumps(entries))
        else: raise AssertionError(method)
        print(json.dumps({"id":request["id"], "result":result}), flush=True)
    sys.exit(0)
def save():
    store.write_text(json.dumps(entries))
    if not os.environ.get("TEST_NO_SNAPSHOT"):
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"mcpServers": entries, "unrelatedSetting": True}))
action = args[1]
def interrupt_after(name):
    if os.getenv("TEST_INTERRUPT") == name:
        os.kill(os.getppid(), signal.SIGKILL)
        sys.exit(0)
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
    if os.getenv("TEST_PROJECT") in {"1","irrelevant"}:
        entry = {"command":"/project","args":["mcp"],"env":{"HOMESCREEN_READ_ONLY":"0","HOMESCREEN_ALLOW_APPLY":"1"}}
    if os.getenv("TEST_EFFECTIVE"): entry = {**entry, **json.loads(os.environ["TEST_EFFECTIVE"])}
    if "--json" in args:
        print(json.dumps({"name": "ios-homescreen-mcp", "enabled": entry.get("enabled", True), "transport": {"type": "stdio", **entry}}))
    else:
        scope = "Project config (/Users/user/project)" if os.getenv("TEST_PROJECT") else "User config (available in all projects)"
        output = "ios-homescreen-mcp:\\n  Scope: " + scope + "\\n  Status: " + os.environ.get("TEST_CONNECTION", "✓ Connected") + "\\n  Type: stdio\\n  Command: " + entry.get("command", "") + "\\n  Args: mcp\\n  Environment:\\n" + "\\n".join("    " + key + "=" + value for key, value in entry.get("env", {}).items())
        if os.environ.get("TEST_COLOR_OUTPUT"):
            color, reset = chr(27) + "[36m", chr(27) + "[0m"
            output = color + output.replace("\\n", reset + "\\n" + color) + reset
        print(output)
elif action == "remove":
    assert args == ["mcp", "remove", "--scope", "user", "ios-homescreen-mcp"]
    entries.pop("ios-homescreen-mcp", None)
    save()
    interrupt_after("remove")
elif action == "add-json":
    assert args[:5] == ["mcp", "add-json", "--scope", "user", "ios-homescreen-mcp"]
    if "ios-homescreen-mcp" in entries:
        sys.exit(2)
    value = json.loads(args[5])
    if value["command"].startswith("/new"):
        if os.getenv("TEST_FAIL") == "add": sys.exit(7)
        if os.getenv("TEST_HANG") == "add":
            Path(os.environ["TEST_PID"]).write_text(str(os.getpid()))
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(60)
        if os.getenv("TEST_SKIP_ADD"): sys.exit(0)
        if os.getenv("TEST_WRONG_ADD"): value["command"] = "/unexpected-engine"
    entries[key] = value
    save()
    interrupt_after("restore" if value["command"].startswith("/old") else "add")
    if os.getenv("TEST_PARTIAL_ADD") and value["command"].startswith("/new"): sys.exit(7)
elif action == "add":
    if entries.get("unrelated",{}).get("enabled_tools") == []: entries["unrelated"].pop("enabled_tools")
    if os.getenv("TEST_WORKER"):
        if os.fork():
            time.sleep(5)
            sys.exit(0)
        Path(os.environ["TEST_PID"]).write_text(str(os.getpid()))
        time.sleep(1.6)
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
    interrupt_after("add")
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
    assert all(command[0] == "app-server" or command[1] in {"get", "add", "remove"} for command in commands(sandbox))


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


@pytest.mark.parametrize("status,connection", [
    ("✔ Connected", "connected"),
    ("✓ Connected", "connected"),
    ("✘ Connection error", "disconnected"),
    ("✘ Failed to connect", "disconnected"),
    ("Not connected", "disconnected"),
    ("Connected status unavailable", "unknown"),
    ("Waiting for client", "unknown"),
    ("Connection error status unavailable", "unknown"),
])
@pytest.mark.parametrize("color", [False, True])
def test_documented_connection_labels_preserve_configuration_and_unknown_states(
        native_mcp_binary, sandbox, tmp_path, status, connection, color):
    client = fake_client(tmp_path)
    execute(native_mcp_binary, sandbox, "register", "claudeCode", client, "/engine")
    sandbox["TEST_CONNECTION"] = status
    if color:
        sandbox["TEST_COLOR_OUTPUT"] = "1"
    result = execute(native_mcp_binary, sandbox, "query", "claudeCode", client)
    assert result == {"code": "success", "configuration": "configured", "connection": connection, "mode": "readOnly"}


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
    assert json.loads(restore[-1][5]) == old
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
        if os.getenv("TEST_ENGINE") == "version": result["protocolVersion"] = "unsupported"
        if os.getenv("TEST_ENGINE") == "capability": result["capabilities"] = {}
        if os.getenv("TEST_ENGINE") == "info": result["serverInfo"]["version"] = 1
    elif message["method"] == "tools/list":
        tools = ["read_phone", "show_layout", "move", "diff"]
        result = {"tools": [{"name": name, "inputSchema": {"type": "object"}} for name in (tools[:1] if os.environ.get("TEST_ENGINE") == "tools" else tools)]}
        shape = os.getenv("TEST_SCHEMA")
        for tool in result["tools"]:
            if shape == "missing": tool.pop("inputSchema")
            if shape == "array": tool["inputSchema"] = {"type":"array"}
            if shape == "properties": tool["inputSchema"]["properties"] = []
            if shape == "required": tool["inputSchema"]["required"] = [3]
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
time.sleep(60)
''')
    path.chmod(0o755)
    return path


@pytest.mark.parametrize("behavior,code", [("success", "passed"), ("identity", "unexpectedServer"),
                                           ("tools", "missingTools"), ("timeout", "timedOut"),
                                           ("closed", "protocolError"), ("version", "protocolError"),
                                           ("capability", "protocolError"), ("info", "protocolError")])
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
    if behavior in {"version", "capability", "info"}:
        assert [message["method"] for message in log[1:]] == ["initialize"]
    if behavior == "success":
        assert [message["method"] for message in log[1:]] == ["initialize", "notifications/initialized", "tools/list"]
        assert result["tools"] == ["diff", "move", "read_phone", "show_layout"]


def test_service_check_launch_failure(native_mcp_binary, sandbox, tmp_path):
    result = execute(native_mcp_binary, sandbox, "check", "codex", tmp_path / "absent-engine")
    assert result["code"] == "launchFailed"

@pytest.mark.parametrize("client", ["codex", "claudeCode"])
@pytest.mark.parametrize("previous", [False, True])
@pytest.mark.parametrize("fault", ["TEST_PARTIAL_ADD", "TEST_WRONG_ADD", "TEST_SKIP_ADD"])
def test_registration_reconciles_exact_prior_entry(native_mcp_binary, sandbox, tmp_path, client, previous, fault):
    executable = fake_client(tmp_path)
    entries = {"unrelated": {"command": "keep me"}}
    if previous:
        entries["ios-homescreen-mcp"] = {"command": "/old", "args": ["mcp"], "env": {
            "HOMESCREEN_READ_ONLY": "0", "HOMESCREEN_ALLOW_APPLY": "1"},
            "advanced": {"引用": [True, 1, False, 0, 1.5, None]}}
    store = Path(sandbox["TEST_STORE"])
    store.write_text(json.dumps(entries))
    (Path(sandbox["HOME"]) / ".claude.json").write_text(json.dumps({"mcpServers": entries}))
    sandbox[fault] = "1"
    result = execute(native_mcp_binary, sandbox, "register", client, executable, "/new")
    expected = "commandFailed" if fault == "TEST_PARTIAL_ADD" else "invalidResponse"
    assert result["code"] == expected
    assert json.dumps(json.loads(store.read_text()), sort_keys=True) == json.dumps(entries, sort_keys=True)


@pytest.mark.parametrize("transport", [{"type": "streamable_http", "url": "https://example.invalid"},
    {"args": ["extra"]}, {"enabled": False}, {"env_vars": ["HOMESCREEN_READ_ONLY"]},
    {"env": {"HOMESCREEN_READ_ONLY": "1", "HOMESCREEN_ALLOW_APPLY": "1"}}])
def test_codex_verifies_effective_transport(native_mcp_binary, sandbox, tmp_path, transport):
    executable = fake_client(tmp_path)
    sandbox["TEST_EFFECTIVE"] = json.dumps(transport)
    result = execute(native_mcp_binary, sandbox, "register", "codex", executable, "/new")
    assert result["code"] == "invalidResponse"
    assert "ios-homescreen-mcp" not in json.loads(Path(sandbox["TEST_STORE"]).read_text())


@pytest.mark.parametrize("fault", ["TEST_NO_WRITE_RPC", "TEST_BAD_LAYERS","TEST_LAYER_PATH","TEST_LAYER_REDACTED"])
def test_codex_requires_recoverable_protocol_before_add(native_mcp_binary, sandbox, tmp_path, fault):
    executable = fake_client(tmp_path)
    sandbox[fault] = "1"
    result = execute(native_mcp_binary, sandbox, "register", "codex", executable, "/new")
    assert result["code"] in {"unsupportedClient", "snapshotReadFailed"}
    assert ["mcp", "add"] not in [c[:2] for c in commands(sandbox)]


def test_remote_claude_user_entry_keeps_oauth_registration(native_mcp_binary, sandbox, tmp_path):
    executable = fake_client(tmp_path)
    entries = {"ios-homescreen-mcp":{"type":"http","url":"https://example.invalid"}}
    Path(sandbox["TEST_STORE"]).write_text(json.dumps(entries))
    (Path(sandbox["HOME"])/".claude.json").write_text(json.dumps({"mcpServers":entries}))
    result = execute(native_mcp_binary, sandbox, "register", "claudeCode", executable, "/new")
    assert result["code"] == "remoteConflict"
    assert not Path(sandbox["TEST_LOG"]).exists() or all(c[1] == "get" for c in commands(sandbox))


def test_npm_symlink_uses_lexical_interpreter_directory(native_mcp_binary, sandbox, tmp_path):
    real = fake_client(tmp_path)
    npm = Path(sandbox["HOME"]) / ".nvm/versions/node/v20/bin"
    npm.mkdir(parents=True)
    (npm/"codex").symlink_to(real)
    (npm/"fixture-interpreter").symlink_to(sys.executable)
    real.write_text("#!/usr/bin/env fixture-interpreter\n" + real.read_text().split("\n",1)[1])
    result = execute(native_mcp_binary, sandbox, "register", "codex", "auto", "/new")
    assert result["code"] == "success"

@pytest.mark.parametrize("client", ["codex", "claudeCode"])
@pytest.mark.parametrize("requested", ["readonly", "apply"])
def test_successful_update_preserves_custom_user_options(native_mcp_binary, sandbox, tmp_path, client, requested):
    executable = fake_client(tmp_path)
    custom_env = {"HOMESCREEN_UDID":"fixture-device", "HOMESCREEN_DATA":"/fixture/data", "CUSTOM":"引用"}
    options = {"tool_timeout_sec":19, "enabled_tools":["a", "b"], "advanced":{"引用":[True,1,False,0]}}
    gates = {"HOMESCREEN_READ_ONLY":"0","HOMESCREEN_ALLOW_APPLY":"1"} if requested == "readonly" else {"HOMESCREEN_READ_ONLY":"1"}
    if client == "codex":
        options["env_vars"] = ["FORWARDED", {"name":"EXTRA","source":"local"}]
    old = {"command":"/old","args":["old"],"env":{**custom_env,**gates}, **options}
    if client == "codex":
        old["env_vars"] = [*options["env_vars"], {"name":"HOMESCREEN_ALLOW_APPLY","source":"local"}]
    entries = {"ios-homescreen-mcp":old, "unrelated":{"command":"/keep"}}
    store = Path(sandbox["TEST_STORE"])
    store.write_text(json.dumps(entries))
    (Path(sandbox["HOME"])/".claude.json").write_text(json.dumps({"mcpServers":entries}))
    result = execute(native_mcp_binary,sandbox,"register",client,executable,"/new",requested)
    assert result["code"] == "success"
    want_gates = {"HOMESCREEN_READ_ONLY":"1"} if requested == "readonly" else {"HOMESCREEN_READ_ONLY":"0","HOMESCREEN_ALLOW_APPLY":"1"}
    expected = {**entries,"ios-homescreen-mcp":{**options,"command":"/new","args":["mcp"],"env":{**custom_env,**want_gates}}}
    assert json.dumps(json.loads(store.read_text()),sort_keys=True) == json.dumps(expected,sort_keys=True)

@pytest.mark.parametrize("client", ["codex","claudeCode"])
def test_project_scope_is_distinct_from_user_mode(native_mcp_binary,sandbox,tmp_path,client):
    executable = fake_client(tmp_path)
    sandbox["TEST_PROJECT"] = "1"
    result = execute(native_mcp_binary,sandbox,"register",client,executable,"/new")
    assert result["code"] == "success"
    view = execute(native_mcp_binary,sandbox,"scope",client,executable)
    assert view == {"scope":"other","user":"readOnly","effective":"applyEnabled",
                    "connection":"connected" if client == "claudeCode" else "unknown"}


@pytest.mark.parametrize("client,phase", [("claudeCode","remove"),("claudeCode","add"),("codex","add")])
@pytest.mark.parametrize("external", [False,True])
def test_restart_after_interrupted_mutation(native_mcp_binary,sandbox,tmp_path,client,phase,external):
    executable = fake_client(tmp_path)
    assert execute(native_mcp_binary,sandbox,"register",client,executable,"/old")["code"] == "success"
    store = Path(sandbox["TEST_STORE"])
    prior = json.loads(store.read_text())
    start = subprocess.run([str(native_mcp_binary),"register",client,str(executable),"/new","apply"],
                           env={**sandbox,"TEST_INTERRUPT":phase},capture_output=True,timeout=10)
    assert start.returncode < 0
    journal = Path(sandbox["HOME"])/"Library/Application Support/homescreen-mcp/registration"/(client+".json")
    assert journal.stat().st_mode & 0o777 == 0o600
    assert journal.parent.stat().st_mode & 0o777 == 0o700
    assert "unrelated" not in journal.read_text() and "keep me" not in journal.read_text()
    assert json.loads(journal.read_text())["phase"] == ("adding" if phase == "add" else "removing")
    if external:
        edited = {**prior,"ios-homescreen-mcp":{"command":"/external","args":["mcp"],"env":{"HOMESCREEN_READ_ONLY":"1"}}}
        store.write_text(json.dumps(edited))
        (Path(sandbox["HOME"])/".claude.json").write_text(json.dumps({"mcpServers":edited}))
    recovered = execute(native_mcp_binary,sandbox,"recover",client,executable)
    assert recovered["code"] == ("recoveryConflict" if external else "success")
    assert json.loads(store.read_text()) == (edited if external else prior)
    assert journal.exists() == external

@pytest.mark.parametrize("conflict", ["owned", "unrelated"])
def test_codex_cas_reloads_and_compares_owned_value_including_scalar_type(native_mcp_binary,sandbox,tmp_path,conflict):
    executable = fake_client(tmp_path)
    entries = {"ios-homescreen-mcp":{"command":"/old","args":["mcp"],"env":{"HOMESCREEN_READ_ONLY":"1"},"advanced":[True]}}
    store = Path(sandbox["TEST_STORE"])
    store.write_text(json.dumps(entries))
    result = execute(native_mcp_binary,{**sandbox,"TEST_CAS":conflict},"register","codex",executable,"/new")
    actual = json.loads(store.read_text())
    if conflict == "owned":
        assert result["code"] == "recoveryConflict"
        assert actual["ios-homescreen-mcp"]["command"] == "/old"
        assert type(actual["ios-homescreen-mcp"]["advanced"][0]) is int
    else:
        assert result["code"] == "success"
        assert actual["unrelated"] == {"command":"/independent"}
        assert actual["ios-homescreen-mcp"]["command"] == "/new"
        assert actual["ios-homescreen-mcp"]["advanced"][0] is True


@pytest.mark.parametrize("existing", [True, False])
def test_codex_missing_user_layer_requires_absent_file(native_mcp_binary,sandbox,tmp_path,existing):
    executable = fake_client(tmp_path)
    path = Path(sandbox["HOME"])/".codex/config.toml"
    if existing:
        path.parent.mkdir()
        path.write_text("# fixture only")
    result = execute(native_mcp_binary,{**sandbox,"TEST_LAYER_OMITTED":"1"},"register","codex",executable,"/new")
    assert result["code"] == ("unsupportedClient" if existing else "success")
    assert Path(sandbox["TEST_STORE"]).exists() != existing


def test_normal_restart_keeps_committed_entry_and_retries_interrupted_recovery(native_mcp_binary,sandbox,tmp_path):
    client = "claudeCode"
    executable = fake_client(tmp_path)
    execute(native_mcp_binary,sandbox,"register",client,executable,"/old")
    store = Path(sandbox["TEST_STORE"])
    prior = json.loads(store.read_text())
    cmd = [str(native_mcp_binary),"register",client,str(executable),"/new"]
    journal = Path(sandbox["HOME"])/"Library/Application Support/homescreen-mcp/registration/claudeCode.json"
    proc = subprocess.run(cmd,env={**sandbox,"TEST_PARTIAL_ADD":"1","TEST_INTERRUPT":"restore"},capture_output=True,timeout=10)
    assert proc.returncode < 0
    assert json.loads(journal.read_text())["phase"] == "restoreRemoved"
    assert execute(native_mcp_binary,sandbox,"recover",client,executable)["code"] == "success"
    assert json.loads(store.read_text()) == prior and not journal.exists()
    proc = subprocess.run(cmd,env={**sandbox,"TEST_JOURNAL_EXIT":"committed"},capture_output=True,timeout=10)
    assert proc.returncode == 85
    assert json.loads(journal.read_text())["phase"] == "committed"
    assert execute(native_mcp_binary,sandbox,"recover",client,executable)["code"] == "success"
    assert json.loads(store.read_text())["ios-homescreen-mcp"]["command"] == "/new"
    assert not journal.exists()


def test_second_app_instance_cannot_start_an_overlapping_mutation(native_mcp_binary,sandbox,tmp_path):
    executable = fake_client(tmp_path)
    cmd = [str(native_mcp_binary),"register","codex",str(executable),"/first"]
    with subprocess.Popen(cmd,env={**sandbox,"TEST_TIMEOUT":"2","TEST_HANG":"add"},stdout=subprocess.PIPE,text=True) as first:
        deadline = time.monotonic()+8
        while not Path(sandbox["TEST_PID"]).exists():
            assert time.monotonic() < deadline and first.poll() is None
            time.sleep(0.01)
        assert execute(native_mcp_binary,sandbox,"register","codex",executable,"/second")["code"] == "operationBusy"
        out,_ = first.communicate(timeout=6)
        assert json.loads(out)["code"] == "timedOut"
    assert execute(native_mcp_binary,sandbox,"register","codex",executable,"/second")["code"] == "success"


@pytest.mark.parametrize("phase", ["prepared","removing","adding","observed","restoring","restoreRemoved"])
def test_restart_from_each_durable_phase(native_mcp_binary,sandbox,tmp_path,phase):
    executable = fake_client(tmp_path)
    execute(native_mcp_binary,sandbox,"register","claudeCode",executable,"/old")
    store = Path(sandbox["TEST_STORE"])
    prior = json.loads(store.read_text())
    env = {**sandbox,"TEST_JOURNAL_EXIT":phase}
    if phase in {"restoring","restoreRemoved"}: env["TEST_PARTIAL_ADD"] = "1"
    result = subprocess.run([str(native_mcp_binary),"register","claudeCode",str(executable),"/new"],
                            env=env,capture_output=True,timeout=10)
    assert result.returncode == 85
    assert execute(native_mcp_binary,sandbox,"recover","claudeCode",executable)["code"] == "success"
    assert json.loads(store.read_text()) == prior


def seed_user(sandbox, **extra):
    store = Path(sandbox["TEST_STORE"])
    entries = {"ios-homescreen-mcp":{"command":"/old","args":["mcp"],"env":{"HOMESCREEN_READ_ONLY":"1"},**extra},
               "unrelated":{"command":"/keep","enabled_tools":[]}}
    store.write_text(json.dumps(entries))
    (Path(sandbox["HOME"])/".claude.json").write_text(json.dumps({"mcpServers":entries}))
    return store,entries


def test_owned_process_group_prevents_late_apply(native_mcp_binary,sandbox,tmp_path):
    client = fake_client(tmp_path)
    result = execute(native_mcp_binary,{**sandbox,"TEST_WORKER":"1","TEST_TIMEOUT":"0.7","TEST_LAYER_OMITTED":"1"},
                     "register","codex",client,"/new","apply")
    assert result["code"] == "timedOut"
    time.sleep(1.7)
    store = Path(sandbox["TEST_STORE"])
    assert not store.exists() or "ios-homescreen-mcp" not in json.loads(store.read_text())
    assert_child_stopped(sandbox)


def test_existing_base_single_key_keeps_unrelated_allowlist(native_mcp_binary,sandbox,tmp_path):
    store,prior = seed_user(sandbox)
    result = execute(native_mcp_binary,sandbox,"register","codex",fake_client(tmp_path),"/new")
    assert result["code"] == "success"
    assert json.loads(store.read_text())["unrelated"] == prior["unrelated"]
    assert not any(cmd[:2] == ["mcp","add"] for cmd in commands(sandbox))


@pytest.mark.parametrize("external",["owned","ownedError","unrelated"])
def test_codex_compares_acknowledged_write_revision(native_mcp_binary,sandbox,tmp_path,external):
    store,_ = seed_user(sandbox,tool_timeout_sec=3)
    result = execute(native_mcp_binary,{**sandbox,"TEST_AFTER_ACK":external},"register","codex",fake_client(tmp_path),"/new")
    saved = json.loads(store.read_text())
    if external in {"owned","ownedError"}:
        assert result["code"] == ("recoveryConflict" if external == "owned" else "commandFailed") and result["recovery"] == "failed"
        assert saved["ios-homescreen-mcp"]["command"] == "/external"
        journal = Path(sandbox["HOME"])/"Library/Application Support/homescreen-mcp/registration/codex.json"
        assert journal.exists()
    else:
        assert result["code"] == "success" and saved["unrelated"]["independent"]


@pytest.mark.parametrize("fault",["","TEST_PARTIAL_ADD"])
def test_codex_selects_local_executor_and_restores_old_remote(native_mcp_binary,sandbox,tmp_path,fault):
    store,old = seed_user(sandbox,environment_id="remote-box")
    env = {**sandbox,fault:"1"} if fault else sandbox
    result = execute(native_mcp_binary,env,"register","codex",fake_client(tmp_path),"/new")
    saved = json.loads(store.read_text())
    if fault:
        assert result["code"] == "commandFailed" and saved == old
    else:
        assert result["code"] == "success" and saved["ios-homescreen-mcp"].get("environment_id","local") == "local"


def test_project_provenance_cannot_explain_unrelated_effective_differences(native_mcp_binary,sandbox,tmp_path):
    store,old = seed_user(sandbox)
    result = execute(native_mcp_binary,{**sandbox,"TEST_PROJECT":"irrelevant"},"register","codex",fake_client(tmp_path),"/new")
    assert result["code"] == "invalidResponse"
    assert json.loads(store.read_text()) == old


def test_oversize_claude_argv_rejected_before_remove(native_mcp_binary,sandbox,tmp_path):
    store,old = seed_user(sandbox,advanced="x"*os.sysconf("SC_ARG_MAX"))
    result = execute(native_mcp_binary,sandbox,"register","claudeCode",fake_client(tmp_path),"/new")
    assert result["code"] != "success" and result["recovery"] == "notNeeded"
    assert json.loads(store.read_text()) == old
    assert all(cmd[1] == "get" for cmd in commands(sandbox))
    assert not (Path(sandbox["HOME"])/"Library/Application Support/homescreen-mcp/registration/claudeCode.json").exists()


@pytest.mark.parametrize("fault",["before","after"])
def test_committed_cleanup_failure_preserves_success(native_mcp_binary,sandbox,tmp_path,fault):
    executable = fake_client(tmp_path)
    result = execute(native_mcp_binary,{**sandbox,"TEST_CLEANUP":fault},"register","claudeCode",executable,"/new")
    assert result["code"] == "success" and result["recovery"] == "notNeeded" and result["cleanupPending"]
    assert execute(native_mcp_binary,sandbox,"recover","claudeCode",executable)["code"] == "success"
    assert json.loads(Path(sandbox["TEST_STORE"]).read_text())["ios-homescreen-mcp"]["command"] == "/new"


@pytest.mark.parametrize("shape",["missing","array","properties","required"])
def test_both_checkers_reject_invalid_tool_descriptors(native_mcp_binary,sandbox,tmp_path,shape):
    engine = fake_engine(tmp_path)
    env = {**sandbox,"TEST_SCHEMA":shape}
    swift = execute(native_mcp_binary,env,"check","codex",engine)
    python = subprocess.run([sys.executable,str(ROOT/"macapp/check_mcp.py"),"--timeout","4","--",str(engine),"mcp"],
                            env=env,capture_output=True,timeout=8)
    assert (swift["code"],python.returncode) == ("protocolError",1)


def test_native_checker_accepts_actual_source_engine_without_source_access(native_mcp_binary,sandbox,tmp_path):
    # The guard fails immediately if initialization/discovery creates a Session.
    engine = tmp_path / "local-engine"
    engine.write_text(f"#!{sys.executable}\n" + """import os,sys
from pathlib import Path
sys.path.insert(0, os.environ["SYNTHETIC_ENGINE_ROOT"])
from homescreen import config
def unexpected(*args, **kwargs):
    raise AssertionError("Unexpected device or session activity during discovery")
config.session = config.make_source = unexpected
from homescreen.server import main
assert sys.argv[1:] == ["mcp"] and os.environ["HOMESCREEN_READ_ONLY"] == "1"
main()
""")
    engine.chmod(0o755)
    fixture = tmp_path/"fixture.json"
    fixture.write_text("[]")
    env = {**sandbox,"SYNTHETIC_ENGINE_ROOT":str(ROOT),"TEST_TIMEOUT":"6","HOMESCREEN_FIXTURE":str(fixture)}
    result = execute(native_mcp_binary,env,"check","codex",engine)
    assert result["code"] == "passed" and {"read_phone","show_layout","move","diff"} <= set(result["tools"])
    assert fixture.read_text() == "[]"


def test_project_remote_executor_is_reported_as_effective_override(native_mcp_binary,sandbox,tmp_path):
    executable = fake_client(tmp_path)
    env = {**sandbox,"TEST_PROJECT":"remote"}
    result = execute(native_mcp_binary,env,"register","codex",executable,"/new")
    assert result["code"] == "success"
    view = execute(native_mcp_binary,env,"scope","codex",executable)
    assert view == {"scope":"other","user":"readOnly","effective":"","connection":"unknown"}
