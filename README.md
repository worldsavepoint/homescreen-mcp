<h1 align="center">Home Screen Organizer</h1>
<p align="center"><strong>Arrange your iPhone or iPad Home Screen from your Mac.</strong><br>macOS 14+ · Apple silicon &amp; Intel · Supports iOS 16+</p>

<p align="center">
  <a href="https://github.com/worldsavepoint/ios-homescreen-organizer/releases"><img alt="Releases" src="https://img.shields.io/badge/download-Releases-blue"></a>
  <a href="https://github.com/worldsavepoint/ios-homescreen-organizer/actions/workflows/tests.yml"><img alt="Build" src="https://github.com/worldsavepoint/ios-homescreen-organizer/actions/workflows/tests.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-blue"></a>
  <a href="macapp/BUILDING.md"><img alt="macOS 14 or later" src="https://img.shields.io/badge/macOS-14%2B-222222"></a>
</p>
<p align="center"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>
<p align="center"><a href="#install">Download</a> · <a href="#get-started">Quick start</a> · <a href="#compatibility">Compatibility</a> · <a href="#mcp">MCP setup</a> · <a href="#development">Develop</a></p>

Drag real app icons, arrange folders and widgets, sort by color or usage, and compare your draft before applying it over USB. Use the Mac app, local browser editor, CLI or an MCP assistant. Free and open source; no account or jailbreak required.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/app-dark.png">
  <img alt="Home Screen Organizer editor with app icons, widgets, App Library and usage information" src="docs/app-light.png" width="1200">
</picture>
<p align="center"><sub>Interface screenshots from Jonathan Kats’s upstream <a href="https://github.com/kats1123/homescreen-mcp">Homescreen project</a>.</sub></p>

## What you can do

| Organize | Review | Work your way |
| --- | --- | --- |
| Drag apps, folders, widgets and Dock items | Compare device layout and draft | Native Mac app or local browser |
| Sort by color, A–Z, category or usage | Undo and redo draft edits | CLI and standard stdio MCP |
| Move apps to the App Library or App Bank | Back up before writes; verify by readback | Separate drafts and backups per device |

Multi-select, search, page editing and multi-page folders help with larger layouts. Category lookup and usage sorting have their own [data sources and permissions](docs/HOW-IT-WORKS.md#data-and-privacy).

<a id="install"></a>

## Download

Open [Releases](https://github.com/worldsavepoint/ios-homescreen-organizer/releases) and choose the archive matching **Apple menu → About This Mac → Chip / Processor**.

| Your Mac | Download |
| --- | --- |
| Apple silicon (M-series) | `home-screen-organizer-<version>-macos-arm64.dmg` |
| Intel | `home-screen-organizer-<version>-macos-x86_64.dmg` |
| MCPB-compatible client | `home-screen-organizer-<version>-macos.mcpb` — both architectures; [install guide](docs/MCP.md#standalone-mcpb) |

Open the DMG and drag **Home Screen Organizer** into **Applications**. ZIP archives are also available. The app includes its Python engine and dependencies and requires **macOS 14 or later**.

The app is **ad-hoc signed**. If macOS requests approval, use **System Settings → Privacy & Security → Open Anyway**, then launch it again.

To verify a download, save `SHA256SUMS.txt` beside the chosen archive and run:

```sh
shasum -a 256 --check --ignore-missing SHA256SUMS.txt
```

For source installation, native builds and Actions artifacts, see [Building Home Screen Organizer](macapp/BUILDING.md).

<a id="get-started"></a>

## Quick start

1. Open Home Screen Organizer, connect your iPhone or iPad by USB, and unlock it. Tap **Trust** if asked.
2. Select the device and click **Read** to start a draft from its current layout.
3. Drag items or choose a sorting action. Empty the **App Bank** and review the layout comparison.
4. **Before Apply:** unhide Home Screen pages on the device (long-press the Home Screen, then tap the page dots) and recreate desired gaps in the editor. Choose **Review & Apply** to save a backup, write the draft and read back the result.

Edits stay in the draft until applied. With `HOMESCREEN_READ_ONLY=1`, you can read and edit drafts while **Apply and Restore are disabled**. For source installs, start that mode with:

```sh
HOMESCREEN_READ_ONLY=1 .venv/bin/home-screen-organizer ui
```

After an interrupted or mismatching write, run **Read** again before continuing. See [hidden pages, gaps and backups](docs/HOW-IT-WORKS.md#layout-writes).

<a id="compatibility"></a>

## Compatibility

These version families select the following layout behavior. See [compatibility and diagnostic guidance](docs/COMPATIBILITY.md) for details.

| iOS family | Layout mode |
| --- | --- |
| 16 | Sequential app order; folders after widgets originally at the start of a page |
| 17 / 18 / 26 / 27 | Fixed-position editing, app and folder organization, widget configuration preservation |

All modes include Dock and App Library organization. iPad grid, Dock and folder capacities follow the device’s reported metrics. App Library contents are inferred from installed apps and the exported layout.

<a id="mcp"></a>

## Use an MCP assistant

In the Mac app, choose **Device → MCP** to copy a launch command or configuration for **Codex, Cursor, Claude, or VS Code / Copilot**. The copied configurations start in read-only mode.

Any local stdio MCP client can launch the bundled engine:

```sh
HOMESCREEN_READ_ONLY=1 '/Applications/Home Screen Organizer.app/Contents/Resources/engine/engine' mcp
```

Source installs use `.venv/bin/home-screen-mcp`. Ask the assistant to “group my apps by color” or “show a draft with my most-used apps on page 1.” Review `diff` and a preview before applying.

**[MCP setup guide](docs/MCP.md)** · [中文配置指南](docs/MCP.zh-CN.md) · [Codex](docs/MCP.md#codex) · [Cursor / Claude](docs/MCP.md#cursor-and-claude) · [VS Code / Copilot](docs/MCP.md#vs-code-and-copilot) · [MCPB](docs/MCP.md#standalone-mcpb)

The server runs on your Mac. Tool results go to the MCP client; its model and privacy settings determine subsequent processing. Assistant writes require an additional apply gate. See [data handling and write controls](docs/MCP.md#data-and-write-controls).

<a id="development"></a>

## Develop and explore

- [Source installation, native builds and releases](macapp/BUILDING.md)
- [USB protocol, widgets, gaps and usage estimates](docs/HOW-IT-WORKS.md)
- [Local editor sessions and API](docs/LOCAL-EDITOR.md)
- [Layout modes and diagnostics](docs/COMPATIBILITY.md)
- [MCP distribution and Registry publishing](docs/MCP.md#distribution-and-discovery)

The primary commands are `home-screen-organizer` and `home-screen-mcp`. Existing `ios-homescreen-organizer`, `ios-homescreen-mcp`, `homescreen` and `homescreen-mcp` aliases remain available. The source checkout directory stays `ios-homescreen-organizer`.

## Credits and license

**Jonathan Kats** created Homescreen. The original app, editor, screenshots and SpringBoard research come from the [upstream project](https://github.com/kats1123/homescreen-mcp) and its contributors. This fork maintains device sessions, backups, the local editor, the Mac launcher and distribution. Thanks to [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) for the USB interface.

[MIT](LICENSE) · Copyright © 2026 Jonathan Kats. The original license and copyright notice are preserved.

[Report a fork issue](https://github.com/worldsavepoint/ios-homescreen-organizer/issues) with installation method, reproduction steps and a redacted error. [Upstream source](https://github.com/kats1123/homescreen-mcp) · [upstream issues](https://github.com/kats1123/homescreen-mcp/issues) · [upstream releases](https://github.com/kats1123/homescreen-mcp/releases).

## Disclaimer

Home Screen Organizer is not affiliated with, endorsed by, or sponsored by Apple Inc.

Mac, macOS, iPhone, iPad and Screen Time are trademarks of Apple Inc. IOS is a trademark or registered trademark of Cisco in the U.S. and other countries and is used by Apple under license.

This tool uses private device interfaces that may change with iOS updates. It saves a Home Screen layout backup before applying or restoring a layout and attempts to verify the result by reading the layout back. Keep a separate, up-to-date full backup of your iPhone or iPad. Use the tool at your own risk; it is provided “AS IS” under the [MIT License](LICENSE).

<p align="center">
  <sub>README views</sub><br>
  <a href="https://github.com/journey-ad/Moe-Counter"><img src="https://count.moeyy.cn/@worldsavepoint.homescreen?theme=gelbooru&amp;padding=7&amp;scale=0.7&amp;darkmode=auto" alt="Home Screen Organizer README views — Moe Counter" width="320"></a>
</p>
