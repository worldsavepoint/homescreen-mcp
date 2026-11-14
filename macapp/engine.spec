# PyInstaller spec for the engine inside Home Screen Organizer.app (onedir, so it starts fast).
import os
import platform
from importlib.metadata import distribution

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hidden = [], [], []
for pkg in ("pymobiledevice3", "mcp", "uvicorn", "starlette", "sse_starlette"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h
# Include only the distribution metadata document used by the MCP handshake.
project = distribution("home-screen-organizer")
metadata = next(path for path in project.files if (path.name == "METADATA" and path.parent.name.endswith(".dist-info"))
                or (path.name == "PKG-INFO" and path.parent.name.endswith(".egg-info")))
datas.append((str(project.locate_file(metadata)), str(metadata.parent)))
datas += collect_data_files("homescreen")  # web assets and simulator icon reader source

a = Analysis(["engine.py"], pathex=[".."], binaries=binaries, datas=datas, hiddenimports=hidden + [
    "homescreen.ui", "homescreen.server", "homescreen.cli", "homescreen.preview"],
    excludes=["tkinter", "pytest", "IPython"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="engine", console=True, target_arch=os.environ.get("HOMESCREEN_BUILD_ARCH", platform.machine()))
coll = COLLECT(exe, a.binaries, a.datas, name="engine")
