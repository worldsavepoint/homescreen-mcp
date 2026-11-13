# Compatibility checks

Run the local fixture checks to exercise layout parsing, draft editing, backup
restoration and transport behavior:

```sh
.venv/bin/python -m pytest -q tests
```

For a connected, already trusted USB device, the diagnostic command reads its
reported software information and exported Home Screen structure:

```sh
HOMESCREEN_READ_ONLY=1 .venv/bin/homescreen diagnose
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
