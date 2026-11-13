# Compatibility checks

[README](../README.md) · [中文 README](../README.zh-CN.md) · [Layout writes and research](HOW-IT-WORKS.md#layout-writes) · [MCP setup](MCP.md)

## Supported iOS layout modes

- **iOS 16:** sequential app placement, folders, Dock and App Library organization.
  Keep folders after widgets originally read at the start of a page. The draft
  editor provides guidance when a placement needs adjustment.
- **iOS 17, 18, 26 and 27:** app and folder organization, Dock and App Library,
  preservation of widget configuration and fixed-position layout editing.
- **iPadOS:** grid, Dock and folder capacity follow the device's reported metrics.

The simulator adapter supports application-bundle icon metadata and standalone
UIKit rendering of asset-catalog and dynamic icons across these version families.

Before Apply, [unhide Home Screen pages and recreate desired gaps](HOW-IT-WORKS.md#layout-writes).

## Local checks

Run the local fixture checks to exercise layout parsing, draft editing, backup
restoration and transport behavior:

```sh
.venv/bin/python -m pytest -q tests
```

For a connected, already trusted USB device, the diagnostic command reads its
reported software information and exported Home Screen structure:

```sh
HOMESCREEN_READ_ONLY=1 .venv/bin/home-screen-organizer diagnose
```

The optional `--expected-version VERSION` argument selects the expected software
version. Save reports in a local directory outside the repository.

The simulator adapter uses `HOMESCREEN_SIM` with an installed simulator runtime.
Select a runtime supported by the installed macOS and Xcode versions. Keep
simulator layout results and USB transport results in separate local records.

The simulator icon reader uses the application's bundled icon metadata. For
asset-catalog or dynamically rendered icons, it builds a small UIKit reader with
the selected Xcode toolchain and runs it as a standalone process in that simulator.

On iOS 16, arrange icons in ordinary page order and place folders after widgets
originally read at the start of a page. The editor explains fixed-position and
folder-order conflicts and preserves the current draft. Reset restores the
original layout and retains undo history.
