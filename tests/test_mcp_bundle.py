"""Standalone MCP bundles retain verified native engines and release metadata."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import sys
import tomllib
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "macapp/mcp_bundle.py"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
BUNDLE = f"home-screen-organizer-{VERSION}-macos.mcpb"
RESOURCES = "Screen Organizer.app/Contents/Resources/"
ENGINE = b'#!/bin/sh\nprintf \'%s\\n\' "$HOMESCREEN_READ_ONLY" "$@"\n'


def member(archive, name, data, mode=stat.S_IFREG | 0o644):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = mode << 16
    archive.writestr(info, data)


def assets(tmp_path, extra=None):
    folder = tmp_path / "verified assets"
    folder.mkdir()
    for arch in ("arm64", "x86_64"):
        prefix = f"home-screen-organizer-{VERSION}-macos-{arch}"
        (folder / f"{prefix}.dmg").write_bytes(b"disk fixture")
        with zipfile.ZipFile(folder / f"{prefix}.zip", "w") as archive:
            member(archive, "Screen Organizer.app/Contents/Info.plist", plistlib.dumps({
                "CFBundleShortVersionString": VERSION, "HomeScreenOrganizerReleaseVersion": VERSION,
                "HomeScreenOrganizerArchitecture": arch}))
            member(archive, RESOURCES + "engine/engine", ENGINE, stat.S_IFREG | 0o755)
            member(archive, RESOURCES + "engine/_internal/libsigned.dylib", b"signed native bytes\x00" + arch.encode(), stat.S_IFREG | 0o755)
            member(archive, RESOURCES + "engine/_internal/current", b"libsigned.dylib", stat.S_IFLNK | 0o777)
            member(archive, RESOURCES + "engine/_internal/example.dist-info/licenses/LICENSE", b"third party notice")
            for name in ("LICENSE", "dependencies.txt", "requirements-build.lock", "THIRD-PARTY-NOTICES.txt", "SourceInventory.json",
                         "ThirdPartyLicenses/components.json", "ThirdPartyLicenses/h11/LICENSE.txt"):
                member(archive, RESOURCES + name, b"notice " + name.encode())
            if arch == "x86_64":
                for name in ("OPENSSL-LICENSE.txt", "requirements-cryptography-x86_64.lock"):
                    member(archive, RESOURCES + name, b"Intel notice")
            for catalog in (ROOT / "homescreen/web/locales").glob("*.json"):
                member(archive, RESOURCES + "engine/_internal/homescreen/web/locales/" + catalog.name, catalog.read_bytes())
            if extra:
                extra(archive, arch)
    checksum(folder)
    return folder


def checksum(folder):
    (folder / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted(folder.iterdir()) if path.suffix in (".zip", ".dmg")))


def assemble(folder, output):
    return subprocess.run([sys.executable, str(SCRIPT), "--assets-dir", str(folder),
                           "--output-dir", str(output), "--repository", "worldsavepoint/ios-homescreen-organizer"],
                          capture_output=True, text=True)


def test_bundle_contains_both_signed_engines_modes_symlinks_and_notices(tmp_path):
    folder = assets(tmp_path)
    output = tmp_path / "distribution"
    result = assemble(folder, output)
    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(output / BUNDLE) as archive:
        for arch in ("arm64", "x86_64"):
            prefix = f"server/{arch}/"
            assert archive.read(prefix + "engine") == ENGINE
            info = archive.getinfo(prefix + "_internal/libsigned.dylib")
            assert archive.read(info) == b"signed native bytes\x00" + arch.encode()
            assert stat.S_IMODE(info.external_attr >> 16) == 0o755
            link = archive.getinfo(prefix + "_internal/current")
            assert stat.S_ISLNK(link.external_attr >> 16)
            assert archive.read(link) == b"libsigned.dylib"
            assert archive.read(prefix + "_internal/example.dist-info/licenses/LICENSE") == b"third party notice"
            assert archive.read(f"licenses/{arch}/LICENSE") == b"notice LICENSE"
            assert archive.read(f"licenses/{arch}/dependencies.txt") == b"notice dependencies.txt"
            for catalog in (ROOT / "homescreen/web/locales").glob("*.json"):
                assert archive.read(prefix + "_internal/homescreen/web/locales/" + catalog.name) == catalog.read_bytes()
        assert archive.read("licenses/x86_64/OPENSSL-LICENSE.txt") == b"Intel notice"
        assert archive.read("THIRD-PARTY-NOTICES.txt") == b"notice THIRD-PARTY-NOTICES.txt"
        assert archive.read("licenses/arm64/ThirdPartyLicenses/h11/LICENSE.txt") == b"notice ThirdPartyLicenses/h11/LICENSE.txt"
        assert archive.read("LICENSE") == (ROOT / "LICENSE").read_bytes()
        assert stat.S_IMODE(archive.getinfo("server/launch.sh").external_attr >> 16) == 0o755
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["license"] == "GPL-3.0-or-later"
    assert manifest["manifest_version"] == "0.3"
    assert manifest["version"] == VERSION
    assert manifest["name"] == "home-screen-organizer"
    assert manifest["display_name"] == "Screen Organizer"
    assert manifest["author"]["name"] == "Jonathan Kats"
    assert manifest["server"] == {"type": "binary", "entry_point": "server/launch.sh", "mcp_config": {
        "command": "/bin/sh", "args": ["${__dirname}/server/launch.sh"], "env": {"HOMESCREEN_READ_ONLY": "1"}}}
    assert manifest["compatibility"]["platforms"] == ["darwin"]
    server = json.loads((output / "server.json").read_text())
    assert server["$schema"] == "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    assert server["name"] == "io.github.worldsavepoint/home-screen-organizer"
    assert server["version"] == VERSION
    assert server["title"] == "Screen Organizer"
    assert server["packages"] == [{"registryType": "mcpb", "identifier":
        f"https://github.com/worldsavepoint/ios-homescreen-organizer/releases/download/v{VERSION}/{BUNDLE}",
        "fileSha256": hashlib.sha256((output / BUNDLE).read_bytes()).hexdigest(), "transport": {"type": "stdio"}}]
    lines = (output / "SHA256SUMS.txt").read_text().splitlines()
    assert len(lines) == 6
    for line in lines:
        digest, name = line.split("  ")
        path = output / name if (output / name).exists() else folder / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_extracted_launcher_selects_native_engine_and_preserves_arguments(tmp_path):
    folder = assets(tmp_path)
    output = tmp_path / "bundle with spaces"
    result = assemble(folder, output)
    assert result.returncode == 0, result.stderr
    extracted = tmp_path / "extracted with spaces"
    subprocess.run(["ditto", "-x", "-k", str(output / BUNDLE), str(extracted)], check=True)
    for setting, expected in ((None, "1"), ("0", "0"), ("", "")):
        env = {**os.environ, "HOMESCREEN_DATA": str(tmp_path / "empty data")}
        env.pop("HOMESCREEN_READ_ONLY", None)
        if setting is not None:
            env["HOMESCREEN_READ_ONLY"] = setting
        proc = subprocess.run(["/bin/sh", str(extracted / "server/launch.sh"), "argument with spaces", "a;literal"],
                              env=env, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.splitlines() == [expected, "mcp", "argument with spaces", "a;literal"]


@pytest.mark.parametrize("damage", ["changed", "missing", "missing-manifest-entry", "extra-manifest-entry"])
def test_invalid_release_checksums_fail_before_output(tmp_path, damage):
    folder = assets(tmp_path)
    path = next(folder.glob("*arm64.zip"))
    if damage == "changed":
        path.write_bytes(b"changed")
    elif damage == "missing":
        path.unlink()
    elif damage == "missing-manifest-entry":
        manifest = folder / "SHA256SUMS.txt"
        manifest.write_text("\n".join(manifest.read_text().splitlines()[1:]) + "\n")
    else:
        with (folder / "SHA256SUMS.txt").open("a") as stream:
            stream.write("a" * 64 + "  extra.zip\n")
    output = tmp_path / "distribution"
    result = assemble(folder, output)
    assert result.returncode != 0
    assert not output.exists()


@pytest.mark.parametrize("path,target,mode", [
    (RESOURCES + "engine/../escape", b"bad", stat.S_IFREG | 0o644),
    ("/absolute", b"bad", stat.S_IFREG | 0o644),
    (RESOURCES + "engine/_internal/escape", b"../../../../outside", stat.S_IFLNK | 0o777),
    (RESOURCES + "engine/_internal/escape", b"/tmp/outside", stat.S_IFLNK | 0o777),
    (RESOURCES + "engine/_internal/pipe", b"", stat.S_IFIFO | 0o644),
    (RESOURCES + "engine/_internal/current/child", b"bad", stat.S_IFREG | 0o644),
])
def test_unsafe_zip_entries_fail_before_output(tmp_path, path, target, mode):
    folder = assets(tmp_path, lambda archive, arch: member(archive, path, target, mode))
    output = tmp_path / "distribution"
    result = assemble(folder, output)
    assert result.returncode != 0
    assert not output.exists()


def test_mismatched_app_version_fails_before_output(tmp_path):
    folder = assets(tmp_path, lambda archive, arch: None)
    # Rewrite one plist without duplicate ZIP members.
    path = next(folder.glob("*arm64.zip"))
    with zipfile.ZipFile(path) as archive:
        entries = [(info, archive.read(info)) for info in archive.infolist()]
    with zipfile.ZipFile(path, "w") as archive:
        for info, data in entries:
            if info.filename.endswith("Info.plist"):
                data = plistlib.dumps({"CFBundleShortVersionString": "9.0.0", "HomeScreenOrganizerArchitecture": "arm64"})
            archive.writestr(info, data)
    checksum(folder)
    output = tmp_path / "distribution"
    result = assemble(folder, output)
    assert result.returncode != 0
    assert not output.exists()


def test_framework_symlink_chain_is_preserved(tmp_path):
    def framework(archive, arch):
        prefix = RESOURCES + "engine/_internal/Example.framework/"
        member(archive, prefix + "Versions/3.12/library", b"signed framework")
        member(archive, prefix + "Versions/Current", b"3.12", stat.S_IFLNK | 0o777)
        member(archive, prefix + "library", b"Versions/Current/library", stat.S_IFLNK | 0o777)
    folder = assets(tmp_path, framework)
    result = assemble(folder, tmp_path / "distribution")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("target", [b"missing", b"cycle"])
def test_dangling_or_cyclic_symlink_fails_before_output(tmp_path, target):
    folder = assets(tmp_path, lambda archive, arch: member(
        archive, RESOURCES + "engine/_internal/cycle", target, stat.S_IFLNK | 0o777))
    output = tmp_path / "distribution"
    result = assemble(folder, output)
    assert result.returncode != 0
    assert not output.exists()


def test_publish_checks_mcpb_members_against_signed_native_zips(tmp_path):
    sys.path.insert(0, str(ROOT / "macapp"))
    from mcp_bundle import verify_bundle
    folder = assets(tmp_path)
    output = tmp_path / "dist"
    assert assemble(folder, output).returncode == 0
    bundle = output / BUNDLE
    verify_bundle(bundle, folder, VERSION, "worldsavepoint/ios-homescreen-organizer",
                  (ROOT / "LICENSE").read_bytes(), (ROOT / "macapp/mcp_launcher.sh").read_bytes())
    with zipfile.ZipFile(bundle, "a") as modified:
        modified.writestr("server/arm64/unexpected.py", b"unexpected")
    with pytest.raises(ValueError, match="bundle"):
        verify_bundle(bundle, folder, VERSION, "worldsavepoint/ios-homescreen-organizer",
                      (ROOT / "LICENSE").read_bytes(), (ROOT / "macapp/mcp_launcher.sh").read_bytes())
