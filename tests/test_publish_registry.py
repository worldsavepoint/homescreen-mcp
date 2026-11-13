"""Registry publication compares exact versions before using OIDC authentication."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "macapp/publish_registry.sh"


def metadata():
    return {"$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.worldsavepoint/home-screen-organizer", "version": "1.2.0", "title": "Home Screen Organizer",
            "packages": [{"registryType": "mcpb", "identifier": "https://github.com/worldsavepoint/ios-homescreen-organizer/releases/download/v1.2.0/home-screen-organizer-1.2.0-macos.mcpb",
                          "fileSha256": "a" * 64, "transport": {"type": "stdio"}}]}


@contextmanager
def endpoint(status, response):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def publish(tmp_path, url, *, fail="", local=None):
    file = tmp_path / "server metadata.json"
    file.write_text(json.dumps(local or metadata()))
    publisher = tmp_path / "mcp-publisher"
    publisher.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ["CLI_LOG"]).open("a") as stream:
    stream.write(json.dumps(args) + "\\n")
if args[0] == os.environ.get("FAIL_COMMAND"):
    sys.exit(1)
''')
    publisher.chmod(0o755)
    log = tmp_path / "publisher.jsonl"
    result = subprocess.run(["bash", str(SCRIPT), str(file)], capture_output=True, text=True, timeout=10,
                            env={**os.environ, "MCP_REGISTRY_URL": url, "MCP_PUBLISHER": str(publisher),
                                 "CLI_LOG": str(log), "FAIL_COMMAND": fail})
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls, file


def test_missing_version_validates_then_authenticates_and_publishes(tmp_path):
    with endpoint(404, {"error": "Server not found"}) as (url, requests):
        result, calls, file = publish(tmp_path, url)
    assert result.returncode == 0, result.stderr
    assert requests == ["/v0.1/servers/io.github.worldsavepoint%2Fhome-screen-organizer/versions/1.2.0"]
    assert calls == [["validate", str(file)], ["login", "github-oidc", "--registry=" + url], ["publish", str(file)]]


def test_identical_published_version_skips_authentication(tmp_path):
    with endpoint(200, {"server": metadata(), "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active"}}}) as (url, requests):
        result, calls, _ = publish(tmp_path, url)
    assert result.returncode == 0, result.stderr
    assert len(requests) == 1
    assert calls == []
    assert "already published" in result.stdout.lower()


@pytest.mark.parametrize("changed", ["hash", "url", "transport", "version", "name", "missing-package"])
def test_existing_metadata_conflict_stops_before_authentication(tmp_path, changed):
    remote = metadata()
    if changed == "hash":
        remote["packages"][0]["fileSha256"] = "b" * 64
    elif changed == "url":
        remote["packages"][0]["identifier"] += "-other"
    elif changed == "transport":
        remote["packages"][0]["transport"] = {"type": "streamable-http", "url": "https://example.com/mcp"}
    elif changed == "missing-package":
        remote["packages"] = []
    else:
        remote[changed] = "different"
    with endpoint(200, {"server": remote}) as (url, _):
        result, calls, _ = publish(tmp_path, url)
    assert result.returncode != 0
    assert calls == []
    assert "differ" in result.stderr.lower()


@pytest.mark.parametrize("status,response", [(503, {"error": "unavailable"}), (200, {"unexpected": "response"})])
def test_lookup_failure_is_not_treated_as_missing_version(tmp_path, status, response):
    with endpoint(status, response) as (url, _):
        result, calls, _ = publish(tmp_path, url)
    assert result.returncode != 0
    assert calls == []


@pytest.mark.parametrize("fail,commands", [("validate", ["validate"]), ("login", ["validate", "login"]),
                                           ("publish", ["validate", "login", "publish"])])
def test_publisher_failure_stops_the_command_sequence(tmp_path, fail, commands):
    with endpoint(404, {"error": "Server not found"}) as (url, _):
        result, calls, _ = publish(tmp_path, url, fail=fail)
    assert result.returncode != 0
    assert [call[0] for call in calls] == commands
