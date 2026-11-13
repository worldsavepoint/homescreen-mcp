# PyInstaller spec for the engine inside iOS Home Screen Organizer.app (onedir, so it starts fast).
import os
import platform

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hidden = [], [], []
for pkg in ("pymobiledevice3", "mcp", "uvicorn", "starlette", "sse_starlette"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h
datas += collect_data_files("homescreen")  # web assets and simulator icon reader source

a = Analysis(["engine.py"], pathex=[".."], binaries=binaries, datas=datas, hiddenimports=hidden + [
    "homescreen.ui", "homescreen.server", "homescreen.cli", "homescreen.preview"],
    excludes=["tkinter", "pytest", "IPython"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="engine", console=True, target_arch=os.environ.get("HOMESCREEN_BUILD_ARCH", platform.machine()))
coll = COLLECT(exe, a.binaries, a.datas, name="engine")
