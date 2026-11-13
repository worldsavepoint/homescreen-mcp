<div align="center">

<h1>iOS Home Screen Organizer</h1>
<p><strong>Arrange your iPhone or iPad Home Screen from your Mac, with drag-and-drop editing and MCP.</strong></p>

**Original project by Jonathan Kats · Fork of [kats1123/homescreen-mcp](https://github.com/kats1123/homescreen-mcp).**

[![Release](https://img.shields.io/github/v/release/worldsavepoint/ios-homescreen-organizer)](https://github.com/worldsavepoint/ios-homescreen-organizer/releases)
[![Build](https://github.com/worldsavepoint/ios-homescreen-organizer/actions/workflows/tests.yml/badge.svg)](https://github.com/worldsavepoint/ios-homescreen-organizer/actions/workflows/tests.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-14%2B-222222?logo=apple)](macapp/BUILDING.md)
[![Source build](https://img.shields.io/badge/source_build-Python_3.12_%C2%B7_arm64_%26_x86__64-3776AB)](macapp/BUILDING.md)

**English** · [简体中文](README.zh-CN.md)

[Install](#install) · [Get started](#get-started) · [Compatibility](#compatibility) · [Optional MCP](#mcp) · [Report an issue](https://github.com/worldsavepoint/ios-homescreen-organizer/issues)

</div>

Drag and drop real app icons, arrange folders and widgets, sort by color or usage, and review a layout before applying it over USB. iOS Home Screen Organizer includes a Mac app, a browser editor, a CLI and an optional MCP server for AI assistants. Free and open source; no account or jailbreak required.

This fork maintains changes to device sessions, backups, the local editor and the macOS launcher. The original app, interface and SpringBoard research are the work of **Jonathan Kats and upstream contributors**. This fork is independently maintained.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/app-dark.png">
  <img alt="iOS Home Screen Organizer editor with real app icons, widgets, App Library and app usage" src="docs/app-light.png">
</picture>

<p align="center"><sub>Interface screenshots from the upstream Homescreen project by Jonathan Kats.</sub></p>

<a id="features"></a>

## ✨ What you can do

- **Arrange visually:** drag real icons, folders, widgets and dock items across pages. Use multi-select, search, undo/redo and ⌥-drop to swap items.
- **Organize in one click:** sort by color, A–Z, App Store category or app usage, with an estimate of page swipes saved.
- **Keep a working area:** park items in the App Bank, add/move/delete pages, and edit folders with multiple pages.
- **Manage the App Library:** move apps into or out of it. iOS Home Screen Organizer infers its contents from installed apps and the visible layout.
- **Review and apply:** compare the draft, save a device-specific backup before a write, and read back the result. Exported widget settings are included in comparisons.
- **Choose your interface:** Mac app, local browser editor, CLI or 30 MCP tools. Drafts and backups are kept separately for each device.

<a id="fork-updates"></a>

## 🔧 Changes in this fork

- **Read-only sessions:** `HOMESCREEN_READ_ONLY=1` lets you read and edit a local draft while Apply and Restore are disabled in the editor, CLI and MCP session.
- **Device and backup handling:** Apply and Restore refresh the device identity and layout, record backup provenance, and check the result. Run Read after an interrupted or mismatching operation. Restore selects backups with matching device provenance.
- **Local editor and launcher:** authenticated editor sessions, backend health checks and launcher URL/request validation. See the [local editor API reference](docs/LOCAL-EDITOR.md).
- **Legacy layouts and distribution:** iOS 16 placement guidance, simulator icon rendering, and automatic versioned DMG/ZIP releases with SHA256 checksums.
- **Source builds:** pinned, hash-checked dependencies for Python 3.12 on Apple silicon and Intel Macs. See [build instructions](macapp/BUILDING.md).

<a id="install"></a>

## 📦 Install

**Apple silicon or Intel Mac · macOS 14 or later · iOS 16 / 17 / 18 / 26 / 27**

### Download the Mac app

Open [Releases](https://github.com/worldsavepoint/ios-homescreen-organizer/releases) and choose the download for your Mac. In **Apple menu → About This Mac**, check **Chip** or **Processor**:

- **Apple silicon** (Apple M-series chip): download `ios-homescreen-organizer-<version>-macos-arm64.dmg`.
- **Intel** processor: download `ios-homescreen-organizer-<version>-macos-x86_64.dmg`.

Open the DMG and drag **iOS Home Screen Organizer** into **Applications**. Each architecture also has a ZIP archive. The downloads include the Python engine and dependencies; they require macOS 14 or later and the matching CPU architecture.

The app uses **ad-hoc signing**. If macOS requests approval, open **System Settings → Privacy & Security → Open Anyway**, then launch iOS Home Screen Organizer again.

`SHA256SUMS.txt` contains the hashes for all four release archives. Save it in the same directory as your chosen DMG or ZIP, then verify the download:

```sh
shasum -a 256 --check --ignore-missing SHA256SUMS.txt
```

PR builds are available under [Actions](https://github.com/worldsavepoint/ios-homescreen-organizer/actions/workflows/tests.yml) → the completed run → **ios-homescreen-organizer-macos-arm64** or **ios-homescreen-organizer-macos-x86_64**. After a merge into `main`, successful builds for both architectures publish each new project version to Releases automatically.

### Install from source

Use an **Apple silicon or Intel Mac with macOS 14+ and native Python 3.12**. Connect an iPhone or iPad over USB and trust the Mac on the device. Clone the repository and create a virtual environment:

```sh
git clone https://github.com/worldsavepoint/ios-homescreen-organizer.git
cd ios-homescreen-organizer
python3.12 -m venv .venv
```

On **Apple silicon**, install the committed dependency lock:

```sh
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock
```

On **Intel**, install the [source build prerequisites](macapp/BUILDING.md#intel-dependencies), then prepare and install the hashed Intel dependencies:

```sh
bash macapp/prepare_intel.sh python3.12 "$PWD/build/dependencies/x86_64"
.venv/bin/python -m pip install --require-hashes --only-binary=:all: \
  --find-links "$PWD/build/dependencies/x86_64/wheels" \
  -r "$PWD/build/dependencies/x86_64/requirements-build.lock"
```

On either architecture, install the project:

```sh
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pip check
```

Start the browser editor in read-only mode:

```sh
HOMESCREEN_READ_ONLY=1 .venv/bin/ios-homescreen-organizer ui
```

The command-line editor is `ios-homescreen-organizer`; the MCP server is `ios-homescreen-mcp`. The `homescreen` and `homescreen-mcp` command aliases remain available.

### Build the Mac app

With Python 3.12 and the [source build prerequisites](macapp/BUILDING.md) installed, run from the repository root on the target Mac:

```sh
macapp/build.sh
```

The script selects the native host architecture (`arm64` or `x86_64`) and creates `build/<arch>/iOS Home Screen Organizer.app` and `build/<arch>/ios-homescreen-organizer-<version>.dmg`. It uses a fresh Python environment, prepares Intel dependencies when needed, and applies **ad-hoc signing**. See [macOS build and signing details](macapp/BUILDING.md).

Create release archives with `python3.12 macapp/release.py package --arch "$(uname -m)"`. The output directory `build/release/<arch>/` contains the architecture-specific DMG, ZIP and `SHA256SUMS.txt`. Published releases combine both architectures into one shared checksum manifest. See [automatic release publishing](macapp/BUILDING.md#automatic-releases).

<a id="get-started"></a>

## 🚀 Get started

1. Launch the editor, connect your iPhone or iPad by USB, and unlock it. Tap **Trust** if asked.
2. Select your device and click **Read** to load its current layout.
3. Drag items, use a sorting action, or park items in the **App Bank** while arranging. Changes stay in the local draft until applied.
4. Review the layout comparison. In a read-only session, keep exploring and editing the draft; Apply and Restore are disabled.

For a normal session, start `.venv/bin/ios-homescreen-organizer ui` without `HOMESCREEN_READ_ONLY=1`, or open the built Mac app. **Review & Apply** then writes the reviewed draft to the device after saving a backup. Device checks are listed in [compatibility](#compatibility).

Before applying a layout, **unhide hidden Home Screen pages on the device**: long-press the Home Screen and tap the page dots. Recreate your desired gaps in iOS Home Screen Organizer. See [USB layout details](#usb-details).

### Sort by app usage

- **Device reports:** periodic iOS memory reports provide an estimate of app usage without setup. Apps with frequent or continuous residency receive less weight in the estimate.
- **Screen Time:** enable *Settings → Screen Time → Share Across Devices* on both the device and Mac. Reading the synced history needs **Full Disk Access** for iOS Home Screen Organizer, or for the Terminal running it, in *System Settings → Privacy & Security*.

### CLI

After installation, use `.venv/bin/ios-homescreen-organizer --help` for commands:

```text
read · show · diff · preview · apply · backups · restore · diagnose · probe · ui
```

For a read compatibility report on one already trusted USB device:

```sh
HOMESCREEN_READ_ONLY=1 .venv/bin/ios-homescreen-organizer diagnose
```

This prints the reported software version and aggregate layout counts.

<a id="compatibility"></a>

## 📱 Compatibility

- **iOS 16:** app order, folders, Dock and App Library organization. Icons follow sequential page order; place folders after widgets at the start of a page. The editor guides placement as you edit.
- **iOS 17, 18, 26 and 27:** app and folder organization, Dock, App Library, widget preservation and fixed-position layout editing.
- **Simulator development:** icon metadata and asset-catalog rendering are supported across these version families. See [layout modes and compatibility checks](docs/COMPATIBILITY.md).
- **iPad:** grid, dock and folder capacities come from the device. MCP/CLI operations and the editor use those capacities; widget pages retain the shape supplied by iPadOS.
- **macOS:** native Apple silicon (`arm64`) and Intel (`x86_64`) apps for macOS 14 or later.
- **Python:** package metadata permits Python 3.11+; the documented source and release builds use Python 3.12 with architecture-specific, hash-checked dependencies.

iOS Home Screen Organizer infers App Library contents from installed apps and layout reads. Keep an archived device backup and recreate your desired gaps in the editor before applying a layout.

<a id="mcp"></a>

## 🔌 Optional: use an AI assistant

MCP lets an assistant inspect, rearrange, sort and explain your layout. For Claude Code with the Mac app, choose **Device → Copy MCP Setup Command**. It points at the engine bundled in your app:

```sh
claude mcp add ios-homescreen-mcp -- "/Applications/iOS Home Screen Organizer.app/Contents/Resources/engine/engine" mcp
```

For the Python installation, run this command from the repository root to use the executable in your virtual environment:

```sh
claude mcp add ios-homescreen-mcp -- "$PWD/.venv/bin/ios-homescreen-mcp"
```

For Claude Desktop's `claude_desktop_config.json`, replace `/path/to/ios-homescreen-organizer` with your checkout's absolute path:

```json
{
  "mcpServers": {
    "ios-homescreen-mcp": {
      "command": "/path/to/ios-homescreen-organizer/.venv/bin/ios-homescreen-mcp",
      "env": { "HOMESCREEN_READ_ONLY": "1" }
    }
  }
}
```

Try *“organize my apps by color”* or *“put my most-used apps on page 1.”* The assistant edits a draft. In a normal session, you apply it through the editor or `ios-homescreen-organizer apply <token>`. Assistant-initiated writes require `HOMESCREEN_ALLOW_APPLY=1`; `HOMESCREEN_READ_ONLY=1` keeps Apply and Restore disabled.

<a id="usb-details"></a>

## 🧠 How it works

[pymobiledevice3](https://github.com/doronz88/pymobiledevice3) communicates over USB: `com.apple.springboardservices` reads layouts and icons, and `installation_proxy` reads installed apps. The editor runs on `127.0.0.1` with authenticated local sessions. Drafts, backups and icon caches are stored in `~/Library/Application Support/homescreen-mcp`.

The optional **Group by App Store category** action asks before sending bundle IDs to Apple's public lookup API and caches the results. Screen Time history is read locally from synced Biome `App.InFocus` streams. Page-swipe estimates count page *N* as *N−1* swipes, plus folder pages, with the dock free.

<details>
<summary><strong>App Library and widget research — from the upstream project</strong></summary>

Jonathan Kats's upstream research describes SpringBoard's icon-state import path:

1. USB `getIconState` returns icon order as `[dock, page 1, page 2, …]`.
2. `setIconState` reaches `-[SBIconController importIconState:]`. `+[SBIconStateArchiver rootArchiveFromITunesRepresentation:]` converts that list into `buttonBar` and `iconLists`.
3. Apps omitted from that list can be placed onto Home Screen pages. The dictionary import format uses `ignored` to retain App Library placement.

iOS Home Screen Organizer instead sends SpringBoard's dictionary form: `buttonBar`, `iconLists` and `ignored` for App Library items. It infers `ignored` from installed apps, including offloaded apps, minus apps on the Home Screen and hidden/system-only apps. App and folder data and unknown fields are retained as items move.

**Widgets:** configuration is associated with an element ID exported as `userSelectedElementIdentifier`. iOS Home Screen Organizer sends it back as `uniqueIdentifier` and remembers IDs across reads. Readback compares exported widget settings and element identifiers.

**Web clips:** iOS Home Screen Organizer remembers clips observed in layout reads per device and includes off-screen clips in `ignored`. If a new clip appears after a write, the result names it under `hidden_webclips`. Move the clip to the App Library and apply again.

The upstream implementation omits Today View and page-ID keys where their existing device values should be retained. Its simulator harness is in [`tools/sbhelper/`](tools/sbhelper/README.md). See the [upstream project](https://github.com/kats1123/homescreen-mcp) for the original research.

</details>

<details>
<summary><strong>Gaps, hidden pages and layout validation</strong></summary>

iOS stores pinned empty cells in `listMetadata` → `fixedLocations`, keyed by page ID. Include page IDs and gap metadata in a write to retain those empty cells across pages.

- iOS Home Screen Organizer remembers gaps created in its editor per device and sends their page IDs and pins with writes.
- Recreate desired gaps by dropping an app on the target empty spot in the editor.
- Unhide Home Screen pages before applying a layout.

Validation checks page/dock/folder capacities, item duplication or loss, nested folders/widgets, and an empty App Bank. On iPhone, a 4×6 page has 24 slots; small/medium/large widgets take 4/8/16, the dock holds 4, and folders hold 9 per page. iPad capacities come from the device's icon metrics.

System apps that iOS never displays on the Home Screen are listed in `NEVER_ON_HOME_SCREEN` in [`homescreen/device.py`](homescreen/device.py). An unexpected system app reported as `added_by_ios` may require updating that list.

</details>

<a id="development"></a>

## 🛠️ Development

Use the source installation above, then run the repository checks:

```sh
.venv/bin/python -m pytest -q tests
```

Explore the editor with a fixture:

```sh
.venv/bin/python tests/fake_phone.py fake.plist --dict
HOMESCREEN_FIXTURE=fake.plist .venv/bin/ios-homescreen-organizer ui
```

Or use a booted simulator:

```sh
HOMESCREEN_SIM=booted .venv/bin/ios-homescreen-organizer ui
```

References: [macOS builds and dependency lock](macapp/BUILDING.md) · [local editor sessions and API](docs/LOCAL-EDITOR.md) · [compatibility checks](docs/COMPATIBILITY.md).

<a id="credits"></a>

## 🤝 Credits and support

**Jonathan Kats** created Homescreen. Credit for the original Mac app, editor, screenshots and SpringBoard investigation belongs to the [upstream project](https://github.com/kats1123/homescreen-mcp) and its contributors. Thanks also to [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) for the USB device interface.

- **This fork:** [source and changes](https://github.com/worldsavepoint/ios-homescreen-organizer) · [issues and support](https://github.com/worldsavepoint/ios-homescreen-organizer/issues).
- **Original project:** [upstream source](https://github.com/kats1123/homescreen-mcp) · [upstream issues and support](https://github.com/kats1123/homescreen-mcp/issues) · [upstream releases](https://github.com/kats1123/homescreen-mcp/releases).

For issues with this fork, include the installation method, reproduction steps, expected result and a redacted error message.

<a id="license"></a>

## 📄 License

[MIT](LICENSE). Copyright © 2026 Jonathan Kats. The original license and copyright notice are preserved.

iPhone, iOS and Screen Time are Apple trademarks. iOS Home Screen Organizer uses private device interfaces for layout operations.
