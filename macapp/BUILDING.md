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

## Release archives

After `macapp/build.sh`, assemble the distributable files:

```sh
python3.12 macapp/release.py package
cd build/release
shasum -a 256 --check SHA256SUMS.txt
```

The package command checks the bundle version, preserves executable permissions in
the ZIP, and produces `Homescreen-<version>-macos-arm64.dmg`,
`Homescreen-<version>-macos-arm64.zip` and `SHA256SUMS.txt`.

## Tagged releases

Pull requests and pushes to `main` run layout, draft, backup, editor and launcher
checks, build the Mac app, verify its signature and engine startup, then upload
installable archives as the `homescreen-macos-arm64` Actions artifact.

To publish a release after merging the contribution:

1. Set `project.version` in `pyproject.toml` to the release version and merge it.
2. Check the matching tag locally, then push it:

   ```sh
   python3.12 macapp/release.py version --tag v1.1.1
   git tag v1.1.1
   git push origin v1.1.1
   ```

3. The tag workflow builds the app, verifies its archives, and publishes the DMG,
   ZIP and checksums to GitHub Releases. Tags match the project version exactly.
   Versions such as `1.2.0-beta.1` produce GitHub prereleases.

The app's standard macOS version fields contain the numeric release core, such as
`1.2.0`. `HomescreenReleaseVersion` retains the complete release version, including
the prerelease suffix; archive filenames and Git tags use this complete version.

CI uses macOS arm64, Python 3.12, hash-checked dependencies and commit-pinned
GitHub actions. App builds use ad-hoc signing. The release job receives repository
contents write permission to publish its assets.

Original application and packaging by Jonathan Kats, distributed under the MIT
license. This fork maintains its release workflow and compatibility changes.
