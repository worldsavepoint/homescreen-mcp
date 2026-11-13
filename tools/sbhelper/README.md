# Simulator SpringBoard harness

The harness feeds a layout to the simulator's `SBIconController importIconState:`
method. `icon_controller` selects the available controller accessor.

- `sbinject.m` loads into SpringBoard for a test session. The `homescreen.import`
  notification imports `$SBTEST_DIR/in.plist` and writes `$SBTEST_DIR/out.txt`.
- `post.c` sends that notification from a process in the selected simulator.
- `sbhelper.m` contains the MIG entry-point experiment. The notification harness
  provides the active import workflow.

## Build and run

Choose a booted simulator and set `SIMULATOR_UDID` to its identifier. Create the
harness directory outside the repository and save the initial layout:

```sh
SIMULATOR_UDID="<simulator-id>"
HARNESS_DIR="$(mktemp -d)"
SIMULATOR_STATE="$HOME/Library/Developer/CoreSimulator/Devices/$SIMULATOR_UDID/data/Library/SpringBoard/IconState.plist"
cp "$SIMULATOR_STATE" "$HARNESS_DIR/before-IconState.plist"

SDK_PATH="$(xcrun --sdk iphonesimulator --show-sdk-path)"
SIMULATOR_TARGET="$(uname -m)-apple-ios16.0-simulator"
xcrun --sdk iphonesimulator clang -target "$SIMULATOR_TARGET" -isysroot "$SDK_PATH" \
  -fobjc-arc -dynamiclib -framework Foundation -framework UIKit \
  sbinject.m -o "$HARNESS_DIR/sbinject.dylib"
xcrun --sdk iphonesimulator clang -target "$SIMULATOR_TARGET" -isysroot "$SDK_PATH" \
  post.c -o "$HARNESS_DIR/post"
codesign -s - -f "$HARNESS_DIR/sbinject.dylib" "$HARNESS_DIR/post"

xcrun simctl spawn "$SIMULATOR_UDID" launchctl debug user/foreground/com.apple.SpringBoard \
  --environment "DYLD_INSERT_LIBRARIES=$HARNESS_DIR/sbinject.dylib" "SBTEST_DIR=$HARNESS_DIR" --
xcrun simctl spawn "$SIMULATOR_UDID" launchctl kill SIGKILL user/foreground/com.apple.SpringBoard
```

After the Home Screen appears, write the target layout to
`$HARNESS_DIR/in.plist`, then send the import notification:

```sh
xcrun simctl spawn "$SIMULATOR_UDID" "$HARNESS_DIR/post"
cat "$HARNESS_DIR/out.txt"
```

Compare the saved layout with the target. To finish the session, restore the
initial snapshot and restart SpringBoard:

```sh
cp "$HARNESS_DIR/before-IconState.plist" "$SIMULATOR_STATE"
xcrun simctl spawn "$SIMULATOR_UDID" launchctl kill SIGKILL user/foreground/com.apple.SpringBoard
```

The debug environment applies to one SpringBoard launch. Keep input layouts,
responses and snapshots in the local harness directory.

## Layout format

- Use a dictionary containing `buttonBar`, `iconLists` and `ignored` to preserve
  App Library placement. Represent apps as bundle identifier strings.
- Include `listUniqueIdentifiers` and `listMetadata` to set fixed locations.
  Each page's `fixedLocations` maps an identifier to a grid cell; the metadata
  also contains `fixedLocationsGridColumns` and `fixedLocationsGridRows`.
- Restore a widget's `userSelectedElementIdentifier` as `uniqueIdentifier` to
  retain its configuration association.
- Read back the layout after importing. The import response and saved layout
  are both available for inspection.

The `homescreen.export`, `homescreen.exports` and `homescreen.gap` notifications
provide additional archive, model-export and fixed-location inspection tools.
See the [upstream project](https://github.com/kats1123/homescreen-mcp) for the
original SpringBoard research.
