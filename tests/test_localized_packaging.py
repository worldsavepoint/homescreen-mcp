"""Native distributions share manifest catalogs and localized product names."""
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "macapp/release.py"
LOCALES = ROOT / "homescreen/web/locales"
REQUIRED = {"en", "zh-Hans", "zh-Hant", "es", "de", "fr", "ru", "pt"}


def command(action, app, locales=LOCALES):
    return subprocess.run([sys.executable, str(SCRIPT), action, "--app", str(app),
                           "--locales", str(locales)], capture_output=True, text=True)


def make_app(tmp_path):
    app = tmp_path / "Screen Organizer.app"
    (app / "Contents/Resources").mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "io.github.worldsavepoint.ios-homescreen-organizer",
        "CFBundleExecutable": "HomeScreenOrganizer", "LSMinimumSystemVersion": "14.0"}))
    return app


def test_localization_resources_follow_manifest_and_shared_display_names(tmp_path):
    app = make_app(tmp_path)
    result = command("localize", app)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((LOCALES / "manifest.json").read_text())
    codes = [language["code"] for language in manifest["languages"]]
    assert REQUIRED <= set(codes)
    bundle = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    assert bundle["CFBundleLocalizations"] == codes
    assert bundle["CFBundleDisplayName"] == bundle["CFBundleName"] == "Screen Organizer"
    assert bundle["CFBundleIdentifier"] == "io.github.worldsavepoint.ios-homescreen-organizer"
    resources = app / "Contents/Resources"
    assert (resources / "Localization/manifest.json").read_bytes() == (LOCALES / "manifest.json").read_bytes()
    for code in codes:
        assert (resources / f"Localization/{code}.json").read_bytes() == (LOCALES / f"{code}.json").read_bytes()
        display = plistlib.loads((resources / f"{code}.lproj/InfoPlist.strings").read_bytes())
        expected = {"zh-Hans": "屏幕整理", "zh-Hant": "螢幕整理"}.get(code, "Screen Organizer")
        assert display == {"CFBundleName": expected, "CFBundleDisplayName": expected}
    assert command("check-localization", app).returncode == 0


@pytest.mark.parametrize("italian_registered,contribution", [
    (False, None), (True, None), (True, ("en-x-test-1", [])), (True, ("it-IT", ["it"])),
])
def test_additional_registered_locale_is_packaged_without_code_changes(tmp_path, italian_registered, contribution):
    locales = tmp_path / "catalogs"
    shutil.copytree(LOCALES, locales)
    manifest = json.loads((locales / "manifest.json").read_text())
    from tools.check_translations import canonical_locales

    registered = set(canonical_locales(manifest["languages"]).values())

    def add_locale(code, name, aliases):
        manifest["languages"].append({"code": code, "name": name, "aliases": aliases})
        shutil.copyfile(locales / "en.json", locales / f"{code}.json")
        registered.update([code, *aliases])

    def unused_private_code():
        index = 1
        while (code := f"en-x-test-{index}") in registered:
            index += 1
        return code

    if contribution:
        code, aliases = contribution
        if registered.isdisjoint([code, *aliases]):
            add_locale(code, "Contributed translation", [code, *aliases])
    if italian_registered and "it" not in registered:
        add_locale("it", "Italiano", ["it", unused_private_code()])
    code = unused_private_code()
    add_locale(code, "Test translation", [code])
    (locales / "manifest.json").write_text(json.dumps(manifest))
    validation = subprocess.run([sys.executable, str(ROOT / "tools/check_translations.py"),
                                 "--locales", str(locales)], capture_output=True, text=True)
    assert validation.returncode == 0, validation.stderr
    app = make_app(tmp_path)
    result = command("localize", app, locales)
    assert result.returncode == 0, result.stderr
    assert (app / f"Contents/Resources/{code}.lproj/InfoPlist.strings").is_file()
    assert command("check-localization", app, locales).returncode == 0


@pytest.mark.parametrize("damage", ["catalog", "manifest", "name", "languages", "missing"])
def test_package_resource_check_rejects_incomplete_or_stale_localizations(tmp_path, damage):
    app = make_app(tmp_path)
    assert command("localize", app).returncode == 0
    resources = app / "Contents/Resources"
    if damage == "catalog":
        (resources / "Localization/fr.json").write_text('{}')
    elif damage == "manifest":
        (resources / "Localization/manifest.json").write_text('{}')
    elif damage == "name":
        (resources / "zh-Hant.lproj/InfoPlist.strings").write_bytes(plistlib.dumps({"CFBundleDisplayName": "old name"}))
    elif damage == "missing":
        (resources / "de.lproj/InfoPlist.strings").unlink()
    else:
        path = app / "Contents/Info.plist"
        plist = plistlib.loads(path.read_bytes())
        plist["CFBundleLocalizations"] = ["en"]
        path.write_bytes(plistlib.dumps(plist))
    result = command("check-localization", app)
    assert result.returncode != 0
