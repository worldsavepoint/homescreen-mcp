# Building Home Screen Organizer

Build native apps for **Apple silicon (`arm64`)** and **Intel (`x86_64`)** on
**macOS 14 or later**, using **CPython 3.12** and Xcode command line tools. Run
commands from the repository root on a Mac matching the target architecture.
Record the Xcode, SDK and signing configuration alongside each build.

The distributed DMG and ZIP include the engine and dependencies. Choose the
archive matching the Mac's CPU; the source build tools below prepare development
and release builds.

## Development dependencies

Create a Python environment:

```sh
python3.12 -m venv .venv
```

On Apple silicon, install the committed arm64 wheel lock:

```sh
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock
```

On Intel, complete [Intel dependency preparation](#intel-dependencies), then install:

```sh
.venv/bin/python -m pip install --require-hashes --only-binary=:all: \
  --find-links "$PWD/build/dependencies/x86_64/wheels" \
  -r "$PWD/build/dependencies/x86_64/requirements-build.lock"
```

Install the project and run development checks on either architecture:

```sh
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q tests
```

## Intel dependencies

Use a native Intel Mac with Python 3.12. Install Xcode command line tools
(`clang`, `make`, `lipo` and `otool`), `curl`, Perl and `rustup`, then run:

```sh
bash macapp/prepare_intel.sh python3.12 "$PWD/build/dependencies/x86_64"
```

The helper selects Rust **1.95.0** and hash-pinned maturin **1.14.1**, verifies the
OpenSSL **4.0.3** source archive hash, and builds static OpenSSL and
**cryptography 50.0.2** for the macOS **14.0** deployment target. It verifies the
compiled wheel's architecture, deployment target and static OpenSSL linkage.
The other dependency versions match the arm64 pins.

`prepare_intel.sh PYTHON OUTPUT_DIR` creates:

- `OUTPUT_DIR/requirements-build.lock`: a complete, hashed Intel wheel lock,
  including the locally built cryptography wheel's hash.
- `OUTPUT_DIR/wheels/`: the compiled cryptography wheel used by `--find-links`.
- `OUTPUT_DIR/OPENSSL-LICENSE.txt`: the verified OpenSSL license included in the Intel app.

The committed `requirements-build-x86_64.lock` contains the Intel wheel and
build-tool pins; `requirements-cryptography-x86_64.lock` pins the cryptography
source archive and its hash. The generated lock combines these inputs with the
compiled wheel. Keep the generated lock and wheel together for installation.

## Building the app

```sh
macapp/build.sh
```

`macapp/build.sh` selects `arm64` or `x86_64` from `uname -m`. Set
`HOMESCREEN_BUILD_ARCH=arm64` or `HOMESCREEN_BUILD_ARCH=x86_64` to select the
matching native host architecture explicitly. `HOMESCREEN_BUILD_PYTHON` selects
the Python 3.12 executable.

The script creates a fresh temporary virtual environment, installs wheels from
the architecture's hashed lock, adds the local source, and rebuilds the Python
engine and Swift launcher. On Intel, it calls `prepare_intel.sh` when
`build/dependencies/x86_64/requirements-build.lock` is missing. The app bundle
includes `dependencies.txt` (the installed package inventory), the installed
`requirements-build.lock`, and the MIT license. Intel bundles also include the
cryptography source lock and `OPENSSL-LICENSE.txt`.

## Updating dependencies

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
              if d.metadata["Name"] != "home-screen-organizer")
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
Update the Intel wheel pins to the same dependency versions, retain the hashed
cryptography source pin, and rerun Intel dependency preparation and validation on
a native Intel Mac. Use a fresh virtual environment for each release build.

## Signing and build outputs

The build script applies **ad-hoc signing** (`codesign --sign -`) to the app.
For Developer ID distribution, sign with the publisher's certificate and submit
the release for Apple notarization using the publisher's Apple credentials.

The Swift package includes a request/URL validation harness. A full `build.sh` run
creates `build/<arch>/Home Screen Organizer.app` and
`build/<arch>/home-screen-organizer-<version>.dmg`, where `<arch>` is `arm64`
or `x86_64`. Install and launch the resulting app as a separate step.

## Release archives

After `macapp/build.sh`, assemble the distributable files:

```sh
python3.12 macapp/release.py package --arch "$(uname -m)"
cd "build/release/$(uname -m)"
shasum -a 256 --check SHA256SUMS.txt
```

The package command checks the bundle version and architecture, preserves executable
permissions in the ZIP, and produces the following in `build/release/<arch>/`:

- `home-screen-organizer-<version>-macos-<arch>.dmg`
- `home-screen-organizer-<version>-macos-<arch>.zip`
- `SHA256SUMS.txt` for that architecture's two archives.

Use `--arch arm64` or `--arch x86_64` to select a completed native build explicitly.
CI collects both architecture artifacts, verifies all four archive hashes, and
creates one shared `SHA256SUMS.txt` for the published release.

## Automatic releases

Pull requests and pushes to `main` run a native CI matrix:

- `macos-15` builds and validates Apple silicon (`arm64`).
- `macos-15-intel` builds and validates Intel (`x86_64`).

Each job checks the layout, draft, backup, editor and launcher modules, builds the
Mac app, starts the packaged engine, completes a packaged MCP initialization and
tool-list handshake, verifies Mach-O architectures and signatures, and checks
archive checksums. The installable Actions artifacts are
`home-screen-organizer-macos-arm64` and
`home-screen-organizer-macos-x86_64`.

To publish a new version:

1. Set `project.version` in `pyproject.toml` to a new version, such as `1.2.0`.
2. Merge the contribution into `main`.
3. After both architectures complete validation and packaging, CI creates the
   matching `v1.2.0` tag at the exact built commit and publishes both DMGs, both
   ZIPs and one shared `SHA256SUMS.txt` to GitHub Releases.

Version `1.2.0` adds Intel support as a SemVer minor release. Both architecture
builds and their complete archive pairs are required for publication.

Each project version has one published release. Increment `project.version` for
the next release; subsequent builds of an already published version retain that
release. CI resumes asset uploads and publication for an existing draft.

Pushing a matching version tag also runs the build and publication workflow.
Versions such as `1.2.0-beta.1` produce GitHub prereleases.

The app's standard macOS version fields contain the numeric release core, such as
`1.2.0`. `HomeScreenOrganizerReleaseVersion` retains the complete release version, including
the prerelease suffix; archive filenames and Git tags use this complete version.

CI uses native macOS arm64 and x86_64 runners, Python 3.12, hash-checked
dependencies and commit-pinned GitHub actions. App builds use ad-hoc signing.
The release job receives repository contents write permission to publish its assets.

Original application and packaging by Jonathan Kats, distributed under the MIT
license. This fork maintains its release workflow and compatibility changes.
