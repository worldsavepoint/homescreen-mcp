"""Retain local native build roots for release verification."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

RECORD = ".build-paths.json"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_record(folder, roots, inputs=()):
    paths = sorted({str(form) for root in roots for form in (root.absolute(), root.resolve())})
    data = {"roots": paths, "inputs": {file.relative_to(folder).as_posix(): digest(file) for file in inputs}}
    with NamedTemporaryFile("w", dir=folder, delete=False) as stream:
        json.dump(data, stream)
    Path(stream.name).replace(folder / RECORD)


def read_roots(folder, inputs=()):
    try:
        record = json.loads((folder / RECORD).read_text())
        roots = [Path(value) for value in record["roots"]]
        if not roots or any(not root.is_absolute() or root.parent == root for root in roots):
            raise ValueError
        if record["inputs"] != {file.relative_to(folder).as_posix(): digest(file) for file in inputs}:
            raise ValueError
        return roots
    except (OSError, TypeError, ValueError, KeyError):
        raise ValueError("Prepare a fresh native build to record its locations") from None


def intel_inputs(folder):
    wheel, = (folder / "wheels").glob("cryptography-*.whl")
    return folder / "requirements-build.lock", wheel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("intel-record", "intel-check", "app-record"))
    parser.add_argument("folder", type=Path)
    parser.add_argument("roots", type=Path, nargs="*")
    parser.add_argument("--intel", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "intel-check":
            read_roots(args.folder, intel_inputs(args.folder))
        elif args.action == "intel-record":
            write_record(args.folder, args.roots, intel_inputs(args.folder))
        else:
            roots = [*args.roots, Path(sys.prefix), Path(sys.base_prefix)]
            if args.intel:
                roots.extend(read_roots(args.intel, intel_inputs(args.intel)))
            write_record(args.folder, roots)
    except (OSError, ValueError):
        parser.exit(1, "Prepare a fresh native build to record its locations\n")


if __name__ == "__main__":
    main()
