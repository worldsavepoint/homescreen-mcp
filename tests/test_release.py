"""Versioned release assets preserve app contents and executable permissions."""
import hashlib
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


def make_build(tmp_path, version=VERSION):
    build = tmp_path / "build with spaces"
    app = build / "iOS Home Screen Organizer.app"
    executable = app / "Contents/MacOS/iOSHomeScreenOrganizer"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleShortVersionString": version.split("-")[0],
        "CFBundleVersion": version.split("-")[0],
        "IOSHomeScreenOrganizerReleaseVersion": version,
    }))
    (build / f"ios-homescreen-organizer-{version}.dmg").write_bytes(b"fixture disk image\n")
    return build


def test_release_archives_and_manifest(tmp_path):
    build = make_build(tmp_path)
    output = tmp_path / "release assets"
    result = release("package", "--build-dir", build, "--output-dir", output,
                     "--tag", f"v{VERSION}")
    assert result.returncode == 0, result.stderr
    dmg = f"ios-homescreen-organizer-{VERSION}-macos-arm64.dmg"
    archive = f"ios-homescreen-organizer-{VERSION}-macos-arm64.zip"
    assert sorted(p.name for p in output.iterdir()) == sorted([dmg, archive, "SHA256SUMS.txt"])
    assert (output / dmg).read_bytes() == b"fixture disk image\n"
    with zipfile.ZipFile(output / archive) as zipped:
        info = zipped.getinfo("iOS Home Screen Organizer.app/Contents/MacOS/iOSHomeScreenOrganizer")
        assert zipped.read(info) == b"#!/bin/sh\nexit 0\n"
        assert (info.external_attr >> 16) & 0o111
    lines = (output / "SHA256SUMS.txt").read_text().splitlines()
    assert len(lines) == 2
    for line, name in zip(lines, [dmg, archive]):
        checksum, filename = line.split("  ")
        assert filename == name
        assert checksum == hashlib.sha256((output / name).read_bytes()).hexdigest()


def test_bundle_version_mismatch_stops_packaging(tmp_path):
    build = make_build(tmp_path, version="0.0.0")
    output = tmp_path / "release"
    result = release("package", "--build-dir", build, "--output-dir", output)
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
                             "--output-dir", str(output), "--tag", "v1.2.0-beta.1"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (output / "ios-homescreen-organizer-1.2.0-beta.1-macos-arm64.dmg").read_bytes() == b"fixture disk image\n"
    assert (output / "ios-homescreen-organizer-1.2.0-beta.1-macos-arm64.zip").is_file()
