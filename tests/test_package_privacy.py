import io
import sys
import sysconfig
import zipfile
from pathlib import Path

import pytest


def test_build_configuration_relocates_complete_path_components(tmp_path, monkeypatch):
    from macapp.frozen_engine import replace_sysconfig

    root = "/build roots/python"
    name = sysconfig._get_sysconfigdata_name()
    values = {"prefix": root, "list": f"{root}/lib {root}", "flags": f"-I{root}/inc",
              "sibling": root + "-tools", "other": "/parent" + root + "/lib",
              "literal": "__PYTHON_PREFIX__", "number": 42}
    entries = [("another", "another.py", "PYMODULE"), (name, "original.py", "PYMODULE")]
    cache = {"another": object(), name: object()}
    replace_sysconfig(entries, cache, tmp_path, name, values, root)
    assert list(cache) == ["another"]
    assert entries[0] == ("another", "another.py", "PYMODULE")
    assert entries[1] == (name, str(tmp_path / (name + ".py")), "PYMODULE")
    new = "/runtime path"
    monkeypatch.setattr(sys, "prefix", new)
    scope = {}
    exec(Path(entries[1][1]).read_text(), scope)
    assert scope["build_time_vars"] == {**values, "prefix": new, "list": new + "/lib " + new,
                                        "flags": "-I" + new + "/inc"}


def native_zip(tmp_path, *, config="clean", extra=b"clean", nested=b"clean"):
    from PyInstaller.archive.writers import CArchiveWriter, ZlibArchiveWriter

    name = sysconfig._get_sysconfigdata_name()
    pyz = tmp_path / "modules.pyz"
    ZlibArchiveWriter(str(pyz), [(name, name + ".py", "PYMODULE")],
                      {name: compile("value = " + repr(config), name + ".py", "exec")})
    engine = tmp_path / "engine"
    CArchiveWriter(str(engine), [("archive.pyz", str(pyz), False, "z")], "Python")
    nested_zip = io.BytesIO()
    with zipfile.ZipFile(nested_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("fixture", nested)
    app = tmp_path / "app.zip"
    with zipfile.ZipFile(app, "w", zipfile.ZIP_DEFLATED) as archive:
        base = "Screen Organizer.app/Contents/"
        archive.writestr(base + "MacOS/HomeScreenOrganizer", extra)
        archive.write(engine, base + "Resources/engine/engine")
        archive.writestr(base + "Resources/engine/_internal/base_library.zip", nested_zip.getvalue())
    return app


@pytest.mark.parametrize("location", ["config", "extra", "nested"])
def test_compiled_and_nested_artifact_paths(tmp_path, location):
    pytest.importorskip("PyInstaller")
    from macapp.check_package_paths import check_archive

    marker = "/private/build-fixture"
    path = native_zip(tmp_path, **{location: marker if location == "config" else marker.encode()})
    if location == "config":
        assert marker.encode() not in (tmp_path / "engine").read_bytes()
    with pytest.raises(ValueError, match="build path") as error:
        check_archive(path, [Path(marker)])
    assert marker not in str(error.value)


def test_unrelated_runner_builds_are_allowed(tmp_path):
    pytest.importorskip("PyInstaller")
    from macapp.check_package_paths import check_archive

    archive = native_zip(tmp_path, config="/Users/runner/work/dependency/src")
    check_archive(archive, [Path("/Users/runner/work/app")])


@pytest.mark.parametrize("document", ["home_screen_organizer-1.3.0.dist-info/METADATA",
                                      "home_screen_organizer.egg-info/PKG-INFO"])
def test_analysis_collects_project_version_document(document):
    from macapp.frozen_engine import project_metadata

    dependency = "tool-2.0.dist-info/entry_points.txt"
    files = [document, "home_screen_organizer-1.3.0.dist-info/direct_url.json",
             "home_screen_organizer.egg-info/SOURCES.txt", dependency,
             "home_screen_organizer_plugin-2.0.dist-info/RECORD", "homescreen/web/index.html"]
    data = [(name, "source", "DATA") for name in files]
    assert project_metadata(data, document) == [data[i] for i in (0, 3, 4, 5)]
