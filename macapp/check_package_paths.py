"""Check a trusted native release ZIP for local build paths."""
import argparse
import io
import os
from pathlib import Path
import sysconfig
import tempfile
import zipfile

from PyInstaller.archive.readers import CArchiveReader

ENGINE = "Screen Organizer.app/Contents/Resources/engine/engine"


def check_archive(path, blocked):
    prefixes = {os.fsencode(form) for root in blocked
                for form in (root.absolute(), root.resolve())}

    def check(data):
        if any(prefix in data for prefix in prefixes):
            raise ValueError("Release payload contains a local build path")

    def check_zip(archive):
        for entry in archive.infolist():
            check(entry.filename.encode())
            data = archive.read(entry)
            check(data)
            if entry.filename.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data)) as nested:
                    check_zip(nested)

    module = sysconfig._get_sysconfigdata_name()
    found_module = False
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as folder:
        check_zip(archive)
        engine = Path(folder) / "engine"
        engine.write_bytes(archive.read(ENGINE))
        package = CArchiveReader(str(engine))
        for option in package.options:
            check(option.encode())
        for name, entry in package.toc.items():
            check(name.encode())
            data = package.extract(name)
            check(data)
            if entry[-1] == "z":
                pyz = package.open_embedded_archive(name)
                for member in pyz.toc:
                    check(member.encode())
                    check(pyz.extract(member, raw=True) or b"")
                if module in pyz.toc:
                    if pyz.extract(module).co_filename != module + ".py":
                        raise ValueError("Check the packaged sysconfig module filename")
                    found_module = True
            elif name.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data)) as nested:
                    check_zip(nested)
    if not found_module:
        raise ValueError("Include the active sysconfig module in the packaged engine")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("build_roots", type=Path, nargs="+")
    args = parser.parse_args()
    roots = args.build_roots
    if os.environ.get("GITHUB_ACTIONS") == "true":
        if temp := os.environ.get("RUNNER_TEMP"):
            roots.append(Path(temp))
    else:
        roots.append(Path.home())
    try:
        check_archive(args.archive, roots)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    print("Native archive build-path check passed")


if __name__ == "__main__":
    main()
