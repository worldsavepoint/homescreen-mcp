"""Packaging, image decoding and launcher checks."""
import io
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from PIL import Image

from homescreen.colors import dominant
from homescreen.organize import fetch_categories

ROOT = Path(__file__).resolve().parents[1]


def image_bytes(format, size=(32, 32)):
    out = io.BytesIO()
    Image.new("RGB", size, "red").save(out, format=format)
    return out.getvalue()


def test_color_accepts_real_png():
    assert dominant(image_bytes("PNG"))["family"] == "red"


def test_color_rejects_other_image_decoders():
    with pytest.raises(ValueError, match="PNG"):
        dominant(image_bytes("JPEG"))


def test_color_rejects_oversized_png_before_decoding():
    with pytest.raises(ValueError, match="large"):
        dominant(image_bytes("PNG", (2049, 1)))


def test_color_rejects_invalid_png():
    with pytest.raises(ValueError, match="PNG"):
        dominant(b"not an image")


def test_category_cache_is_private_even_if_preexisting(tmp_path):
    cache = tmp_path / "cache" / "categories.json"
    cache.parent.mkdir(mode=0o755)
    cache.write_text('{"com.apple.test": "Apple"}')
    cache.chmod(0o644)
    assert fetch_categories(["com.apple.test"], cache) == {"com.apple.test": "Apple"}
    assert cache.stat().st_mode & 0o777 == 0o600
    assert cache.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(shutil.which("swiftc") is None, reason="Swift compiler unavailable")
def test_swift_backend_authentication_and_navigation(tmp_path):
    # This harness runs only pure request/URL validation, never the app or a server.
    harness = tmp_path / "main.swift"
    harness.write_text(r'''
import Foundation
let token = try EngineSecurity.makeToken()
let secondToken = try EngineSecurity.makeToken()
assert(token.count == 64 && token != secondToken)
let base = URL(string: "http://127.0.0.1:8765/")!
let challenge = String(repeating: "0", count: 64)
let healthSecret = String(repeating: "1", count: 64)
let req = EngineSecurity.healthRequest(base: base, challenge: challenge)
assert(req.url!.absoluteString == "http://127.0.0.1:8765/v1/health")
assert(req.value(forHTTPHeaderField: "X-Token") == nil)
assert(req.value(forHTTPHeaderField: "X-Homescreen-Challenge") == challenge)
let response = HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
let validBody = #"{"app":"homescreen","ready":true,"proof":"fa40bbcaacdf85af802097ac9bd203a5fba3224a673e880aa08ac85361c340e1"}"#
assert(EngineSecurity.isHealthy(data: Data(validBody.utf8), response: response, base: base, secret: healthSecret, challenge: challenge))
for body in [validBody.replacingOccurrences(of: "homescreen", with: "other"), validBody.replacingOccurrences(of: "true", with: "false"), validBody.replacingOccurrences(of: "true", with: "1"), #"{"app":"homescreen","ready":true}"#, "<html>unrelated server</html>"] {
    assert(!EngineSecurity.isHealthy(data: Data(body.utf8), response: response, base: base, secret: healthSecret, challenge: challenge))
}
assert(!EngineSecurity.isHealthy(data: Data(validBody.utf8), response: response, base: base, secret: token, challenge: challenge))
assert(!EngineSecurity.isHealthy(data: Data(validBody.utf8), response: response, base: base, secret: healthSecret, challenge: token))
let redirected = HTTPURLResponse(url: URL(string: "https://example.com/health")!, statusCode: 200, httpVersion: nil, headerFields: nil)!
assert(!EngineSecurity.isHealthy(data: Data(validBody.utf8), response: redirected, base: base, secret: healthSecret, challenge: challenge))
assert(EngineSecurity.pageURL(base: base, token: token).fragment == "token=" + token)
assert(NavigationPolicy.destination(URL(string: "http://127.0.0.1:8765/?x=1")!, origin: base) == .embedded)
assert(NavigationPolicy.destination(URL(string: "https://example.com")!, origin: base) == .browser)
for value in ["file:///etc/passwd", "x-apple.systempreferences:foo", "javascript:alert(1)", "data:text/html,hello", "about:blank", "ftp://127.0.0.1:8765/"] {
    assert(NavigationPolicy.destination(URL(string: value)!, origin: base) == .blocked)
}
''')
    binary = tmp_path / "security-tests"
    compiled = subprocess.run(["swiftc", "-module-cache-path", str(tmp_path / "modules"),
                               str(ROOT / "macapp/Shell/Sources/Homescreen/Security.swift"),
                               str(harness), "-o", str(binary)], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def test_build_recreates_environment_and_requires_locked_hashes(tmp_path):
    # Stop at dependency installation; no Swift build, signing, app bundle, or DMG.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    build_venv = tmp_path / "buildvenv"
    (build_venv / "bin").mkdir(parents=True)
    (build_venv / "stale-package").write_text("must not survive")
    (build_venv / "bin/pyinstaller").touch(mode=0o755)
    log = tmp_path / "commands"
    uname = fake_bin / "uname"
    uname.write_text("#!/bin/sh\nprintf 'arm64\\n'\n")
    uname.chmod(0o755)
    fake_python = fake_bin / "python3.12"
    fake_python.write_text('''#!/bin/zsh
if [[ "$1" != "-m" || "$2" != "venv" ]]; then exit 80; fi
mkdir -p "$3/bin"
cat > "$3/bin/python" <<'SCRIPT'
#!/bin/zsh
print -r -- "$*" >> "$COMMAND_LOG"
exit 79
SCRIPT
chmod +x "$3/bin/python"
''')
    fake_python.chmod(0o755)
    result = subprocess.run(["zsh", str(ROOT / "macapp/build.sh")], capture_output=True, text=True,
                            env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
                                 "HOMESCREEN_BUILD_VENV": str(build_venv), "HOMESCREEN_BUILD_PYTHON": str(fake_python),
                                 "HOMESCREEN_BUILD_ARCH": "arm64", "COMMAND_LOG": str(log)})
    assert result.returncode == 79, result.stdout + result.stderr
    install = log.read_text()
    assert "--require-hashes" in install
    assert "--only-binary=:all:" in install
    assert "requirements-build.lock" in install
