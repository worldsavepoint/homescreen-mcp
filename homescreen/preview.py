"""Static HTML preview of the draft next to the original, with real icons."""

from __future__ import annotations

import base64
import html
from pathlib import Path

from .model import Layout, Node
from .session import Session

CSS = """
:root{--bg:#f4f4f6;--fg:#1c1c1e;--card:#fff;--muted:#8e8e93;--line:#d1d1d6}
@media (prefers-color-scheme:dark){:root{--bg:#000;--fg:#f2f2f7;--card:#1c1c1e;--muted:#8e8e93;--line:#38383a}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px -apple-system,system-ui,sans-serif}
h1{font-size:20px;margin:0 0 4px} .sub{color:var(--muted);margin-bottom:16px}
.row{display:flex;gap:16px;overflow-x:auto;padding-bottom:12px}
.phone{flex:0 0 auto;width:236px;background:var(--card);border:1px solid var(--line);border-radius:22px;padding:12px}
.phone h3{margin:0 0 8px;font-size:12px;color:var(--muted);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(4,52px);grid-auto-rows:62px;gap:4px}
.cell{display:flex;flex-direction:column;align-items:center;font-size:9px;text-align:center;overflow:hidden}
.cell img,.ph{width:44px;height:44px;border-radius:10px;background:var(--line)}
.cell span{width:52px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}
.folder .ph{display:grid;grid-template-columns:repeat(3,1fr);padding:4px;box-sizing:border-box;gap:2px}
.folder .ph img{width:11px;height:11px;border-radius:3px}
.w-small{grid-column:span 2;grid-row:span 2}.w-medium{grid-column:span 4;grid-row:span 2}
.w-large{grid-column:span 4;grid-row:span 4}
.widget{background:var(--line);border-radius:14px;display:flex;align-items:center;justify-content:center;
 font-size:10px;color:var(--muted);padding:4px;text-align:center}
.moved img{outline:2px solid #ff9f0a;outline-offset:1px}
"""


async def render(session: Session, out: Path, show_original: bool = True) -> Path:
    lay = session.require()
    cache: dict[str, str] = {}
    moved = {k.rsplit("[", 1)[-1].rstrip("]") for k in lay.diff()["moves"]}

    async def img(node: Node, cls: str = "") -> str:
        if not node.bundle_id:
            return f'<div class="ph {cls}"></div>'
        if node.bundle_id not in cache:
            png = await session.icon(node.bundle_id)
            cache[node.bundle_id] = (f'<img src="data:image/png;base64,{base64.b64encode(png).decode()}">'
                                     if png else '<div class="ph"></div>')
        return cache[node.bundle_id]

    async def cell(node: Node, mark: bool) -> str:
        name = html.escape(node.name)
        if node.kind == "widget":
            size = str(node.raw.get("gridSize", "small")).lower()
            if size not in {"small", "medium", "large", "extralarge"}:
                size = "small"
            return f'<div class="widget w-{size}">{name}</div>'
        if node.kind == "folder":
            inner = "".join([await img(c) for p in node.children for c in p][:9])
            return f'<div class="cell folder"><div class="ph">{inner}</div><span>{name}</span></div>'
        cls = "cell moved" if mark and node.id in moved else "cell"
        return f'<div class="{cls}">{await img(node)}<span>{name}</span></div>'

    async def phone(layout: Layout, title: str, mark: bool) -> str:
        parts = []
        sections = [("Dock", layout.dock)] + [(f"Page {i}", p) for i, p in enumerate(layout.pages, 1)]
        if layout.library:
            sections.append(("App Library only", layout.library))
        for label, nodes in sections:
            cells = "".join([await cell(n, mark) for n in nodes])
            parts.append(f'<div class="phone"><h3>{title} · {label}</h3><div class="grid">{cells}</div></div>')
        return f'<div class="row">{"".join(parts)}</div>'

    d = lay.diff()
    body = [f"<h1>Home Screen draft</h1><div class='sub'>{d['items_moved']} items moved · "
            f"{d['pages_before']} → {d['pages_after']} pages · {d['to_app_library']} to App Library · "
            f"{'no problems' if not d['problems'] else html.escape('; '.join(d['problems']))}</div>",
            "<h2>Draft</h2>", await phone(lay, "Draft", True)]
    if show_original:
        body += ["<h2>On the phone now</h2>", await phone(lay.original(), "Current", False)]
    out.write_text(f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
                   f"content='width=device-width,initial-scale=1'><title>Home Screen Draft</title>"
                   f"<style>{CSS}</style></head><body>{''.join(body)}</body></html>")
    return out
