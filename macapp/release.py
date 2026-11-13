"""Assemble versioned macOS release assets from a completed app build."""
import argparse
import hashlib
from pathlib import Path
import plistlib
import platform
import re
import shutil
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURES = ("arm64", "x86_64")


def project_version(tag=None):
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(alpha|beta|rc)\.(0|[1-9]\d*))?", version):
        raise ValueError("Set the project version to a SemVer release or alpha/beta/rc version")
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"Release tag must match project version: v{version}")
    return version


def package(build_dir, output_dir, version, arch):
    app = build_dir / "iOS Home Screen Organizer.app"
    bundle = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if (bundle.get("IOSHomeScreenOrganizerReleaseVersion", bundle["CFBundleShortVersionString"]) != version
            or bundle["CFBundleShortVersionString"] != version.split("-")[0]):
        raise ValueError("Build the app with the current project version; bundle version differs")
    if bundle.get("IOSHomeScreenOrganizerArchitecture") != arch:
        raise ValueError("Build the app for the selected architecture")
    dmg = build_dir / f"ios-homescreen-organizer-{version}.dmg"
    if not dmg.is_file():
        raise ValueError(f"Build the disk image first: {dmg.name}")
    output_dir.mkdir(parents=True, exist_ok=True)
    disk_image = output_dir / f"ios-homescreen-organizer-{version}-macos-{arch}.dmg"
    archive = output_dir / f"ios-homescreen-organizer-{version}-macos-{arch}.zip"
    shutil.copyfile(dmg, disk_image)
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                    str(app), str(archive)], check=True)
    lines = []
    for asset in (disk_image, archive):
        with asset.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        lines.append(f"{digest}  {asset.name}\n")
    (output_dir / "SHA256SUMS.txt").write_text("".join(lines))


def collect(input_dir, output_dir, version):
    verified = []
    for arch in ARCHITECTURES:
        folder = input_dir / f"ios-homescreen-organizer-macos-{arch}"
        expected = {f"ios-homescreen-organizer-{version}-macos-{arch}.{extension}"
                    for extension in ("dmg", "zip")}
        seen = set()
        for line in (folder / "SHA256SUMS.txt").read_text().splitlines():
            digest, name = line.split("  ")
            if name not in expected or name in seen or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"Check the {arch} release manifest")
            asset = folder / name
            with asset.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != digest:
                raise ValueError(f"Archive checksum differs: {name}")
            seen.add(name)
            verified.append((asset, digest))
        if seen != expected:
            raise ValueError(f"Supply both {arch} release archives")
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for asset, digest in sorted(verified):
        shutil.copyfile(asset, output_dir / asset.name)
        lines.append(f"{digest}  {asset.name}\n")
    (output_dir / "SHA256SUMS.txt").write_text("".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    version_command = commands.add_parser("version", help="Check the project version and release tag")
    version_command.add_argument("--tag")
    package_command = commands.add_parser("package", help="Create DMG, ZIP and SHA256 assets")
    package_command.add_argument("--tag")
    package_command.add_argument("--arch", choices=ARCHITECTURES, default=platform.machine())
    package_command.add_argument("--build-dir", type=Path)
    package_command.add_argument("--output-dir", type=Path)
    collect_command = commands.add_parser("collect", help="Verify and combine both architecture builds")
    collect_command.add_argument("--tag")
    collect_command.add_argument("--input-dir", type=Path, required=True)
    collect_command.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        version = project_version(args.tag)
        if args.command == "package":
            build_dir = args.build_dir or ROOT / "build" / args.arch
            output_dir = args.output_dir or ROOT / "build/release" / args.arch
            package(build_dir.resolve(), output_dir.resolve(), version, args.arch)
        elif args.command == "collect":
            collect(args.input_dir.resolve(), args.output_dir.resolve(), version)
        print(version)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
