"""Authenticate immutable release inputs and inspect upstream source archives."""
import hashlib
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen
import zipfile

LOCKS = Path(__file__).with_name("sources")
BLOCK = 1024 * 1024
HEX = re.compile(r"[0-9a-f]{64}")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def relative_name(name):
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or any(p in ("", ".", "..", ".git") for p in name.split("/"))):
        raise ValueError("Expected a public relative source path")
    return name


def pin_name(pin):
    parsed = urlsplit(pin["url"])
    name = pin.get("name", unquote(parsed.path.rsplit("/", 1)[-1]))
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or "/" in name or not HEX.fullmatch(pin["sha256"])
            or type(pin["size"]) is not int or not 0 < pin["size"] <= 2 * 1024**3):
        raise ValueError("Invalid immutable source input")
    return relative_name(name)


def fetch(pin, cache, offline=False):
    name = pin_name(pin)
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / (pin["sha256"] + "-" + name)
    if (out.is_file() and not out.is_symlink() and out.stat().st_size == pin["size"]
            and sha256(out) == pin["sha256"]):
        return out
    if offline:
        raise ValueError(f"Missing verified source input: {name}")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as output:
            temporary = Path(output.name)
            with urlopen(pin["url"], timeout=45) as response:
                if urlsplit(response.geturl()).scheme != "https":
                    raise ValueError("Expected HTTPS for release sources")
                size = 0
                digest = hashlib.sha256()
                while chunk := response.read(BLOCK):
                    size += len(chunk)
                    if size > pin["size"]:
                        raise ValueError(f"Incorrect source size: {name}")
                    output.write(chunk)
                    digest.update(chunk)
        if size != pin["size"] or digest.hexdigest() != pin["sha256"]:
            raise ValueError(f"Incorrect source digest: {name}")
        os.replace(temporary, out)
        return out
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_locks():
    return (json.loads((LOCKS / "python.json").read_bytes()),
            json.loads((LOCKS / "native.json").read_bytes()))


def cache_directory():
    return Path(os.environ.get("HOMESCREEN_SOURCE_CACHE", Path.home() / ".cache/screen-organizer/sources"))


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def source_member(path, member):
    """Read a specific authenticated member verbatim, without extracting a tree."""
    relative_name(member)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo(member)
            if info.file_size > 32 * BLOCK or info.is_dir():
                raise ValueError("Unexpected source notice size or type")
            return archive.read(info)
    with tarfile.open(path) as archive:
        info = archive.getmember(member)
        if not info.isfile() or info.size > 32 * BLOCK:
            raise ValueError("Unexpected source notice size or type")
        return archive.extractfile(info).read()
