"""Dominant icon color, so an agent can sort by color without looking at 300 images."""

from __future__ import annotations

import colorsys
import io
import warnings
from collections import Counter

from PIL import Image

FAMILIES = [(15, "red"), (40, "orange"), (65, "yellow"), (160, "green"), (200, "teal"),
            (255, "blue"), (290, "purple"), (335, "pink"), (360, "red")]


def family(h: float, s: float, l: float) -> str:
    if l < 0.15:
        return "black"
    if s < 0.18:
        return "white" if l > 0.8 else "gray"
    deg = h * 360
    return next(name for limit, name in FAMILIES if deg < limit)


def _pick(bins: Counter) -> tuple[float, float, float]:
    (hq, sq, lq), _ = bins.most_common(1)[0]
    return hq / 24, sq / 4, lq / 4


def dominant(png: bytes) -> dict:
    """Main color of an icon. A colorful glyph on a white/black tile (News, Health) counts
    as its glyph color when it covers enough of the icon; the tile color is in 'background'."""
    if len(png) > 4 * 1024 * 1024:
        raise ValueError("PNG icon is too large")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(png), formats=["PNG"]) as source:
                if max(source.size) > 2048:
                    raise ValueError("PNG icon is too large")
                source.verify()
            with Image.open(io.BytesIO(png), formats=["PNG"]) as source:
                img = source.convert("RGBA").resize((32, 32))
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Invalid or too large PNG icon") from exc
    bins: Counter = Counter()
    vivid: Counter = Counter()
    total = 0
    pixels = img.get_flattened_data() if hasattr(img, "get_flattened_data") else img.getdata()
    for r, g, b, a in pixels:
        if a < 128:
            continue
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        # quantize; weight saturated pixels higher so a white glyph on red reads as red
        key = (round(h * 24) % 24, round(s * 4), round(l * 4))
        bins[key] += 1 + 2 * s
        if s > 0.35 and 0.2 < l < 0.85:
            vivid[key] += 1
        total += 1
    if not total:
        return {"family": "unknown"}
    background = family(*_pick(bins))
    if background in ("white", "black", "gray") and sum(vivid.values()) >= 0.12 * total:
        h, s, l = _pick(vivid)
    else:
        h, s, l = _pick(bins)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return {
        "family": family(h, s, l),
        "background": background,
        "hex": "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255)),
        "hue": round(h * 360),
        "saturation": round(s, 2),
        "lightness": round(l, 2),
    }
