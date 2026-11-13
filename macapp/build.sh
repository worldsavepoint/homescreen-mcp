#!/bin/zsh
# Build Homescreen.app and Homescreen-<version>.dmg into build/.
#   macapp/build.sh            full build
# Requires Python 3.12 and Xcode command line tools. See macapp/BUILDING.md.
set -euo pipefail

ROOT=${0:A:h:h}
BUILD=$ROOT/build
PYTHON=${HOMESCREEN_BUILD_PYTHON:-python3.12}
VENV=$(mktemp -d "${TMPDIR:-/tmp}/homescreen-build.XXXXXXXX")
trap 'rm -rf "$VENV"' EXIT
APP=$BUILD/Homescreen.app

"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --require-hashes --only-binary=:all: -r "$ROOT/requirements-build.lock"
"$VENV/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Build lock requires Python 3.12"'
"$VENV/bin/python" -m pip install --no-deps --no-build-isolation "$ROOT"
"$VENV/bin/python" -m pip check
VERSION=$("$VENV/bin/python" "$ROOT/macapp/release.py" version)
BUNDLE_VERSION=${VERSION%%-*}

echo "• engine"
(cd "$ROOT/macapp" && "$VENV/bin/pyinstaller" --clean --noconfirm --log-level ERROR \
    --distpath "$BUILD/dist" --workpath "$BUILD/work" engine.spec)

echo "• shell"
(cd "$ROOT/macapp/Shell" && swift build -c release --arch arm64)
SHELL_BIN=$(cd "$ROOT/macapp/Shell" && swift build -c release --arch arm64 --show-bin-path)/Homescreen

echo "• app bundle"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$SHELL_BIN" "$APP/Contents/MacOS/Homescreen"
cp -R "$BUILD/dist/engine" "$APP/Contents/Resources/engine"
"$VENV/bin/python" -c 'import importlib.metadata as m; print("\n".join(sorted(d.metadata["Name"] + "==" + d.version for d in m.distributions())))' \
  > "$APP/Contents/Resources/dependencies.txt"
cp "$ROOT/requirements-build.lock" "$APP/Contents/Resources/requirements-build.lock"
cp "$ROOT/LICENSE" "$APP/Contents/Resources/LICENSE"
"$VENV/bin/python" "$ROOT/macapp/make_icon.py" "$BUILD/AppIcon.iconset"
iconutil -c icns "$BUILD/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Homescreen</string>
  <key>CFBundleDisplayName</key><string>Homescreen</string>
  <key>CFBundleIdentifier</key><string>io.github.kats1123.homescreen</string>
  <key>CFBundleExecutable</key><string>Homescreen</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$BUNDLE_VERSION</string>
  <key>CFBundleVersion</key><string>$BUNDLE_VERSION</string>
  <key>HomescreenReleaseVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>Copyright © 2026 Jonathan Kats. MIT License.</string>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST

echo "• ad-hoc signing"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

echo "• dmg"
DMG=$BUILD/Homescreen-$VERSION.dmg
STAGE=$BUILD/dmg
rm -rf "$STAGE" "$DMG" && mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/" && ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "Homescreen $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
echo "built $APP ($(du -sh "$APP" | cut -f1)) and $DMG ($(du -sh "$DMG" | cut -f1))"
