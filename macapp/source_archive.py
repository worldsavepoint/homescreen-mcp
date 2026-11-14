"""Build and verify the matching native release sources."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile

from native_sources import selected_assets
from source_inputs import (HEX, cache_directory, fetch, json_bytes, pin_name, read_locks,
                           relative_name, sha256, source_member)

ROOT = Path(__file__).resolve().parents[1]
ARCHES = ("arm64", "x86_64")
RESOURCES = "Screen Organizer.app/Contents/Resources/"
ENGINE = RESOURCES + "engine/"
LIMIT = 2 * 1024**3


def asset_name(version):
    return f"home-screen-organizer-{version}-corresponding-source.tar.gz"


def validate_inventory(data, arch, version, packages, native):
    if (not HEX.fullmatch(data.get("engine", "")) or set(data) != {"projectCommit", "engine", "version", "arch", "runtime", "owners", "members", "notices", "overlays"}
            or data["arch"] != arch or data["version"] != version
            or not re.fullmatch(r"(?:[0-9a-f]{40})?", data["projectCommit"])):
        raise ValueError("Source inputs do not match the release version and architecture")
    runtime = native["runtime"][arch]
    if data["runtime"] != {k: runtime[k] for k in ("archive", "libpython", "version")}:
        raise ValueError("Different native interpreter source")
    owners = data["owners"]
    for owner, row in owners.items():
        lock = packages.get(owner, {})
        if set(row) != {"version", "wheel"} or row["version"] != lock.get("version") or not HEX.fullmatch(row["wheel"]):
            raise ValueError("Unknown frozen component or version")
        pinned = lock["wheels"].get(arch)
        if row["wheel"] != pinned and not (arch == "x86_64" and owner == "cryptography" and not pinned):
            raise ValueError("Different native component wheel")
    seen, used = set(), set()
    for section, path, owner, source, value in data["members"]:
        relative_name(path)
        relative_name(source)
        if ((section, path) in seen or section not in ("pyz", "base", "bootstrap", "bootloader", "file", "link")
                or owner not in {*owners, "cpython", "home-screen-organizer"} or not HEX.fullmatch(value)):
            raise ValueError("Invalid frozen source member")
        seen.add((section, path))
        used.add(owner)
    if used - {"cpython", "home-screen-organizer"} != owners.keys() or not seen:
        raise ValueError("Incomplete frozen component inventory")
    for group in ("notices", "overlays"):
        for path, value in data[group].items():
            relative_name(path)
            if not HEX.fullmatch(value):
                raise ValueError("Invalid source input member digest")
    native_notices = {"native/" + item["id"] + "/" + name: digest
                      for item in selected_assets(native, arch, owners) for name, digest in item.get("notices", {}).items()}
    for name, value in native_notices.items():
        if data["notices"].get(name) != value:
            raise ValueError("Missing or changed native upstream notice")
    if any(not any(p.startswith(owner + "/") for p in data["notices"]) for owner in owners):
        raise ValueError("Missing frozen component notice")


def check_zip(source, inventory):
    """Check the signed payload against the actual freeze before binding its ZIP digest."""
    arch, version = inventory["arch"], inventory["version"]
    from mcp_bundle import engine_entries
    with zipfile.ZipFile(source) as archive:
        engine_entries(archive, arch, version)
        with archive.open(ENGINE + "engine") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != inventory["engine"]:
                raise ValueError("The frozen engine differs from its source inventory")
        files = {n[len(ENGINE + "_internal/"):] for n in archive.namelist()
                 if n.startswith(ENGINE + "_internal/") and not n.endswith("/")}
        mapped = {name for section, name, *_ in inventory["members"] if section in ("file", "link")}
        if files != mapped:
            raise ValueError("Different signed engine file inventory")
        for section, name, owner, relative, value in inventory["members"]:
            if section in ("file", "link"):
                with archive.open(ENGINE + "_internal/" + name) as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != value:
                        raise ValueError(f"Signed source inventory differs: {name}")
        expected = inventory["notices"]
        prefix = RESOURCES + "ThirdPartyLicenses/"
        notices = {n[len(prefix):] for n in archive.namelist() if n.startswith(prefix) and not n.endswith("/")}
        if notices != expected.keys():
            raise ValueError("Different signed notice inventory")
        for name, value in expected.items():
            if hashlib.sha256(archive.read(prefix + name)).hexdigest() != value:
                raise ValueError(f"Different signed notice: {name}")
        return archive.read(RESOURCES + "THIRD-PARTY-NOTICES.txt")


def native_inputs(inputs, archive, output):
    inventory = json.loads((inputs / "inventory.json").read_bytes())
    packages, native = read_locks()
    validate_inventory(inventory, inventory["arch"], inventory["version"], packages, native)
    check_zip(archive, inventory)
    with tempfile.TemporaryDirectory(dir=output.parent) as folder:
        sidecar = Path(folder) / "source-inputs.zip"
        with zipfile.ZipFile(sidecar, "w", compression=zipfile.ZIP_DEFLATED) as result:
            result.writestr("inventory.json", json_bytes(inventory))
            result.writestr("binary.sha256", sha256(archive))
            for name, value in inventory["overlays"].items():
                path = inputs / "overlays" / name
                if path.is_symlink() or sha256(path) != value:
                    raise ValueError("Different editable input overlay")
                result.write(path, "overlays/" + name)
        sidecar.replace(output)


class HashReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, amount):
        block = self.stream.read(amount)
        self.digest.update(block)
        return block


def payload_tar(output, entries, metadata):
    members = {}
    with output.open("wb") as stream, gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0, compresslevel=1) as zipped:
        with tarfile.open(fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT) as archive:
            for name, mode, source, size in entries:
                relative_name(name)
                if name in members or name == "MANIFEST.json" or mode not in (0o644, 0o755) or not 0 <= size <= LIMIT:
                    raise ValueError("Invalid public source member")
                reader = HashReader(source)
                header = tarfile.TarInfo(name)
                header.mode, header.size = mode, size
                archive.addfile(header, reader)
                members[name] = reader.digest.hexdigest()
            data = json_bytes({**metadata, "files": members})
            header = tarfile.TarInfo("MANIFEST.json")
            header.size = len(data)
            archive.addfile(header, io.BytesIO(data))


def verify_tar(path, version, commit=None, *, release=False):
    files, inventories = {}, {}
    manifest = None
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            name = relative_name(member.name)
            if (not member.isfile() or not 0 <= member.size <= LIMIT or name in files
                    or manifest is not None or len(files) >= 100000):
                raise ValueError("Invalid source archive member")
            stream = archive.extractfile(member)
            if name == "MANIFEST.json":
                if member.size > 32 * 1024**2:
                    raise ValueError("Invalid source manifest size")
                manifest = json.load(stream)
            elif release and name in ("inventories/arm64.json", "inventories/x86_64.json"):
                if member.size > 16 * 1024**2:
                    raise ValueError("Invalid native inventory size")
                data = stream.read()
                files[name] = hashlib.sha256(data).hexdigest()
                inventories[name] = json.loads(data)
            else:
                files[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    if (not manifest or manifest.get("files") != files or manifest.get("version") != version
            or not re.fullmatch(r"[0-9a-f]{40}", manifest.get("commit", ""))
            or commit is not None and manifest["commit"] != commit):
        raise ValueError("Different source archive version, commit or member digest")
    if release:
        required = {"README.md", "project/LICENSE", "project/macapp/engine.spec", "project/macapp/SOURCE.md"}
        if not required <= files.keys() or set(manifest.get("architectures", {})) != set(ARCHES):
            raise ValueError("The source archive lacks its project or architecture inputs")
        inputs = manifest.get("inputs", {})
        for item in inputs.values():
            if files.get(relative_name(item["path"])) != item["sha256"] or not item["path"].startswith("sources/"):
                raise ValueError("Missing matching component source bytes")
        for arch in ARCHES:
            record = manifest["architectures"][arch]
            name = f"inventories/{arch}.json"
            volume = inventories.get(name, {})
            if (record.get("inventory") != name or volume.get("projectCommit") != manifest["commit"]
                    or volume.get("arch") != arch or volume.get("version") != version or not volume.get("members")
                    or not volume.get("notices") or not volume.get("owners") or volume["runtime"]["archive"] not in inputs
                    or any("python/" + owner not in inputs for owner in volume["owners"])):
                raise ValueError("Source archive has an incomplete frozen inventory")
            if any(files.get(f"overlays/{arch}/" + relative_name(key)) != value
                   for key, value in volume["overlays"].items()):
                raise ValueError("Missing corresponding source overlay")
    return manifest


def project_entries(root, commit):
    records = subprocess.check_output(["git", "-C", root, "ls-tree", "-rz", "--full-tree", commit]).split(b"\0")
    for row in records:
        if not row:
            continue
        header, raw_name = row.split(b"\t", 1)
        mode, kind, object_id = header.split()
        name = relative_name(raw_name.decode())
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError("Unexpected tracked source member type")
        data = subprocess.check_output(["git", "-C", root, "cat-file", "blob", object_id])
        yield "project/" + name, int(mode, 8) & 0o777, io.BytesIO(data), len(data)


def assemble(input_dir, release, version, commit, repository, root=ROOT):
    if not re.fullmatch("[0-9a-f]{40}", commit) or subprocess.check_output(
            ["git", "-C", root, "rev-parse", "HEAD"], text=True).strip() != commit:
        raise ValueError("Build source assets from the exact release commit")
    for flag in ([], ["--cached"]):
        subprocess.run(["git", "-C", root, "diff", "--quiet", *flag, commit, "--"], check=True)
    project = tomllib.loads(subprocess.check_output(["git", "-C", root, "show", f"{commit}:pyproject.toml"], text=True))
    if project["project"]["version"] != version:
        raise ValueError("Different project source version")
    packages, native = read_locks()
    records, overlays, pins, owners_by_arch = {}, {}, {}, {}
    cache = cache_directory()
    from frozen_sources import distribution_notice
    with ExitStack() as stack:
        for arch in ARCHES:
            inputs = stack.enter_context(zipfile.ZipFile(input_dir / ("home-screen-organizer-sources-" + arch) / "source-inputs.zip"))
            folder = release / f"home-screen-organizer-{version}-macos-{arch}.zip"
            inventory = json.loads(inputs.read("inventory.json"))
            validate_inventory(inventory, arch, version, packages, native)
            if inventory['projectCommit'] != commit:
                raise ValueError('Native frozen source references a different project commit')
            binary = sha256(folder)
            if (inputs.read("binary.sha256").decode() != binary
                    or check_zip(folder, inventory) != distribution_notice(repository, version)):
                raise ValueError("Matching native source inputs required")
            records[arch] = {"zip": binary, "inventory": f"inventories/{arch}.json"}
            owners_by_arch[arch] = inventory
            expected = {"inventory.json", "binary.sha256", *("overlays/" + n for n in inventory["overlays"])}
            if set(inputs.namelist()) != expected or len(inputs.infolist()) != len(expected):
                raise ValueError("Unexpected source input sidecar members")
            for name, value in inventory["overlays"].items():
                data = inputs.read("overlays/" + name)
                if hashlib.sha256(data).hexdigest() != value:
                    raise ValueError("Different editable source overlay")
                overlays[f"overlays/{arch}/{name}"] = data
            for owner in inventory["owners"]:
                pins["python/" + owner] = packages[owner]["source"]
            for item in selected_assets(native, arch, inventory["owners"]):
                pins[item["id"]] = item
        unique = {pin["sha256"]: pin for pin in pins.values()}
        with ThreadPoolExecutor(max_workers=8) as pool:
            paths = dict(zip(unique, pool.map(lambda pin: fetch(pin, cache), unique.values())))
        blobs = {value: "sources/" + value + "-" + pin_name(pin) for value, pin in unique.items()}
        inputs = {name: {"path": blobs[pin["sha256"]], "sha256": pin["sha256"], "url": pin["url"]}
                  for name, pin in pins.items()}
        check_cargo(pins, paths, native)
        def entries():
            yield from project_entries(root, commit)
            text = (root / "macapp/SOURCE.md").read_bytes()
            yield "README.md", 0o644, io.BytesIO(text), len(text)
            for arch, inventory in sorted(owners_by_arch.items()):
                data = json_bytes(inventory)
                yield records[arch]["inventory"], 0o644, io.BytesIO(data), len(data)
            for name, data in sorted(overlays.items()):
                yield name, 0o644, io.BytesIO(data), len(data)
            for value, path in sorted(paths.items()):
                with path.open("rb") as stream:
                    yield blobs[value], 0o644, stream, path.stat().st_size
        with tempfile.TemporaryDirectory(dir=release) as temporary:
            out = Path(temporary) / asset_name(version)
            payload_tar(out, entries(), {"version": version, "commit": commit, "architectures": records, "inputs": inputs})
            verify_tar(out, version, commit, release=True)
            digest = sha256(out)
            out.replace(release / out.name)
            checksums = release / "SHA256SUMS.txt"
            previous = [line for line in checksums.read_text().splitlines() if not line.endswith("  " + out.name)]
            manifest_path = Path(temporary) / checksums.name
            manifest_path.write_text("\n".join(sorted([*previous, f"{digest}  {out.name}"], key=lambda s: s.split("  ")[1])) + "\n")
            manifest_path.replace(checksums)


def check_cargo(pins, paths, native):
    for owner, recipe in native["cargo"].items():
        if "python/" + owner not in pins:
            continue
        pin = pins["python/" + owner]
        lock = source_member(paths[pin["sha256"]], recipe["path"])
        if hashlib.sha256(lock).hexdigest() != recipe["sha256"]:
            raise ValueError("Different Cargo build inputs")
        for item in tomllib.loads(lock.decode())["package"]:
            if item.get("source"):
                source = pins.get("crate/" + item["name"] + "@" + item["version"], {})
                if source.get("sha256") != item.get("checksum") or not source:
                    raise ValueError("Missing locked Cargo source")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    stage = sub.add_parser("native")
    for arg in ("inputs", "archive", "output"):
        stage.add_argument("--" + arg, type=Path, required=True)
    build = sub.add_parser("assemble")
    for arg in ("inputs", "release"):
        build.add_argument("--" + arg, type=Path, required=True)
    for arg in ("version", "commit", "repository"):
        build.add_argument("--" + arg, required=True)
    args = parser.parse_args()
    try:
        if args.action == "native":
            native_inputs(args.inputs, args.archive, args.output)
        else:
            assemble(args.inputs, args.release, args.version, args.commit, args.repository)
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError, zipfile.BadZipFile) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
