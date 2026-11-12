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
version. Reports are produced locally.

The simulator adapter uses `HOMESCREEN_SIM` with an installed simulator runtime.
Available runtimes depend on the host macOS and Xcode versions. Simulator layout
checks and USB transport checks exercise different interfaces and should be
recorded separately for each release environment.
