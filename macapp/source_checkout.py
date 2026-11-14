"""Export the exact tracked project inputs used for an official native build."""
import argparse
from pathlib import Path
import subprocess
from source_inputs import relative_name


def tracked_blobs(root, commit):
    records = subprocess.check_output(["git", "-C", root, "ls-tree", "-rz", "--full-tree", commit]).split(b"\0")
    for row in records:
        if not row:
            continue
        header, raw_name = row.split(b"\t", 1)
        mode, kind, object_id = header.split()
        name = relative_name(raw_name.decode())
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError("Unsupported tracked release member type")
        data = subprocess.check_output(["git", "-C", root, "cat-file", "blob", object_id])
        yield name, int(mode, 8) & 0o777, data


def export_project(root, target):
    commit = subprocess.check_output(["git", "-C", root, "rev-parse", "--verify", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "-C", root, "status", "--porcelain", "--untracked-files=all"]):
        raise ValueError("Use a clean release checkout or a local source rebuild")
    target.mkdir()
    for name, mode, data in tracked_blobs(root, commit):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
        path.chmod(mode)
    return commit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        print(export_project(args.root, args.destination))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")
