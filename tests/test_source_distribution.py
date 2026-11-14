"""Native distributions supply the exact editable inputs and copyright notices."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macapp"))


def test_source_lock_covers_known_frozen_owners():
    lock = ROOT / "macapp/sources/python.json"
    assert lock.is_file(), "The release needs component source pins"
    packages = json.loads(lock.read_text())
    assert packages["h11"]["version"] == "0.16.0"
    assert packages["pymobiledevice3"]["source"]["sha256"] == "097eefb68b9f04f33d564c122a78b7d2d7d71437c0a438f0a086954e755ccd29"
    assert packages["pyinstaller-hooks-contrib"]["wheels"]["x86_64"]
    assert packages["pylzss"]["license"] == "LGPL-3.0-only"
    assert "asttokens" not in packages


def test_cached_input_must_match_digest_and_size(tmp_path):
    import source_inputs
    content = b"verified source\n"
    digest = hashlib.sha256(content).hexdigest()
    pin = {"url": "https://example.org/releases/project.tar.gz", "size": len(content), "sha256": digest}
    (tmp_path / (digest + "-project.tar.gz")).write_bytes(content)
    assert source_inputs.fetch(pin, tmp_path, offline=True).read_bytes() == content
    (tmp_path / (digest + "-project.tar.gz")).write_bytes(b"x" * len(content))
    with pytest.raises(ValueError, match="verified source"):
        source_inputs.fetch(pin, tmp_path, offline=True)


@pytest.mark.parametrize("name", ["/outside", "a/../../outside", "a//b", r"a\b", ".git/config", "a\nline"])
def test_public_names_reject_unsafe_members(name):
    import source_inputs
    with pytest.raises(ValueError):
        source_inputs.relative_name(name)



def test_exact_wheel_record_ownership_uses_full_path(tmp_path):
    from frozen_sources import installed_files
    from importlib.metadata import distributions
    for name in ("first", "second"):
        info = tmp_path / (name + "-1.0.dist-info")
        info.mkdir()
        (info / "METADATA").write_text("Metadata-Version: 2.1\nName: " + name + "\nVersion: 1.0\n")
        (info / "RECORD").write_text(name + "/shared.py,,\n")
        (tmp_path / name).mkdir()
        (tmp_path / name / "shared.py").write_text(name)
    files = installed_files(distributions(path=[str(tmp_path)]))
    assert files[tmp_path / "first/shared.py"][:2] == ("first", "1.0")
    assert files[tmp_path / "second/shared.py"][:2] == ("second", "1.0")
    (tmp_path / "second-1.0.dist-info/RECORD").write_text("first/shared.py,,\n")
    with pytest.raises(ValueError, match="Multiple owners"):
        installed_files(distributions(path=[str(tmp_path)]))


def test_notices_and_overlays_compare_exact_wheel_bytes(tmp_path):
    import io
    import tarfile
    import zipfile
    from frozen_sources import wheel_material
    wheel = tmp_path / "demo.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr("demo/payload.py", "x = 2\n")
        z.writestr("demo/identical.py", "x = 1\n")
        z.writestr("demo-1.0.dist-info/licenses/a/LICENSE", b"First upstream notice\n")
        z.writestr("demo-1.0.dist-info/licenses/b/LICENSE", b"Second upstream notice\n")
    source = tmp_path / "demo.tar.gz"
    with tarfile.open(source, "w:gz") as tar:
        for name in ("payload", "identical"):
            info = tarfile.TarInfo("demo-1.0/src/demo/" + name + ".py")
            info.size = len(b"x = 1\n")
            tar.addfile(info, io.BytesIO(b"x = 1\n"))
    notice = tmp_path / "notices"
    overlays = tmp_path / "overlays"
    with zipfile.ZipFile(wheel) as z:
        wheel_material("demo", z, source, {"demo/payload.py", "demo/identical.py"}, notice, overlays)
    assert (notice / "demo/demo-1.0.dist-info/licenses/a/LICENSE").read_bytes() == b"First upstream notice\n"
    assert (notice / "demo/demo-1.0.dist-info/licenses/b/LICENSE").read_bytes() == b"Second upstream notice\n"
    assert (overlays / "demo/demo/payload.py").read_bytes() == b"x = 2\n"
    assert not (overlays / "demo/demo/identical.py").exists()



def test_native_lock_contains_build_sources_and_pinned_interpreters():
    native_file = ROOT / "macapp/sources/native.json"
    assert native_file.is_file(), "Native libraries need pinned source and provider inputs"
    native = json.loads(native_file.read_text())
    table = {entry["id"]: entry for entry in native["assets"]}
    for name in ("avif/aom", "avif/dav1d", "avif/libyuv", "pbs-sources/uuid", "pbs/recipe", "pillow/multibuild"):
        assert table[name]["size"] > 0
    assert table["openssl/4.0.3"]["sha256"] == "325b5c806167c13b40b1ffeadfe0248197c00eccc4cf123ec1e28d2d2fd216d9"
    assert {v["role"] for v in table.values()} >= {"cargo-source", "interpreter-source", "native-build-recipe"}
    assert native["runtime"]["arm64"]["libpython"] == "16d39098fb247e8386e112396a6ebccbcc89586155af7adce89c2f5428287ba9"
    assert native["runtime"]["x86_64"]["libpython"] == "baf4fc3516b40b2f1a48522543bad9762a11890e23830bee9eeb9c2f51d16c25"



def test_release_selects_editable_pure_chardet_on_both_architectures():
    uri = "https://files.pythonhosted.org/packages/cc/75/88a3eb36264375ff951bd2f9397c409727ab6aa6a18e1bd933851571d421/chardet-7.7.0-py3-none-any.whl"
    checksum = "11cf9b719ea3675a2a7d8a3071bbe4d7ea24b26bfe39a51588d515ddd05cacad"
    for name in ("requirements-build.lock", "requirements-build-x86_64.lock"):
        assert f"chardet @ {uri} --hash=sha256:{checksum}" in (ROOT / name).read_text().splitlines()



def test_source_archive_rejects_unsafe_metadata_and_rebuilds_reproducibly(tmp_path):
    import io
    import tarfile
    from source_archive import payload_tar, verify_tar

    def inputs():
        yield "project/macapp/build.sh", 0o755, io.BytesIO(b"build"), 5
        yield "sources/h11.tar.gz", 0o644, io.BytesIO(b"source"), 6
    hashes = []
    for index in range(2):
        output = tmp_path / str(index)
        payload_tar(output, inputs(), {"version": "1.3.0", "commit": "a" * 40, "architectures": {}})
        verify_tar(output, version="1.3.0", commit="a" * 40)
        hashes.append(hashlib.sha256(output.read_bytes()).hexdigest())
        with tarfile.open(output) as archive:
            assert archive.extractfile("project/macapp/build.sh").read() == b"build"
            assert archive.getmember("project/macapp/build.sh").mode == 0o755
    assert hashes[0] == hashes[1]
    with pytest.raises(ValueError):
        verify_tar(output, version="1.3.0", commit="b" * 40)
    with pytest.raises(ValueError):
        payload_tar(tmp_path / "unsafe", [("../outside", 0o644, io.BytesIO(b"x"), 1)], {})



def test_editable_component_extracts_under_one_directory(tmp_path):
    import io
    import tarfile
    from rebuild_sources import unpack_source
    archive = tmp_path / "editable.tar"
    with tarfile.open(archive, "w") as tar:
        for name in ("demo-1/setup.py", "demo-1/src/demo.py"):
            member = tarfile.TarInfo(name)
            member.size = len(b"x = 1\n")
            tar.addfile(member, io.BytesIO(b"x = 1\n"))
    output = tmp_path / "editable"
    unpack_source(archive, output)
    assert (output / "src/demo.py").read_text() == "x = 1\n"
    with tarfile.open(archive, "w") as tar:
        link = tarfile.TarInfo("demo-1/escape")
        link.type, link.linkname = tarfile.SYMTYPE, "../../outside"
        tar.addfile(link)
    with pytest.raises(ValueError):
        unpack_source(archive, tmp_path / "bad")


def test_local_refreeze_records_actual_substitution_and_stays_outside_release(tmp_path):
    from rebuild_sources import local_selections
    original = tmp_path / "original.lock"
    edited = tmp_path / "edited.lock"
    original.write_text("# h11-0.16.0-py3-none-any.whl\nh11==0.16.0 --hash=sha256:" + "a" * 64 + "\n")
    edited.write_text(original.read_text().replace("a" * 64, "b" * 64))
    assert local_selections(original, edited, {"h11"}) == {"h11": {"upstreamWheel": "a" * 64, "wheel": "b" * 64}}
    edited.write_text(edited.read_text().replace("h11", "other"))
    with pytest.raises(ValueError, match="release component"):
        local_selections(original, edited, {"h11"})



def test_signed_inventory_and_source_header_are_required(tmp_path):
    from source_archive import check_zip
    from test_mcp_bundle import assets
    folder = assets(tmp_path)
    package = folder / "home-screen-organizer-1.3.0-macos-arm64.zip"
    altered = {"arch": "arm64", "version": "1.3.0"}
    with pytest.raises(ValueError, match="signed source inventory"):
        check_zip(package, altered)
    pins = json.loads((ROOT / "macapp/sources/python.json").read_bytes())
    assert "pylzss-0.3.9/src/include/py3c.h" in pins["pylzss"]["notices"]


def test_local_extract_skips_git_pointer_and_checks_promoted_root(tmp_path):
    import io
    import tarfile
    from rebuild_sources import unpack_source
    path = tmp_path / "source.tar"
    with tarfile.open(path, "w") as tar:
        for name, data in [("project/source.py", b"x = 1"), ("project/suite/.git", b"gitdir: ../.git/modules/suite\n")]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    unpack_source(path, tmp_path / "good")
    assert (tmp_path / "good/source.py").is_file()
    assert not (tmp_path / "good/suite/.git").exists()
    with tarfile.open(path, "w") as tar:
        link = tarfile.TarInfo("project/untrusted")
        link.type, link.linkname = tarfile.SYMTYPE, "../promoted-outside"
        tar.addfile(link)
    with pytest.raises(ValueError, match="link"):
        unpack_source(path, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_provider_matches_actual_collected_stdlib(tmp_path):
    import io
    import tarfile
    from native_sources import verify_provider_files
    path = tmp_path / "runtime.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo("python/lib/python3.12/stat.py")
        info.size = 7
        tar.addfile(info, io.BytesIO(b"trusted"))
    verify_provider_files(path, {"lib/python3.12/stat.py": hashlib.sha256(b"trusted").hexdigest()})
    with pytest.raises(ValueError, match="Python"):
        verify_provider_files(path, {"lib/python3.12/stat.py": hashlib.sha256(b"changed").hexdigest()})


def test_official_freeze_exports_clean_commit_and_excludes_ignored_files(tmp_path):
    import subprocess
    from source_checkout import export_project
    tree = tmp_path / "tree"
    tree.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", tree, *args], text=True).strip()
    git("init", "-q")
    (tree / "module.py").write_text("original")
    (tree / ".gitignore").write_text("local.py\n")
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.com", "-c", "commit.gpgsign=false", "commit", "-qm", "Fixture")
    (tree / "local.py").write_text("ignored")
    destination = tmp_path / "release"
    assert export_project(tree, destination) == git("rev-parse", "HEAD")
    assert (destination / "module.py").read_text() == "original" and not (destination / "local.py").exists()
    (tree / "module.py").write_text("edited")
    with pytest.raises(ValueError, match="clean release"):
        export_project(tree, tmp_path / "invalid")
