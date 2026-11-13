#!/bin/zsh
# Build Screen Organizer.app and home-screen-organizer-<version>.dmg into build/.
#   macapp/build.sh            full build
# Requires Python 3.12 and Xcode command line tools. See macapp/BUILDING.md.
set -euo pipefail

ROOT=${0:A:h:h}
ARCH=${HOMESCREEN_BUILD_ARCH:-$(uname -m)}
case "$ARCH" in
  arm64|x86_64) ;;
  *) echo "Select arm64 or x86_64 for the build architecture." >&2; exit 1 ;;
esac
if [[ "$(uname -m)" != "$ARCH" ]]; then
  echo "Use a native $ARCH build host." >&2
  exit 1
fi
export HOMESCREEN_BUILD_ARCH="$ARCH"
export MACOSX_DEPLOYMENT_TARGET=14.0
BUILD=$ROOT/build/$ARCH
PYTHON=${HOMESCREEN_BUILD_PYTHON:-python3.12}
VENV=$(mktemp -d "${TMPDIR:-/tmp}/homescreen-build.XXXXXXXX")
trap 'rm -rf "$VENV"' EXIT
APP="$BUILD/Screen Organizer.app"

LOCK="$ROOT/requirements-build.lock"
WHEEL_LINKS=()
if [[ "$ARCH" == x86_64 ]]; then
  DEPENDENCIES="$ROOT/build/dependencies/x86_64"
  if [[ ! -f "$DEPENDENCIES/requirements-build.lock" ]]; then
    bash "$ROOT/macapp/prepare_intel.sh" "$PYTHON" "$DEPENDENCIES"
  fi
  LOCK="$DEPENDENCIES/requirements-build.lock"
  WHEEL_LINKS=(--find-links "$DEPENDENCIES/wheels")
fi
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --require-hashes --only-binary=:all: "${WHEEL_LINKS[@]}" -r "$LOCK"
"$VENV/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Build lock requires Python 3.12"'
"$VENV/bin/python" -m pip install --no-deps --no-build-isolation "$ROOT"
"$VENV/bin/python" -m pip check
"$VENV/bin/python" -c 'import platform, sys; assert platform.machine() == sys.argv[1], "Use a matching Python architecture"' "$ARCH"
VERSION=$("$VENV/bin/python" "$ROOT/macapp/release.py" version)
BUNDLE_VERSION=${VERSION%%-*}

echo "• engine"
(cd "$ROOT/macapp" && "$VENV/bin/pyinstaller" --clean --noconfirm --log-level ERROR \
    --distpath "$BUILD/dist" --workpath "$BUILD/work" engine.spec)

echo "• shell"
(cd "$ROOT/macapp/Shell" && swift build -c release --arch "$ARCH")
SHELL_BIN=$(cd "$ROOT/macapp/Shell" && swift build -c release --arch "$ARCH" --show-bin-path)/HomeScreenOrganizer

echo "• app bundle"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$SHELL_BIN" "$APP/Contents/MacOS/HomeScreenOrganizer"
cp -R "$BUILD/dist/engine" "$APP/Contents/Resources/engine"
"$VENV/bin/python" -c 'import importlib.metadata as m; print("\n".join(sorted(d.metadata["Name"] + "==" + d.version for d in m.distributions())))' \
  > "$APP/Contents/Resources/dependencies.txt"
cp "$LOCK" "$APP/Contents/Resources/requirements-build.lock"
if [[ "$ARCH" == x86_64 ]]; then
  cp "$ROOT/requirements-cryptography-x86_64.lock" "$APP/Contents/Resources/requirements-cryptography-x86_64.lock"
  cp "$DEPENDENCIES/OPENSSL-LICENSE.txt" "$APP/Contents/Resources/OPENSSL-LICENSE.txt"
fi
cp "$ROOT/LICENSE" "$APP/Contents/Resources/LICENSE"
"$VENV/bin/python" "$ROOT/macapp/make_icon.py" "$BUILD/AppIcon.iconset"
iconutil -c icns "$BUILD/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Screen Organizer</string>
  <key>CFBundleDisplayName</key><string>Screen Organizer</string>
  <key>CFBundleIdentifier</key><string>io.github.worldsavepoint.ios-homescreen-organizer</string>
  <key>CFBundleExecutable</key><string>HomeScreenOrganizer</string>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$BUNDLE_VERSION</string>
  <key>CFBundleVersion</key><string>$BUNDLE_VERSION</string>
  <key>HomeScreenOrganizerReleaseVersion</key><string>$VERSION</string>
  <key>HomeScreenOrganizerArchitecture</key><string>$ARCH</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>Copyright © 2026 Jonathan Kats. MIT License.</string>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST

"$VENV/bin/python" "$ROOT/tools/check_translations.py"
"$VENV/bin/python" "$ROOT/macapp/release.py" localize --app "$APP"
"$VENV/bin/python" "$ROOT/macapp/release.py" check-localization --app "$APP"

echo "• ad-hoc signing"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

echo "• dmg"
DMG=$BUILD/home-screen-organizer-$VERSION.dmg
STAGE=$BUILD/dmg
rm -rf "$STAGE" "$DMG" && mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/" && ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "Screen Organizer" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
echo "built $APP ($(du -sh "$APP" | cut -f1)) and $DMG ($(du -sh "$DMG" | cut -f1))"
