"""Verify the Asarak social-brand-kit against its safe-zone spec.

Checks, per asset:
  1. exported PNG exists at the exact target pixel size
  2. exported PNG is current (identical to a fresh render of its source)
  3. no foreground ink outside the safe zone / inside a keep-clear zone
  4. every foreground element's ink box, plus pairwise collisions
  5. headroom left between the ink and the safe-zone edges

Zones are read from preview.html (its <script id="safe-zones"> block), so the
gallery overlays and this checker can never disagree.

    python src/verify.py
"""
from __future__ import annotations

import io
import json
import pathlib
import re
import sys

from PIL import Image, ImageChops, ImageDraw
from playwright.sync_api import sync_playwright

from render import KIT, MANIFEST, SCALE, SRC, guard, render

INK_THRESHOLD = 24  # max channel delta that still counts as "background"


def load_zones() -> dict:
    html = (KIT / "preview.html").read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="safe-zones">(.*?)</script>', html, re.S)
    if not m:
        raise SystemExit("preview.html: safe-zones block not found")
    return {a["file"]: a for a in json.loads(m.group(1))["assets"]}


def ink_mask(fg_visible: Image.Image, bg_only: Image.Image) -> Image.Image:
    """255 where the foreground changed a pixel, 0 elsewhere."""
    r, g, b = ImageChops.difference(fg_visible, bg_only).convert("RGB").split()
    return ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v > INK_THRESHOLD else 0)


def shape_mask(size, shape: dict) -> Image.Image:
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    if shape["type"] == "rect":
        d.rectangle([shape["x"], shape["y"], shape["x"] + shape["w"] - 1, shape["y"] + shape["h"] - 1], fill=255)
    else:
        cx, cy, r = shape["cx"], shape["cy"], shape["r"]
        d.ellipse([cx - r, cy - r, cx + r - 1, cy + r - 1], fill=255)
    return m


def element_boxes(page, url: str, cw: int, ch: int, bg_only: Image.Image) -> list[tuple[str, tuple]]:
    """Ink bounding box of every direct child of .fg (device px)."""
    clip = {"x": 0, "y": 0, "width": cw, "height": ch}
    page.goto(url)
    count = page.evaluate("document.querySelectorAll('.fg > *').length")
    boxes = []
    for i in range(1, count + 1):
        page.goto(url)
        page.wait_for_function("document.fonts.status === 'loaded'")
        page.add_style_tag(content=f".fg > *:not(:nth-child({i})){{visibility:hidden !important}}")
        page.wait_for_timeout(30)
        bb = ink_mask(Image.open(io.BytesIO(page.screenshot(clip=clip))).convert("RGB"), bg_only).getbbox()
        if bb:
            label = page.evaluate(f"document.querySelector('.fg > :nth-child({i})').className.split(' ')[0]")
            boxes.append((label, bb))
    return boxes


def overlap(a, b) -> int:
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def verify_asset(ctx, zones: dict, name: str, src: str, query: str, cw: int, ch: int) -> list[str]:
    fails: list[str] = []
    url = (SRC / src).as_uri() + (f"?{query}" if query else "")

    page = ctx.new_page()
    page.route("**/*", guard)
    full = render(page, src, query, cw, ch)
    bg = render(page, src, query, cw, ch, hide=".fg")
    boxes = element_boxes(page, url, cw, ch, bg)
    page.close()

    path = KIT / name
    if not path.exists():
        return [f"{name}: missing file"]
    saved = Image.open(path).convert("RGB")
    expected = (cw * SCALE, ch * SCALE)
    if saved.size != expected:
        fails.append(f"{name}: size {saved.size} != expected {expected}")
    elif ImageChops.difference(saved, full).getbbox() is not None:
        fails.append(f"{name}: PNG is stale (differs from a fresh render) — re-run src/render.py")

    mask = ink_mask(full, bg)
    ink = mask.getbbox()
    z = zones.get(name)
    if z is None:
        return fails + [f"{name}: no entry in preview.html safe-zones"]

    for shape in z.get("safe", []):
        stray = ImageChops.subtract(mask, shape_mask(mask.size, shape)).getbbox()
        if stray:
            fails.append(f"{name}: ink outside safe zone '{shape['label']}' at {stray}")
    for shape in z.get("avoid", []):
        hit = ImageChops.multiply(mask, shape_mask(mask.size, shape)).getbbox()
        if hit:
            fails.append(f"{name}: ink inside keep-clear zone '{shape['label']}' at {hit}")

    print(f"\n{name}  {saved.size[0]}x{saved.size[1]}")
    print(f"  ink bbox            {ink}")
    for label, bb in boxes:
        print(f"    {label:<14s} x {bb[0]:>4}->{bb[2]:<5} y {bb[1]:>4}->{bb[3]:<5} ({bb[2] - bb[0]}x{bb[3] - bb[1]})")
    hits = [(a[0], b[0]) for i, a in enumerate(boxes) for b in boxes[i + 1:] if overlap(a[1], b[1])]
    if hits:
        fails.append(f"{name}: overlapping foreground elements {hits}")
    if ink:
        for shape in z.get("safe", []):
            if shape["type"] == "rect":
                l, t, r, b = ink
                head = (l - shape["x"], t - shape["y"], shape["x"] + shape["w"] - r, shape["y"] + shape["h"] - b)
                print(f"  headroom L/T/R/B    {head[0]} / {head[1]} / {head[2]} / {head[3]} px")
                if min(head) < 0:
                    fails.append(f"{name}: negative headroom {head}")
            elif shape["type"] == "circle":
                cx, cy, r = shape["cx"], shape["cy"], shape["r"]
                far = 0
                for x in range(ink[0], ink[2]):
                    for y in range(ink[1], ink[3]):
                        if mask.getpixel((x, y)) and ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 > far:
                            far = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                print(f"  farthest ink        r = {far:.0f} px of {r} px safe circle ({far / r:.1%})")
    return fails


def main() -> int:
    zones = load_zones()
    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(device_scale_factor=SCALE)
        for name, src, query, cw, ch in MANIFEST:
            failures += verify_asset(ctx, zones, name, src, query, cw, ch)
        browser.close()
    print("\n" + ("PASS - every asset respects its safe zones" if not failures else "FAIL"))
    for f in failures:
        print("  x", f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
