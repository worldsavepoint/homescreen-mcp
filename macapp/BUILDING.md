# Building Home Screen Organizer

[README](../README.md) · [中文 README](../README.zh-CN.md) · [MCP client setup](../docs/MCP.md) · [Protocol and data sources](../docs/HOW-IT-WORKS.md)

Build native apps for **Apple silicon (`arm64`)** and **Intel (`x86_64`)** on
**macOS 14 or later**, using **CPython 3.12** and Xcode command line tools. Run
commands from the repository root on a Mac matching the target architecture.
Record the Xcode, SDK and signing configuration alongside each build.

The distributed DMG and ZIP include the engine and dependencies. Choose the
archive matching the Mac's CPU; the source build tools below prepare development
and release builds.

## Source installation

Clone the repository and create a Python environment. The checkout directory keeps
the repository name:

```sh
git clone https://github.com/worldsavepoint/ios-homescreen-organizer.git
cd ios-homescreen-organizer
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

### Run from source

Start the browser editor with device writes disabled:

```sh
HOMESCREEN_READ_ONLY=1 .venv/bin/home-screen-organizer ui
```

Run `.venv/bin/home-screen-organizer --help` for `read`, `show`, `diff`, `preview`,
`apply`, `backups`, `restore`, `diagnose`, `probe` and `ui`. For a normal app/CLI
session, omit `HOMESCREEN_READ_ONLY=1`; review the draft before writing. Prepare
[hidden pages and gaps](../docs/HOW-IT-WORKS.md#layout-writes) before Apply.

The primary executables are `home-screen-organizer` and `home-screen-mcp`.
`ios-homescreen-organizer`, `ios-homescreen-mcp`, `homescreen` and `homescreen-mcp`
remain available. The package’s Python module stays `homescreen`; the MCP server
ID and data directory stay `ios-homescreen-mcp` and `homescreen-mcp` respectively.
For client settings, see the [English](../docs/MCP.md) or
[Chinese MCP guide](../docs/MCP.zh-CN.md). For fixtures and simulator development,
see [development sources](../docs/HOW-IT-WORKS.md#development-sources).

Package metadata permits Python 3.11+, while the documented source and release
builds use Python 3.12 with architecture-specific, hash-checked dependencies.

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

The build script applies **ad-hoc signing** (`codesign --sign -`) to the app and
native engine. The standalone MCPB preserves the native signatures and is unsigned
as an outer archive. Release checksums cover the complete downloaded files.

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
creates one shared `SHA256SUMS.txt` for the published release. The assembly job
then adds the standalone MCPB and Registry metadata to that manifest.

## Standalone MCP bundle

For end-user installation and per-client stdio configuration, see the
[MCP setup guide](../docs/MCP.md#standalone-mcpb).

The standalone `home-screen-organizer-<version>-macos.mcpb` contains both native
engines, their bundled dependencies, the MIT license and per-architecture license
and dependency records. It requires macOS 14 or later. An MCPB-compatible client
can install this archive directly; Python and a separate app installation are not
required. The launcher selects `arm64` or `x86_64` from the Mac's native architecture.

MCPB stdio configuration runs `/bin/sh` with the extracted `server/launch.sh`.
The manifest configures `HOMESCREEN_READ_ONLY=1`; the launcher defaults to that value
when it is unset and preserves an explicit environment setting. To enable MCP
Apply and Restore, configure both `HOMESCREEN_READ_ONLY=0` and
`HOMESCREEN_ALLOW_APPLY=1` in the client, then reconnect to restart the server.
Before Apply, review `diff` and supply its latest `apply_token`; Restore takes the
selected backup name. Existing `HOMESCREEN_DATA` settings and data directories
continue to apply. See [write controls](../docs/MCP.md#data-and-write-controls).

To assemble a bundle from the two downloaded native Actions artifacts:

```sh
python3.12 macapp/release.py collect --input-dir artifacts --output-dir release
python3.12 macapp/mcp_bundle.py --assets-dir release --output-dir release \
  --repository worldsavepoint/ios-homescreen-organizer
python3.12 macapp/release.py verify --input-dir release \
  --repository worldsavepoint/ios-homescreen-organizer
```

`artifacts/` must contain the `home-screen-organizer-macos-arm64` and
`home-screen-organizer-macos-x86_64` artifact directories, each with its native
DMG, ZIP and checksum manifest. Assembly verifies every source archive before
writing output, checks app versions and architecture labels, and copies native
engine bytes, modes and relative symlinks into the MCPB. It rejects unsafe ZIP
paths, unsupported file types and escaping, dangling or cyclic engine symlinks.

The output adds these files beside the four native archives:

- `home-screen-organizer-<version>-macos.mcpb`
- `server.json`, identifying `io.github.worldsavepoint/home-screen-organizer` and
  the exact versioned GitHub MCPB URL and SHA256.
- `SHA256SUMS.txt`, covering all four native archives, the MCPB and `server.json`.

To check a locally extracted bundle on the matching native Mac:

```sh
ditto -x -k release/home-screen-organizer-<version>-macos.mcpb extracted-mcpb
python3.12 macapp/check_mcp.py -- /bin/sh "$PWD/extracted-mcpb/server/launch.sh"
```

The check initializes the server and lists tools with a startup deadline and a
fresh temporary read-only data directory, then terminates the server.

## Automatic releases

Pull requests and pushes to `main` run a native CI matrix:

- `macos-15` builds and validates Apple silicon (`arm64`).
- `macos-15-intel` builds and validates Intel (`x86_64`).

Each build checks the functional modules, packaged MCP initialization and tool
discovery, Mach-O architectures, ad-hoc signatures and archive checksums. The
installable Actions artifacts are `home-screen-organizer-macos-arm64` and
`home-screen-organizer-macos-x86_64`.

After both builds, CI assembles the complete distribution and validates its MCPB
manifest and Registry metadata with the official tools. It uploads
`home-screen-organizer-distribution`, then extracts that MCPB on both native Mac
architectures and repeats initialization and tool discovery. These final startup
checks use only Python's standard library and the assembled engines.

To publish a new version:

1. Set `project.version` in `pyproject.toml` to the new SemVer release version.
2. Merge the contribution into `main`, or push its matching `v<version>` tag.
3. After both native builds and standalone MCPB checks pass, CI publishes both
   DMGs, both ZIPs, the dual-architecture MCPB, `server.json` and the shared
   `SHA256SUMS.txt` in a GitHub release targeted at the exact built commit.
4. A following job validates and publishes the released `server.json` to the
   official MCP Registry using GitHub OIDC authentication.

Each project version has one published release. Subsequent builds retain a
published release's assets; CI resumes uploads and publication for an existing
draft. The Registry job reads metadata from the published release, compares the
exact existing Registry version's name, version and package metadata, and skips
matching publications. Conflicting metadata requires a new project version.
Retained releases without standalone MCP metadata skip Registry publication.

The Registry job has `id-token: write` and `contents: read`. It verifies the
pinned official `mcp-publisher` v1.8.9 Linux archive's SHA256 before extracting the
publisher and authenticating with `login github-oidc`. GitHub release write
permission is scoped to the separate release job. All GitHub actions are pinned
to commits.

Versions such as `1.2.0-beta.1` produce GitHub prereleases. The app's standard
macOS version fields contain the numeric core (`1.2.0`), while
`HomeScreenOrganizerReleaseVersion`, archive names, Registry metadata and Git tags
retain the complete version.
