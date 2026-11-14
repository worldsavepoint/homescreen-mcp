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
        let env = ProcessInfo.processInfo.environment
        if env["TEST_SAVE_FAIL_BEFORE"] == record.phase.rawValue { throw MCPClientOperationCode.snapshotReadFailed }
        try super.save(record)
        if env["TEST_SAVE_FAIL_AFTER"] == record.phase.rawValue { throw MCPClientOperationCode.snapshotReadFailed }
        if env["TEST_JOURNAL_EXIT"] == record.phase.rawValue { _exit(85) }
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
        } else if args[1] == "query" || args[1] == "executor" {
            let result = await manager.query(client: client, executablePath: path)
            output = queryJSON(result)
            if args[1] == "executor" { output["localEnabled"] = result.localEnabled }
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
    path.write_text(f"#!{sys.executable}\n" + '''import hashlib, json, os, signal, sys, time
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
store = Path(os.environ["TEST_STORE"])
config = Path(os.environ["TEST_CONFIG_PATH"]) if "TEST_CONFIG_PATH" in os.environ else Path(os.environ.get("CLAUDE_CONFIG_DIR", os.environ["HOME"])) / ".claude.json"
entries = json.loads(store.read_text()) if store.exists() else {"unrelated": {"command": "keep me"}}
key = "ios-homescreen-mcp"
target = Path(os.environ["HOME"]) / ".codex/config.toml"
def trace_mutation(operation):
    with store.with_suffix(".mutations").open("a") as log:
        log.write(operation + "\\n")
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
    def version():
        data = json.loads(store.read_text()) if store.exists() else {}
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(canonical).hexdigest()
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
            marker = store.with_suffix(".read-stage")
            stage = marker.read_text() if marker.exists() else ""
            bounce = os.getenv("TEST_BOUNCE")
            if stage == "written" and params["cwd"]:
                marker.write_text("effective")
            return_to_intended = ((bounce == "cas" and stage == "conflict") or
                (bounce == "effective" and stage == "written" and params["cwd"]) or
                (bounce in ("final","final-prior") and stage == "effective" and not params["cwd"]))
            if return_to_intended:
                if bounce == "final-prior": entries.pop(key)
                else: entries[key] = {"command":"/external","args":["mcp"],"env":{}}
                store.write_text(json.dumps(entries))
            effective = dict(entries.get(key, {}))
            origin = {"name":{"type":"project","dotCodexFolder":"/synthetic/.codex"},"version":"p"}
            project = {"command":"/project", "env":{"HOMESCREEN_READ_ONLY":"0","HOMESCREEN_ALLOW_APPLY":"1"}}
            if os.getenv("TEST_PROJECT") == "irrelevant": project = {"tool_timeout_sec":13}
            if os.getenv("TEST_PROJECT") == "remote": project = {"environment_id":"remote-box"}
            if os.getenv("TEST_SYSTEM_EXECUTOR"):
                effective.setdefault("environment_id", "remote-system")
            if os.getenv("TEST_SYSTEM_ALLOW"):
                effective["env"] = {"HOMESCREEN_ALLOW_APPLY":"1", **effective.get("env", {})}
            if params["cwd"] and os.getenv("TEST_PROJECT"): effective.update(project)
            layer = {"name": {"type": "user", "file": str(target), "profile": None}, "disabledReason": None,
                     "version": version(), "config": {"mcp_servers": entries, "privateSetting": "excluded"}}
            result = {"layers": [layer], "origins": {}, "config": {"mcp_servers": {key: effective} if effective else {}}}
            if os.getenv("TEST_BAD_LAYERS"): result["layers"] = [layer, layer]
            if os.getenv("TEST_LAYER_PATH"): layer["name"]["file"] = "/wrong/config.toml"
            if os.getenv("TEST_LAYER_REDACTED"): layer["config"]["mcp_servers"] = {key:{"command":"/old","env":{"SECRET":"<redacted>"}}}
            if os.getenv("TEST_LAYER_OMITTED") and not store.exists() and not any(os.getenv(k) for k in ("TEST_BAD_LAYERS","TEST_LAYER_PATH","TEST_LAYER_REDACTED")): result["layers"] = []
            if os.getenv("TEST_SYSTEM_EXECUTOR"):
                system = {"name":{"type":"system","file":str(target.parent/"fixture-system.toml")},"version":"s"}
                system_entry = {"environment_id":"remote-system"}
                if os.getenv("TEST_SYSTEM_ALLOW"): system_entry["env"] = {"HOMESCREEN_ALLOW_APPLY":"1"}
                result["layers"].insert(0, {**system,"disabledReason":None,"config":{"mcp_servers":{key:system_entry}}})
                if "environment_id" not in entries.get(key,{}):
                    result["origins"]["mcp_servers." + key + ".environment_id"] = system
            if os.getenv("TEST_CAPTURE_BOOTSTRAP") and key in entries and "environment_id" not in entries[key]:
                store.with_suffix(".bootstrap").write_text(json.dumps({"user":entries[key], "effective":effective}))
            if os.getenv("TEST_READ_UNSUPPORTED"):
                print(json.dumps({"id":request["id"],"error":{"code":-32601,"message":"unsupported"}}), flush=True)
                continue
            if params["cwd"] and os.getenv("TEST_PROJECT") and key in entries:
                for field in project: result["origins"]["mcp_servers." + key + "." + field] = origin
                result["layers"].append({**origin,"disabledReason":None,"config":{"mcp_servers":{key:project}}})
            if return_to_intended:
                store.write_text(json.dumps({**entries, key:json.loads(store.with_suffix(".intended").read_text())}))
                marker.write_text("returned")
        elif method == "config/batchWrite":
            assert ready and request["id"] == 2 and params["filePath"] == str(target) and params["expectedVersion"] == version()
            edit, = params["edits"]
            assert edit["keyPath"] == "mcp_servers." + key and edit["mergeStrategy"] == "replace"
            value = edit["value"]
            requested = value is not None and value.get("command") == "/new"
            trace_mutation("delete" if value is None else "replace")
            conflict = store.with_suffix(".conflicted")
            cas = os.getenv("TEST_CAS") if value is not None else os.getenv("TEST_UNDO_CAS")
            if cas and (not conflict.exists() or cas == "twice"):
                conflict.touch()
                if cas == "owned": entries[key]["advanced"] = [1]
                elif cas == "bounce":
                    entries[key] = {"command":"/external","args":["mcp"],"env":{}}
                    store.with_suffix(".read-stage").write_text("conflict")
                    store.with_suffix(".intended").write_text(json.dumps(value))
                else: entries["unrelated"] = {"command":"/independent"}
                store.write_text(json.dumps(entries))
                print(json.dumps({"id":request["id"],"error":{"code":-32600,"message":"Cambió la revisión",
                      "data":{"config_write_error_code":"configVersionConflict"}}}), flush=True)
                continue
            if requested and os.getenv("TEST_WRITE_REPLY"):
                if os.getenv("TEST_REVERT_UNRELATED"):
                    entries["unrelated"] = {"command":"keep me"}
                    store.write_text(json.dumps(entries))
                print(os.environ["TEST_WRITE_REPLY"],flush=True)
                continue
            previous = entries.get(key)
            if requested and os.getenv("TEST_WRONG_ADD"): value["command"] = "/unexpected-engine"
            if value is None: entries.pop(key, None)
            elif not (requested and os.getenv("TEST_SKIP_ADD")): entries[key] = value
            store.write_text(json.dumps(entries))
            if value is None and os.getenv("TEST_UNDO_INTERRUPT"):
                if os.environ["TEST_UNDO_INTERRUPT"] == "recreate":
                    entries[key] = previous
                    store.write_text(json.dumps(entries))
                os.kill(os.getppid(), signal.SIGKILL)
                sys.exit(0)
            if requested and os.getenv("TEST_BOUNCE"):
                store.with_suffix(".read-stage").write_text("written")
                store.with_suffix(".intended").write_text(json.dumps(value))
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
                elif external == "implicit": entries[key].pop("environment_id", None)
                else: entries["unrelated"]["independent"] = True
                store.write_text(json.dumps(entries))
                outcome = os.getenv("TEST_AFTER_EDIT")
                if outcome == "crash":
                    os.kill(os.getppid(), signal.SIGKILL)
                    sys.exit(0)
                if outcome == "eof": sys.exit(0)
                if outcome == "error":
                    print(json.dumps({"id":2,"error":{"code":-32603,"message":"write rejected"}}),flush=True)
                    continue
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
        print(json.dumps({"name": "ios-homescreen-mcp", "enabled": entry.get("enabled", True), "transport": {"type": "stdio", **{k:v for k,v in entry.items() if k != "environment_id"}}}))
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
            name, value = args[index + 1].split("=", 1)
            env[name] = value
    trace_mutation("add")
    entries[key] = {"command": args[separator + 1], "args": args[separator + 2:], "env": env}
    if os.getenv("TEST_CLI_LOCAL"): entries[key]["environment_id"] = "local"
    if os.environ.get("TEST_WRONG_ADD"):
        entries[key]["command"] = "/unexpected-engine"
        if "--scope" not in args:
            entries[key]["env"] = {"HOMESCREEN_READ_ONLY":"0","HOMESCREEN_ALLOW_APPLY":"1"}
    save()
    interrupt_after("add" if "--scope" in args else "bootstrap")
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
        **({"environment_id":"local"} if client == "codex" else {}),
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
            if shape == "dialect-number": tool["inputSchema"]["$schema"] = 5
            if shape == "dialect-string": tool["inputSchema"]["$schema"] = "https://json-schema.org/draft/2020-12/schema"
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
    if client == "codex":
        expected["ios-homescreen-mcp"]["environment_id"] = "local"
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
    expected_phase = "versionedWritePending" if client == "codex" else ("adding" if phase == "add" else "removing")
    assert json.loads(journal.read_text())["phase"] == expected_phase
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
        assert result["code"] == "success" and saved["ios-homescreen-mcp"]["environment_id"] == "local"


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


@pytest.mark.parametrize("shape",["missing","array","properties","required","dialect-number","dialect-string"])
def test_both_checkers_validate_tool_descriptors(native_mcp_binary,sandbox,tmp_path,shape):
    engine = fake_engine(tmp_path)
    env = {**sandbox,"TEST_SCHEMA":shape}
    swift = execute(native_mcp_binary,env,"check","codex",engine)
    python = subprocess.run([sys.executable,str(ROOT/"macapp/check_mcp.py"),"--timeout","4","--",str(engine),"mcp"],
                            env=env,capture_output=True,timeout=8)
    assert (swift["code"],python.returncode) == (("passed",0) if shape == "dialect-string" else ("protocolError",1))


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


@pytest.mark.parametrize("existing", [True, False])
def test_local_registration_overrides_inherited_remote_executor(native_mcp_binary, sandbox, tmp_path, existing):
    if existing:
        seed_user(sandbox, environment_id="remote-user")
    env = {**sandbox, "TEST_SYSTEM_EXECUTOR":"1"}
    result = execute(native_mcp_binary, env, "register", "codex", fake_client(tmp_path), "/new")
    assert result["code"] == "success" and result["query"]["mode"] == "readOnly"
    entry = json.loads(Path(sandbox["TEST_STORE"]).read_text())["ios-homescreen-mcp"]
    assert entry["environment_id"] == "local"


@pytest.mark.parametrize("executor, fault, mode", [
    ("remote-box", "", None), ("local", "", "readOnly"),
    ("remote-box", "TEST_BAD_LAYERS", None), ("local", "TEST_READ_UNSUPPORTED", None)])
def test_query_mode_requires_effective_executor(native_mcp_binary, sandbox, tmp_path, executor, fault, mode):
    seed_user(sandbox, environment_id=executor)
    env = {**sandbox, fault:"1"} if fault else sandbox
    result = execute(native_mcp_binary, env, "executor", "codex", fake_client(tmp_path))
    assert result["configuration"] == "configured" and result["code"] == "success"
    assert result["mode"] == mode and result["localEnabled"] == (mode is not None)


@pytest.mark.parametrize("interrupt", ["bootstrap", "executor"])
def test_interrupted_first_registration_recovers_owned_entry(native_mcp_binary, sandbox, tmp_path, interrupt):
    cli = fake_client(tmp_path)
    env = {**sandbox, "TEST_INTERRUPT":"add" if interrupt == "executor" else "bootstrap"}
    process = subprocess.run([native_mcp_binary, "register", "codex", cli, "/new"], env=env,
                             capture_output=True, timeout=10)
    assert process.returncode < 0
    store = Path(sandbox["TEST_STORE"])
    assert json.loads(store.read_text())["ios-homescreen-mcp"].get("environment_id") == (
        "local" if interrupt == "executor" else None)
    assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "success"
    assert "ios-homescreen-mcp" not in json.loads(store.read_text())


@pytest.mark.parametrize("interrupt_after_ack", [False, True])
def test_bootstrap_preserves_later_edit_to_implicit_executor(native_mcp_binary, sandbox, tmp_path, interrupt_after_ack):
    cli = fake_client(tmp_path)
    env = {**sandbox,"TEST_AFTER_ACK":"implicit"}
    if interrupt_after_ack:
        proc = subprocess.run([native_mcp_binary,"register","codex",cli,"/new"], capture_output=True,
                              env={**env,"TEST_JOURNAL_EXIT":"acknowledged"}, timeout=10)
        assert proc.returncode == 85
    else:
        result = execute(native_mcp_binary, env, "register", "codex", cli, "/new")
        assert result["code"] == "recoveryConflict" and result["recovery"] == "failed"
    store = Path(sandbox["TEST_STORE"])
    entry = json.loads(store.read_text())["ios-homescreen-mcp"]
    assert entry["command"] == "/new" and "environment_id" not in entry
    assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "recoveryConflict"
    journal = Path(sandbox["HOME"])/"Library/Application Support/homescreen-mcp/registration/codex.json"
    assert json.loads(journal.read_text())["phase"] == "conflicted"
    assert json.loads(store.read_text())["ios-homescreen-mcp"] == entry


SERVER_ID = "ios-homescreen-mcp"
READ_ONLY = {"command":"/new", "args":["mcp"], "env":{"HOMESCREEN_READ_ONLY":"1"}}
LOCAL = {**READ_ONLY, "environment_id":"local"}
SENTINEL = {"unrelated":{"command":"keep me"}}


def journal_file(sandbox):
    return Path(sandbox["HOME"]) / "Library/Application Support/homescreen-mcp/registration/codex.json"


def mutations(sandbox):
    path = Path(sandbox["TEST_STORE"]).with_suffix(".mutations")
    return path.read_text().splitlines() if path.exists() else []


def interrupted(binary, env, cli, *args, action="register", status=85):
    proc = subprocess.run([binary, action, "codex", cli, *args], env=env, capture_output=True, timeout=10)
    assert proc.returncode == status, proc.stdout


def rpc_error(reason="configValidationError", code=-32600):
    return {"id":2,"error":{"code":code,"message":"Solicitud rechazada", "data":{"config_write_error_code":reason}}}


@pytest.mark.parametrize("reason", ["configValidationError","configRequirementReadonly"])
@pytest.mark.parametrize("crash", [False, True])
def test_first_registration_restores_bootstrap_after_rejected_executor_write(native_mcp_binary, sandbox, tmp_path, reason, crash):
    cli = fake_client(tmp_path)
    env = {**sandbox, "TEST_WRITE_REPLY":json.dumps(rpc_error(reason))}
    if crash:
        interrupted(native_mcp_binary, {**env, "TEST_JOURNAL_EXIT":"versionedWriteRejected"}, cli, "/new")
        assert mutations(sandbox) == ["add", "replace"]
        assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "success"
    else:
        result = execute(native_mcp_binary, env, "register", "codex", cli, "/new")
        assert (result["code"], result["recovery"]) == ("commandFailed","restored")
    assert json.loads(Path(sandbox["TEST_STORE"]).read_text()) == SENTINEL
    assert mutations(sandbox) == ["add", "replace", "delete"]
    assert not journal_file(sandbox).exists()


@pytest.mark.parametrize("outcome", ["crash", "error", "eof"])
def test_pre_acknowledgment_bootstrap_aba_survives_recovery(native_mcp_binary, sandbox, tmp_path, outcome):
    cli = fake_client(tmp_path)
    env = {**sandbox,"TEST_AFTER_ACK":"implicit","TEST_AFTER_EDIT":outcome}
    if outcome == "crash":
        interrupted(native_mcp_binary, env, cli, "/new", status=-9)
        assert json.loads(journal_file(sandbox).read_text())["phase"] == "versionedWritePending"
    else:
        result = execute(native_mcp_binary, env, "register", "codex", cli, "/new")
        assert result["recovery"] == "failed"
    store = Path(sandbox["TEST_STORE"])
    assert json.loads(store.read_text()) == {**SENTINEL, SERVER_ID:READ_ONLY}
    for _ in range(2):
        assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "recoveryConflict"
        assert json.loads(journal_file(sandbox).read_text())["phase"] == "conflicted"
        assert json.loads(store.read_text()) == {**SENTINEL, SERVER_ID:READ_ONLY}
        assert mutations(sandbox) == ["add", "replace"]


@pytest.mark.parametrize("reply", [
    {"id":2,"error":{"code":-32603,"message":"write rejected"}},
    rpc_error(code=-32603), rpc_error("configLayerReadonly"),
    {**rpc_error(),"id":1}, {**rpc_error(),"result":{}},
    {"id":2,"error":{"code":-32600,"data":{"config_write_error_code":"configValidationError"}}},
    {"id":2,"result":{"status":"ok"}},
    {"id":2,"error":{"code":-32603,"message":"Configuration was modified since last read. Fetch latest version and retry."}},
], ids=["generic","wrong-code","unknown-reason","wrong-id","both-branches","missing-message","missing-revision","cas-text"])
def test_indeterminate_batch_response_preserves_bootstrap(native_mcp_binary, sandbox, tmp_path, reply):
    cli = fake_client(tmp_path)
    env = {**sandbox, "TEST_WRITE_REPLY":json.dumps(reply)}
    result = execute(native_mcp_binary, env, "register", "codex", cli, "/new")
    assert result["recovery"] == "failed"
    assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "recoveryConflict"
    assert json.loads(journal_file(sandbox).read_text())["phase"] == "conflicted"
    assert json.loads(Path(sandbox["TEST_STORE"]).read_text()) == {**SENTINEL, SERVER_ID:READ_ONLY}
    assert mutations(sandbox) == ["add", "replace"]


@pytest.mark.parametrize("position", ["before","after"])
def test_failed_rejection_save_leaves_bootstrap_pending(native_mcp_binary, sandbox, tmp_path, position):
    cli = fake_client(tmp_path)
    env = {**sandbox, "TEST_WRITE_REPLY":json.dumps(rpc_error()),
           "TEST_SAVE_FAIL_" + position.upper():"versionedWriteRejected"}
    result = execute(native_mcp_binary, env, "register", "codex", cli, "/new")
    assert result["recovery"] == "failed"
    assert journal_file(sandbox).is_file()
    assert json.loads(Path(sandbox["TEST_STORE"]).read_text()) == {**SENTINEL, SERVER_ID:READ_ONLY}
    assert mutations(sandbox) == ["add","replace"]


@pytest.mark.parametrize("stage", ["versionedWritePending","acknowledged","conflicted"])
def test_failed_forward_phase_save_cannot_send_or_compensate_write(native_mcp_binary, sandbox, tmp_path, stage):
    cli = fake_client(tmp_path)
    env = {**sandbox,"TEST_SAVE_FAIL_AFTER":stage,"TEST_AFTER_ACK":"implicit"}
    result = execute(native_mcp_binary, env, "register", "codex", cli, "/new")
    assert result["recovery"] == "failed"
    assert json.loads(journal_file(sandbox).read_text())["phase"] == stage
    before = ["add"] if stage == "versionedWritePending" else ["add","replace"]
    assert mutations(sandbox) == before
    assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "recoveryConflict"
    assert json.loads(Path(sandbox["TEST_STORE"]).read_text()) == {**SENTINEL, SERVER_ID:READ_ONLY}
    assert mutations(sandbox) == before


@pytest.mark.parametrize("scenario", ["exhausted","rejected","rejected-original-revision","generic-original-revision"])
def test_bounded_cas_retry_requires_its_own_receipt(native_mcp_binary, sandbox, tmp_path, scenario):
    cli = fake_client(tmp_path)
    env = {**sandbox, "TEST_CAS":"twice" if scenario == "exhausted" else "unrelated"}
    if scenario != "exhausted":
        reply = rpc_error(code=-32603) if scenario.startswith("generic") else rpc_error()
        env["TEST_WRITE_REPLY"] = json.dumps(reply)
        if scenario.endswith("original-revision"): env["TEST_REVERT_UNRELATED"] = "1"
    result = execute(native_mcp_binary, env, "register", "codex", cli, "/new")
    undone = scenario == "rejected-original-revision"
    assert result["recovery"] == ("restored" if undone else "failed")
    assert result["code"] == ("recoveryConflict" if scenario == "exhausted" else "commandFailed")
    assert mutations(sandbox) == ["add","replace","replace"] + (["delete"] if undone else [])
    unrelated = SENTINEL if scenario.endswith("original-revision") else {"unrelated":{"command":"/independent"}}
    assert json.loads(Path(sandbox["TEST_STORE"]).read_text()) == (unrelated if undone else {**unrelated, SERVER_ID:READ_ONLY})


@pytest.mark.parametrize("recreate", [False,True])
def test_bootstrap_undo_is_single_use_across_lost_reply(native_mcp_binary, sandbox, tmp_path, recreate):
    cli = fake_client(tmp_path)
    env = {**sandbox, "TEST_WRITE_REPLY":json.dumps(rpc_error()), "TEST_UNDO_INTERRUPT":"recreate" if recreate else "deleted"}
    interrupted(native_mcp_binary, env, cli, "/new", status=-9)
    journal = journal_file(sandbox)
    assert json.loads(journal.read_text())["phase"] == "bootstrapUndoPending"
    for _ in range(2):
        assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == ("recoveryConflict" if recreate else "success")
        assert journal.exists() == recreate
        assert json.loads(Path(sandbox["TEST_STORE"]).read_text()) == ({**SENTINEL, SERVER_ID:READ_ONLY} if recreate else SENTINEL)
        assert mutations(sandbox) == ["add","replace","delete"]


def test_bootstrap_undo_cas_refusal_never_retries(native_mcp_binary, sandbox, tmp_path):
    cli = fake_client(tmp_path)
    env = {**sandbox, "TEST_WRITE_REPLY":json.dumps(rpc_error()), "TEST_UNDO_CAS":"unrelated"}
    result = execute(native_mcp_binary, env, "register", "codex", cli, "/new")
    assert result["recovery"] == "failed"
    store = Path(sandbox["TEST_STORE"])
    assert json.loads(store.read_text()) == {SERVER_ID:READ_ONLY,"unrelated":{"command":"/independent"}}
    # Restore even the original fingerprint after the CAS refusal.
    store.write_text(json.dumps({**SENTINEL, SERVER_ID:READ_ONLY}))
    assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "recoveryConflict"
    assert mutations(sandbox) == ["add","replace","delete"]


@pytest.mark.parametrize("next_action,existing", [("recover", False), ("register",False), ("recover",True)])
def test_manually_restored_prior_retires_conflict(native_mcp_binary, sandbox, tmp_path, next_action, existing):
    cli = fake_client(tmp_path)
    store = Path(sandbox["TEST_STORE"])
    if existing:
        store,prior = seed_user(sandbox, advanced={"flags":[True,1,False,0]})
    else:
        prior = SENTINEL
    result = execute(native_mcp_binary, {**sandbox,"TEST_AFTER_ACK":"owned"}, "register", "codex", cli, "/new")
    journal = journal_file(sandbox)
    assert result["recovery"] == "failed" and json.loads(journal.read_text())["phase"] == "conflicted"
    before = mutations(sandbox)
    if existing:
        similar = json.loads(json.dumps(prior))
        similar[SERVER_ID]["advanced"]["flags"][0] = 1
        store.write_text(json.dumps(similar))
        assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "recoveryConflict"
    store.write_text(json.dumps(prior))
    for fault in ["TEST_BAD_LAYERS", "TEST_LAYER_PATH"]:
        assert execute(native_mcp_binary, {**sandbox,fault:"1"}, "recover", "codex", cli)["code"] != "success"
        assert journal.exists() and mutations(sandbox) == before
    if next_action == "recover":
        assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "success"
        assert not journal.exists() and mutations(sandbox) == before
        assert json.dumps(json.loads(store.read_text()),sort_keys=True) == json.dumps(prior,sort_keys=True)
    assert execute(native_mcp_binary, sandbox, "register", "codex", cli, "/next")["code"] == "success"
    assert mutations(sandbox) == before + ["replace"]
    assert json.loads(store.read_text())["unrelated"] == prior["unrelated"] and not journal.exists()


@pytest.mark.parametrize("stage", ["cas","effective","final"])
def test_observed_ownership_change_remains_a_conflict(native_mcp_binary, sandbox, tmp_path, stage):
    cli = fake_client(tmp_path)
    env = {**sandbox, "TEST_BOUNCE":stage}
    if stage == "cas": env["TEST_CAS"] = "bounce"
    result = execute(native_mcp_binary, env, "register", "codex", cli, "/new")
    assert (result["code"],result["recovery"]) == ("recoveryConflict","failed")
    assert json.loads(journal_file(sandbox).read_text())["phase"] == "conflicted"
    assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "recoveryConflict"
    assert json.loads(Path(sandbox["TEST_STORE"]).read_text()) == {**SENTINEL,SERVER_ID:LOCAL}
    assert mutations(sandbox) == ["add","replace"]


def test_acknowledged_conflict_stays_terminal_when_user_reinstates_intended(native_mcp_binary, sandbox, tmp_path):
    cli = fake_client(tmp_path)
    result = execute(native_mcp_binary, {**sandbox,"TEST_AFTER_ACK":"implicit"}, "register", "codex", cli, "/new")
    assert result["code"] == "recoveryConflict"
    store = Path(sandbox["TEST_STORE"])
    store.write_text(json.dumps({**SENTINEL,SERVER_ID:LOCAL}))
    assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "recoveryConflict"
    assert json.loads(store.read_text()) == {**SENTINEL, SERVER_ID:LOCAL}
    assert mutations(sandbox) == ["add","replace"]


def test_verification_observing_exact_prior_retires_without_compensation(native_mcp_binary, sandbox, tmp_path):
    cli = fake_client(tmp_path)
    # Another edit reinstates intended just after verification observed exact prior absence.
    result = execute(native_mcp_binary, {**sandbox, "TEST_BOUNCE":"final-prior"}, "register", "codex", cli, "/new")
    assert (result["code"], result["recovery"]) == ("recoveryConflict", "restored")
    assert not journal_file(sandbox).exists()
    assert json.loads(Path(sandbox["TEST_STORE"]).read_text()) == {**SENTINEL, SERVER_ID:LOCAL}
    assert mutations(sandbox) == ["add","replace"]


@pytest.mark.parametrize("stop", ["success","bootstrap","bootstrapObserved"])
def test_first_apply_bootstrap_pins_read_only_before_local_executor(native_mcp_binary, sandbox, tmp_path, stop):
    cli = fake_client(tmp_path)
    store = Path(sandbox["TEST_STORE"])
    env = {**sandbox,"TEST_SYSTEM_EXECUTOR":"1","TEST_SYSTEM_ALLOW":"1","TEST_CAPTURE_BOOTSTRAP":"1"}
    assert not store.exists() and not (Path(env["HOME"])/".codex/config.toml").exists()
    if stop == "success":
        result = execute(native_mcp_binary, env, "register", "codex", cli, "/new", "apply")
        assert result["code"] == "success" and result["query"]["mode"] == "applyEnabled"
    else:
        option = "TEST_INTERRUPT" if stop == "bootstrap" else "TEST_JOURNAL_EXIT"
        interrupted(native_mcp_binary, {**env,option:stop}, cli, "/new", "apply", status=-9 if stop == "bootstrap" else 85)
        execute(native_mcp_binary, env, "scope", "codex", cli)
    interim = {**READ_ONLY,"env":{"HOMESCREEN_READ_ONLY":"1","HOMESCREEN_ALLOW_APPLY":"0"}}
    assert json.loads(store.with_suffix(".bootstrap").read_text()) == {"user":interim, "effective":{**interim,"environment_id":"remote-system"}}
    if stop == "success":
        assert json.loads(store.read_text()) == {**SENTINEL, SERVER_ID:{**LOCAL,"env":{"HOMESCREEN_READ_ONLY":"0","HOMESCREEN_ALLOW_APPLY":"1"}}}
        assert mutations(sandbox) == ["add","replace"]
    else:
        assert json.loads(store.read_text()) == {**SENTINEL,SERVER_ID:interim}
        assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "success"
        assert json.loads(store.read_text()) == SENTINEL and mutations(sandbox) == ["add","delete"]


@pytest.mark.parametrize("final_matches_cli", [False,True])
def test_pending_write_cannot_reclaim_cli_postimage(native_mcp_binary, sandbox, tmp_path, final_matches_cli):
    cli = fake_client(tmp_path)
    env = {**sandbox, "TEST_JOURNAL_EXIT":"versionedWritePending"}
    if final_matches_cli: env["TEST_CLI_LOCAL"] = "1"
    interrupted(native_mcp_binary, env, cli, "/new")
    journal = journal_file(sandbox)
    if not final_matches_cli:
        # Frozen Codex 'adding' records with a bootstrap predate the separate dispatch phase.
        record = json.loads(journal.read_text())
        record["phase"] = "adding"
        record.pop("bootstrapExpected", None)
        journal.write_text(json.dumps(record))
    assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "recoveryConflict"
    assert json.loads(Path(sandbox["TEST_STORE"]).read_text()) == {**SENTINEL, SERVER_ID:(LOCAL if final_matches_cli else READ_ONLY)}
    assert mutations(sandbox) == ["add"]


@pytest.mark.parametrize("phase", ["bootstrapping","adding"])
def test_legacy_codex_journal_recovers_known_postimage(native_mcp_binary, sandbox, tmp_path, phase):
    cli = fake_client(tmp_path)
    # No bootstrapExpected or observed fields in the older on-disk format.
    journal = journal_file(sandbox)
    journal.parent.mkdir(parents=True, mode=0o700)
    intended = {**LOCAL,"env":{"HOMESCREEN_READ_ONLY":"0","HOMESCREEN_ALLOW_APPLY":"1"}}
    record = {"client":"codex","scope":"user","server":SERVER_ID,"file":str(Path(sandbox["HOME"])/".codex/config.toml"),
              "prior":{"absent":{}},"intended":{"present":{"_0":json.dumps(intended,sort_keys=True,separators=(",",":"))}},"phase":phase}
    journal.write_text(json.dumps(record))
    journal.chmod(0o600)
    entry = dict(intended)
    if phase == "bootstrapping": del entry["environment_id"]
    store = Path(sandbox["TEST_STORE"])
    store.write_text(json.dumps({**SENTINEL,SERVER_ID:entry}))
    assert execute(native_mcp_binary, sandbox, "recover", "codex", cli)["code"] == "success"
    assert not journal.exists() and json.loads(store.read_text()) == SENTINEL
    assert mutations(sandbox) == ["delete"]


@pytest.mark.parametrize("cli_error", [False, True])
def test_first_cli_wrong_apply_entry_is_restored(native_mcp_binary, sandbox, tmp_path, cli_error):
    store = Path(sandbox["TEST_STORE"])
    assert not store.exists() and not (Path(sandbox["HOME"])/".codex/config.toml").exists()
    env = {**sandbox, "TEST_WRONG_ADD":"1"}
    if cli_error:
        env["TEST_PARTIAL_ADD"] = "1"
    result = execute(native_mcp_binary, env, "register", "codex", fake_client(tmp_path), "/new", "apply")
    assert result["code"] == ("commandFailed" if cli_error else "invalidResponse")
    assert result["recovery"] == "restored"
    assert "ios-homescreen-mcp" not in json.loads(store.read_text())
    assert not (Path(sandbox["HOME"])/"Library/Application Support/homescreen-mcp/registration/codex.json").exists()


@pytest.mark.parametrize("interruption, external", [("bootstrap", None), ("bootstrapObserved", None),
                                                    ("bootstrapObserved", "owned"), ("bootstrapObserved", "revision")])
def test_first_cli_wrong_postimage_recovery_requires_ownership(native_mcp_binary, sandbox, tmp_path, interruption, external):
    cli = fake_client(tmp_path)
    env = {**sandbox, "TEST_WRONG_ADD":"1",
           ("TEST_INTERRUPT" if interruption == "bootstrap" else "TEST_JOURNAL_EXIT"):interruption}
    process = subprocess.run([native_mcp_binary, "register", "codex", cli, "/new", "apply"],
                             env=env, capture_output=True, timeout=10)
    assert process.returncode != 0
    store = Path(sandbox["TEST_STORE"])
    entries = json.loads(store.read_text())
    key = "ios-homescreen-mcp"
    assert entries[key]["command"] == "/unexpected-engine" and entries[key]["env"]["HOMESCREEN_ALLOW_APPLY"] == "1"
    if external == "owned":
        entries[key]["command"] = "/external-engine"
    elif external == "revision":
        entries["unrelated"]["command"] = "/external"
    if external:
        store.write_text(json.dumps(entries))
    result = execute(native_mcp_binary, sandbox, "recover", "codex", cli)
    if interruption == "bootstrapObserved" and not external:
        assert result["code"] == "success" and key not in json.loads(store.read_text())
    else:
        assert result["code"] == "recoveryConflict" and json.loads(store.read_text()) == entries
