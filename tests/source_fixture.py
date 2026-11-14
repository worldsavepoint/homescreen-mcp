import hashlib
import io
import json
import tarfile


def release_source(folder, version, commit):
    inputs = {}
    files = {"project/LICENSE": b"original fixture grant", "project/macapp/engine.spec": b"fixture build",
             "project/macapp/SOURCE.md": b"build guide", "README.md": b"build guide"}
    archives = {}
    for arch in ("arm64", "x86_64"):
        runtime = {"libpython": "a" * 64, "version": "3.12.1", "archive": "pbs/" + arch}
        for key in ("python/h11", runtime["archive"]):
            data = key.encode()
            filename = "sources/" + key.replace("/", "-") + ".tar.gz"
            files[filename] = data
            inputs[key] = {"path": filename, "sha256": hashlib.sha256(data).hexdigest(), "url": "https://example.com/source"}
        entry = {"arch": arch, "version": version, "projectCommit": commit, "owners": {"h11": {"version": "0.16.0"}},
                 "runtime": runtime, "members": [["file", "h11.py", "h11", "h11.py", "a" * 64]],
                 "notices": {"h11/LICENSE": "a" * 64}, "overlays": {}}
        name = "inventories/" + arch + ".json"
        files[name] = json.dumps(entry).encode()
        archives[arch] = {"inventory": name, "zip": hashlib.sha256((folder / f"home-screen-organizer-{version}-macos-{arch}.zip").read_bytes()).hexdigest()}
    manifest = {"version": version, "commit": commit, "architectures": archives, "inputs": inputs,
                "files": {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}}
    files["MANIFEST.json"] = json.dumps(manifest).encode()
    target = folder / f"home-screen-organizer-{version}-corresponding-source.tar.gz"
    with tarfile.open(target, "w:gz") as tar:
        for name, data in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
    return target
