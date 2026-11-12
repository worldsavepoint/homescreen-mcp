# Building the macOS app

The dependency lock targets CPython 3.12 on macOS arm64. Other Python versions,
Intel Macs and other operating systems need a separately resolved and tested
lock. The lock pins Python dependencies and verifies downloaded artifact hashes;
it does not make the Swift toolchain, SDK, signing output or DMG byte reproducible.

For development and offline device-free tests:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q tests
```

`macapp/build.sh` creates a fresh temporary virtual environment for each build,
installs only wheels from the hashed lock and the local source without dependency resolution
or build isolation, and rebuilds the Python engine. Old build environments and
`SKIP_ENGINE` are no longer used. The app bundle includes `dependencies.txt`
(the installed package inventory) and a copy of `requirements-build.lock`.
The build requires Python 3.12 and compatible Xcode command line tools.

The committed lock records the exact wheels downloaded for macOS arm64 and
CPython 3.12, including their filenames and SHA256 hashes. To deliberately update
dependencies, adjust the exact direct versions in `pyproject.toml`, then resolve
and download wheels in a separate environment on that same platform:

```sh
export LOCK_DIR=$(mktemp -d)
python3.12 -m venv "$LOCK_DIR/venv"
"$LOCK_DIR/venv/bin/python" -m pip install '.[dev,build]'
"$LOCK_DIR/venv/bin/python" -m pip check
"$LOCK_DIR/venv/bin/python" - <<'PY'
import importlib.metadata as m
import os
from pathlib import Path
pins = sorted(d.metadata["Name"] + "==" + d.version for d in m.distributions()
              if d.metadata["Name"] != "homescreen-mcp")
Path(os.environ["LOCK_DIR"], "pins.txt").write_text("\n".join(pins) + "\n")
PY
"$LOCK_DIR/venv/bin/python" -m pip download --no-deps --only-binary=:all: \
  -r "$LOCK_DIR/pins.txt" --dest "$LOCK_DIR/wheels"
"$LOCK_DIR/venv/bin/python" - <<'PY'
from email.parser import BytesParser
from hashlib import sha256
import os
from pathlib import Path
from zipfile import ZipFile
entries = []
for wheel in Path(os.environ["LOCK_DIR"], "wheels").glob("*.whl"):
    with ZipFile(wheel) as archive:
        member = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(member))
    pin = metadata["Name"] + "==" + metadata["Version"]
    entries.append((pin.lower(), "# " + wheel.name + "\n" + pin
                    + " --hash=sha256:" + sha256(wheel.read_bytes()).hexdigest()))
Path("requirements-build.lock").write_text(
    "# CPython 3.12 / macOS arm64: runtime, build and test dependencies.\n"
    + "\n".join(entry for _, entry in sorted(entries)) + "\n")
PY
```

Review all transitive version changes and verify a new clean installation with
`--require-hashes`, `pip check` and the full test suite before committing the lock.
Do not copy an old virtual environment into a release build.

## Signing status

The build script uses **ad-hoc signing only** (`codesign --sign -`). Its output is
**not Developer ID signed or notarized**. Ad-hoc signing does not establish a
trusted publisher identity or satisfy Gatekeeper's notarization checks.
Developer ID signing and Apple notarization require the publisher's valid
certificate, Apple credentials and a separate release process. This repository
does not claim those steps have occurred, and does not disable Gatekeeper.

Compiling the Swift package or running the pure request/URL validation test
harness does not launch the macOS app or contact a phone. A full `build.sh` run
creates the app bundle and DMG; it does not install the app or launch it.
