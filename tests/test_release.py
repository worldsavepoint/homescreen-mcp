"""Versioned release assets preserve app contents and executable permissions."""
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tomllib
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "macapp/release.py"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def release(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True)


def test_matching_version_tag():
    result = release("version", "--tag", f"v{VERSION}")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == VERSION


@pytest.mark.parametrize("tag", ["v99.0.0", "v1.1.1/extra", "1.1.1"])
def test_tag_mismatch_stops_packaging(tag):
    result = release("version", "--tag", tag)
    assert result.returncode != 0
    assert "tag" in result.stderr.lower()


def make_build(tmp_path, version=VERSION, arch="arm64"):
    build = tmp_path / "build with spaces"
    app = build / "Screen Organizer.app"
    executable = app / "Contents/MacOS/HomeScreenOrganizer"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleShortVersionString": version.split("-")[0],
        "CFBundleVersion": version.split("-")[0],
        "HomeScreenOrganizerReleaseVersion": version,
        "HomeScreenOrganizerArchitecture": arch,
    }))
    (build / f"home-screen-organizer-{version}.dmg").write_bytes(b"fixture disk image\n")
    result = release("localize", "--app", app)
    assert result.returncode == 0, result.stderr
    return build


@pytest.mark.parametrize("arch", ["arm64", "x86_64"])
def test_release_archives_and_manifest(tmp_path, arch):
    build = make_build(tmp_path, arch=arch)
    output = tmp_path / "release assets"
    result = release("package", "--build-dir", build, "--output-dir", output,
                     "--tag", f"v{VERSION}", "--arch", arch)
    assert result.returncode == 0, result.stderr
    dmg = f"home-screen-organizer-{VERSION}-macos-{arch}.dmg"
    archive = f"home-screen-organizer-{VERSION}-macos-{arch}.zip"
    assert sorted(p.name for p in output.iterdir()) == sorted([dmg, archive, "SHA256SUMS.txt"])
    assert (output / dmg).read_bytes() == b"fixture disk image\n"
    with zipfile.ZipFile(output / archive) as zipped:
        info = zipped.getinfo("Screen Organizer.app/Contents/MacOS/HomeScreenOrganizer")
        assert zipped.read(info) == b"#!/bin/sh\nexit 0\n"
        assert (info.external_attr >> 16) & 0o111
        source = ROOT / "homescreen/web/locales"
        manifest = json.loads((source / "manifest.json").read_text())
        resources = "Screen Organizer.app/Contents/Resources/"
        for language in manifest["languages"]:
            code = language["code"]
            assert zipped.read(resources + f"Localization/{code}.json") == (source / f"{code}.json").read_bytes()
            strings = plistlib.loads(zipped.read(resources + f"{code}.lproj/InfoPlist.strings"))
            assert strings["CFBundleDisplayName"] == json.loads((source / f"{code}.json").read_text())["app.name"]
    lines = (output / "SHA256SUMS.txt").read_text().splitlines()
    assert len(lines) == 2
    for line, name in zip(lines, [dmg, archive]):
        checksum, filename = line.split("  ")
        assert filename == name
        assert checksum == hashlib.sha256((output / name).read_bytes()).hexdigest()


def test_bundle_version_mismatch_stops_packaging(tmp_path):
    build = make_build(tmp_path, version="0.0.0")
    output = tmp_path / "release"
    result = release("package", "--build-dir", build, "--output-dir", output, "--arch", "arm64")
    assert result.returncode != 0
    assert "bundle version" in result.stderr.lower()
    assert not output.exists()


def test_prerelease_keeps_tag_version_with_numeric_bundle_version(tmp_path):
    version = "1.2.0-beta.1"
    build = make_build(tmp_path, version=version)
    project = tmp_path / "project"
    script = project / "macapp/release.py"
    script.parent.mkdir(parents=True)
    script.write_bytes(SCRIPT.read_bytes())
    (project / "pyproject.toml").write_text('[project]\nversion = "1.2.0-beta.1"\n')
    output = tmp_path / "prerelease"
    result = subprocess.run([sys.executable, str(script), "package", "--build-dir", str(build),
                             "--output-dir", str(output), "--tag", "v1.2.0-beta.1", "--arch", "arm64"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (output / "home-screen-organizer-1.2.0-beta.1-macos-arm64.dmg").read_bytes() == b"fixture disk image\n"
    assert (output / "home-screen-organizer-1.2.0-beta.1-macos-arm64.zip").is_file()


def test_architecture_label_matches_bundle(tmp_path):
    build = make_build(tmp_path, arch="arm64")
    result = release("package", "--build-dir", build, "--output-dir", tmp_path / "release",
                     "--arch", "x86_64")
    assert result.returncode != 0
    assert "architecture" in result.stderr.lower()


def artifact_set(tmp_path):
    incoming = tmp_path / "incoming"
    for arch in ("arm64", "x86_64"):
        folder = incoming / f"home-screen-organizer-macos-{arch}"
        folder.mkdir(parents=True)
        lines = []
        for extension in ("dmg", "zip"):
            name = f"home-screen-organizer-{VERSION}-macos-{arch}.{extension}"
            data = f"{arch} {extension}".encode()
            (folder / name).write_bytes(data)
            lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
        (folder / "SHA256SUMS.txt").write_text("".join(lines))
    return incoming


def test_collect_combines_verified_architectures(tmp_path):
    incoming = artifact_set(tmp_path)
    output = tmp_path / "release"
    result = release("collect", "--input-dir", incoming, "--output-dir", output)
    assert result.returncode == 0, result.stderr
    assert len(list(output.iterdir())) == 5
    lines = (output / "SHA256SUMS.txt").read_text().splitlines()
    assert len(lines) == 4
    for line in lines:
        digest, name = line.split("  ")
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest


def test_collect_requires_both_architectures(tmp_path):
    incoming = artifact_set(tmp_path)
    (incoming / "home-screen-organizer-macos-x86_64/SHA256SUMS.txt").unlink()
    output = tmp_path / "release"
    result = release("collect", "--input-dir", incoming, "--output-dir", output)
    assert result.returncode != 0
    assert not output.exists()


def test_collect_checks_each_archive_before_copying(tmp_path):
    incoming = artifact_set(tmp_path)
    archive = next((incoming / "home-screen-organizer-macos-x86_64").glob("*.zip"))
    archive.write_bytes(b"changed archive")
    output = tmp_path / "release"
    result = release("collect", "--input-dir", incoming, "--output-dir", output)
    assert result.returncode != 0
    assert not output.exists()


def distribution(tmp_path):
    import json
    incoming = artifact_set(tmp_path)
    output = tmp_path / "release"
    result = release("collect", "--input-dir", incoming, "--output-dir", output)
    assert result.returncode == 0, result.stderr
    bundle = output / f"home-screen-organizer-{VERSION}-macos.mcpb"
    bundle.write_bytes(b"bundle fixture")
    metadata = {"name": "io.github.worldsavepoint/home-screen-organizer", "version": VERSION, "packages": [{
        "registryType": "mcpb", "identifier": f"https://github.com/example/project/releases/download/v{VERSION}/{bundle.name}",
        "fileSha256": hashlib.sha256(bundle.read_bytes()).hexdigest(), "transport": {"type": "stdio"}}]}
    (output / "server.json").write_text(json.dumps(metadata))
    refresh_distribution_checksums(output)
    return output


def refresh_distribution_checksums(output):
    (output / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted(output.iterdir()) if path.name != "SHA256SUMS.txt"))


def test_verify_distribution_checks_all_assets_and_package_metadata(tmp_path):
    output = distribution(tmp_path)
    result = release("verify", "--input-dir", output, "--repository", "example/project", "--tag", f"v{VERSION}")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("damage", ["missing-checksum", "duplicate-checksum", "hash", "url", "version", "name"])
def test_verify_rejects_incomplete_checksums_and_mismatched_registry_metadata(tmp_path, damage):
    import json
    output = distribution(tmp_path)
    if damage in ("missing-checksum", "duplicate-checksum"):
        manifest = output / "SHA256SUMS.txt"
        lines = manifest.read_text().splitlines()
        manifest.write_text("\n".join(lines[1:] if damage == "missing-checksum" else lines + [lines[0]]) + "\n")
    else:
        metadata_path = output / "server.json"
        metadata = json.loads(metadata_path.read_text())
        if damage == "hash":
            metadata["packages"][0]["fileSha256"] = "f" * 64
        elif damage == "url":
            metadata["packages"][0]["identifier"] = "https://example.com/other.mcpb"
        else:
            metadata[damage] = "different"
        metadata_path.write_text(json.dumps(metadata))
        refresh_distribution_checksums(output)
    result = release("verify", "--input-dir", output, "--repository", "example/project", "--tag", f"v{VERSION}")
    assert result.returncode != 0
