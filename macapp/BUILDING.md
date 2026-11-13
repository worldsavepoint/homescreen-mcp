# Building the macOS app

The dependency lock targets CPython 3.12 on macOS arm64. Resolve and validate a
platform-specific lock for another Python version or architecture. The lock pins
Python dependencies and verifies downloaded artifact hashes. Record the Xcode,
SDK and signing configuration alongside each build.

For development and fixture checks:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q tests
```

`macapp/build.sh` creates a fresh temporary virtual environment for each build,
installs wheels from the hashed lock, adds the local source with the resolved
dependencies, and rebuilds the Python engine. The app bundle includes `dependencies.txt`
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
Use a fresh virtual environment for each release build.

## Signing and build outputs

The build script applies **ad-hoc signing** (`codesign --sign -`) to the app.
For Developer ID distribution, sign with the publisher's certificate and submit
the release for Apple notarization using the publisher's Apple credentials.

The Swift package includes a request/URL validation harness. A full `build.sh` run
creates the app bundle and DMG in `build/`. Install and launch the resulting app
as a separate step.
