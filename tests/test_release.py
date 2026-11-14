"""Versioned release assets preserve app contents and executable permissions."""
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
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
    shutil.copyfile("/usr/bin/true", executable)
    executable.chmod(0o755)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "org.example.release-fixture",
        "CFBundleExecutable": executable.name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version.split("-")[0],
        "CFBundleVersion": version.split("-")[0],
        "HomeScreenOrganizerReleaseVersion": version,
        "HomeScreenOrganizerArchitecture": arch,
    }))
    from test_package_privacy import native_zip
    from macapp.build_paths import write_record

    native_zip(tmp_path)
    engine = app / "Contents/Resources/engine/engine"
    engine.parent.mkdir(parents=True)
    engine.write_bytes((tmp_path / "engine").read_bytes())
    write_record(build, [build])
    result = release("localize", "--app", app)
    assert result.returncode == 0, result.stderr
    make_image(app, build / f"home-screen-organizer-{version}.dmg", tmp_path / "image-files")
    return build


def make_image(app, image, folder):
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", app], check=True, capture_output=True)
    folder.mkdir(exist_ok=True)
    copy = folder / app.name
    if copy.exists():
        shutil.rmtree(copy)
    subprocess.run(["ditto", app, copy], check=True)
    if not (folder / "Applications").is_symlink():
        (folder / "Applications").symlink_to("/Applications")
    subprocess.run(["hdiutil", "create", "-quiet", "-ov", "-format", "UDZO", "-srcfolder", folder, image],
                   check=True, capture_output=True)


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
    assert (output / dmg).read_bytes() == (build / f"home-screen-organizer-{VERSION}.dmg").read_bytes()
    with zipfile.ZipFile(output / archive) as zipped:
        info = zipped.getinfo("Screen Organizer.app/Contents/MacOS/HomeScreenOrganizer")
        assert zipped.read(info) == (build / info.filename).read_bytes()
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
    for name in ("release.py", "check_package_paths.py", "build_paths.py"):
        (script.parent / name).write_bytes((SCRIPT.parent / name).read_bytes())
    (project / "pyproject.toml").write_text('[project]\nversion = "1.2.0-beta.1"\n')
    output = tmp_path / "prerelease"
    result = subprocess.run([sys.executable, str(script), "package", "--build-dir", str(build),
                             "--output-dir", str(output), "--tag", "v1.2.0-beta.1", "--arch", "arm64"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (output / "home-screen-organizer-1.2.0-beta.1-macos-arm64.dmg").read_bytes() == (build / f"home-screen-organizer-{version}.dmg").read_bytes()
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


def test_rejected_package_preserves_verified_assets(tmp_path):
    build = make_build(tmp_path)
    output = tmp_path / "release"
    args = ("package", "--arch", "arm64", "--build-dir", build, "--output-dir", output)
    dirty = build / "Screen Organizer.app/Contents/Resources/note"
    dirty.write_text(str(build / "private"))
    assert release(*args).returncode != 0
    assert not output.exists()
    dirty.unlink()
    result = release(*args)
    assert result.returncode == 0, result.stderr
    (output / "other").write_text("keep")
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    dirty.write_text(str(build / "another"))
    assert release(*args).returncode != 0
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before
    dirty.write_text("public resource")
    app = build / "Screen Organizer.app"
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", app], check=True, capture_output=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", app], check=True)
    stale = release(*args)
    assert stale.returncode != 0 and "different apps" in stale.stderr
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before
    make_image(app, build / f"home-screen-organizer-{VERSION}.dmg", tmp_path / "image-files")
    result = release(*args)
    assert result.returncode == 0, result.stderr
    assert (output / "other").read_text() == "keep"
    assert (output / "SHA256SUMS.txt").read_bytes() != before["SHA256SUMS.txt"]


def test_recreated_package_uses_original_intel_roots(tmp_path):
    from macapp.build_paths import write_record

    build = make_build(tmp_path, arch="x86_64")
    original = tmp_path / "old-temp/intel"
    prepared = tmp_path / "copied-dependencies"
    wheel = prepared / "wheels/cryptography-source.whl"
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"fixture")
    lock = prepared / "requirements-build.lock"
    lock.write_text("fixture")
    write_record(prepared, [original], (lock, wheel))
    subprocess.run([sys.executable, str(SCRIPT.with_name("build_paths.py")), "app-record",
                    str(build), str(build), "--intel", str(prepared)], check=True)
    (build / "Screen Organizer.app/Contents/Resources/note").write_text(str(original / "openssl/lib"))
    output = tmp_path / "release"
    result = release("package", "--build-dir", build, "--output-dir", output, "--arch", "x86_64")
    assert result.returncode != 0 and "build path" in result.stderr
    assert str(original) not in result.stderr and not output.exists()


@pytest.mark.parametrize("host", ["local", "self-hosted", "github-hosted"])
def test_app_record_retains_builder_account_rules(tmp_path, monkeypatch, host):
    from macapp.build_paths import read_roots
    original = tmp_path / "first-home"
    runner_temp = tmp_path / "original-runner-temp"
    monkeypatch.setenv("HOME", str(original))
    monkeypatch.setenv("GITHUB_ACTIONS", "false" if host == "local" else "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", host)
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    subprocess.run([sys.executable, str(SCRIPT.with_name("build_paths.py")), "app-record",
                    str(tmp_path), str(tmp_path / "checkout")], check=True)
    monkeypatch.setenv("HOME", str(tmp_path / "other-home"))
    roots = read_roots(tmp_path)
    assert (original in roots) == (host != "github-hosted")
    assert (runner_temp in roots) == (host != "local")


def test_replacement_preserves_permissions_and_drops_managed_prior_pair(tmp_path):
    from macapp.release import install_generation

    output = tmp_path / "assets"
    output.mkdir(mode=0o700)
    (output / "notes").write_text("private")
    subprocess.run(["chmod", "+a", "everyone allow readattr", str(output)], check=True)
    acl = subprocess.check_output(["ls", "-lde", str(output)], text=True).splitlines()[1:]
    for version in ("1.2.0-beta.1", "1.3.0"):
        staged = tmp_path / version
        staged.mkdir()
        rows = []
        for extension in ("zip", "dmg"):
            name = f"home-screen-organizer-{version}-macos-arm64.{extension}"
            data = (name + version).encode()
            (staged / name).write_bytes(data)
            rows.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
        (staged / "SHA256SUMS.txt").write_text("".join(rows))
        install_generation(staged, output, "arm64")
    assert output.stat().st_mode & 0o777 == 0o700
    assert subprocess.check_output(["ls", "-lde", str(output)], text=True).splitlines()[1:] == acl
    assert (output / "notes").read_text() == "private"
    assert sorted(p.suffix for p in output.iterdir()) == ["", ".dmg", ".txt", ".zip"]


@pytest.mark.parametrize("bad", ["../relative", "wrong-architecture", "mismatched-pair", "duplicate", "hash"])
def test_previous_manifest_establishes_owned_native_pair(tmp_path, bad):
    from macapp.release import previous_assets

    base = "home-screen-organizer-1.3.0-macos-arm64"
    rows = []
    for suffix in ("zip", "dmg"):
        name = f"{base}.{suffix}"
        (tmp_path / name).write_bytes(b"old")
        rows.append(f"{hashlib.sha256(b'old').hexdigest()}  {name}\n")
    if bad == "duplicate":
        rows[1] = rows[0]
    else:
        source, change = {"../relative": (base, "../" + base),
                          "wrong-architecture": ("arm64", "x86_64"),
                          "mismatched-pair": ("1.3.0", "1.2.0"),
                          "hash": (rows[0][:64], "0" * 64)}[bad]
        rows[0] = rows[0].replace(source, change)
    (tmp_path / "SHA256SUMS.txt").write_text("".join(rows))
    with pytest.raises(ValueError, match="manifest"):
        previous_assets(tmp_path, "arm64")
