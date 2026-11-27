"""Render the Asarak social-brand-kit PNGs with headless Chromium (Playwright).

Every asset is authored at 1x CSS pixels and captured at deviceScaleFactor 2,
so Arabic shaping is done by the browser's text engine (HarfBuzz + DirectWrite)
and the exported PNG lands on the exact target pixel dimensions.

    python src/render.py              # render all 7 assets
    python src/render.py --only 03 07 # re-render a subset
    python src/render.py --list       # show the manifest

Fully offline: fonts and logo are bundled, any non-file request is blocked.
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib
import sys

from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright

SRC = pathlib.Path(__file__).resolve().parent
KIT = SRC.parent
SCALE = 2  # deviceScaleFactor

# file, source, query, css size (1x) -> output size = css * SCALE
MANIFEST: list[tuple[str, str, str, int, int]] = [
    ("01_profile_avatar_primary.png", "avatar.html", "variant=primary", 540, 540),    # 1080x1080
    ("02_profile_avatar_alt.png", "avatar.html", "variant=alt", 540, 540),             # 1080x1080
    ("03_facebook_cover.png", "facebook-cover.html", "", 820, 462),                    # 1640x924
    ("04_youtube_banner.png", "youtube-banner.html", "", 1280, 720),                   # 2560x1440
    ("05_x_twitter_header.png", "x-header.html", "", 750, 250),                        # 1500x500
    ("06_linkedin_banner.png", "linkedin-banner.html", "", 1128, 191),                 # 2256x382
    ("07_og_share_cover.png", "og-cover.html", "", 600, 315),                          # 1200x630
]

READY = """() => {
  const a = document.querySelector('.asset');
  if (!a || document.fonts.status !== 'loaded') return false;
  const r = a.getBoundingClientRect();
  return r.width === innerWidth && r.height === innerHeight;
}"""


def guard(route) -> None:
    """The kit is self-contained: refuse anything that is not a local file."""
    if route.request.url.startswith(("file://", "data:", "blob:")):
        route.continue_()
    else:
        route.abort()


def render(page, source: str, query: str, css_w: int, css_h: int, dst: pathlib.Path | None = None,
           hide: str = "") -> Image.Image:
    """Load one source at 1x and capture it. `hide` is a CSS selector to make
    invisible first (used by verify.py to isolate background vs foreground)."""
    url = (SRC / source).as_uri() + (f"?{query}" if query else "")
    page.set_viewport_size({"width": css_w, "height": css_h})
    page.goto(url)
    page.wait_for_function(READY, timeout=30_000)
    if hide:
        page.add_style_tag(content=f"{hide}{{visibility:hidden !important}}")
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    buf = page.screenshot(clip={"x": 0, "y": 0, "width": css_w, "height": css_h})
    im = Image.open(io.BytesIO(buf)).convert("RGB")
    if dst:
        im.save(dst, optimize=True)
    return im


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", default=[], help="asset numbers to render, e.g. 01 03")
    ap.add_argument("--list", action="store_true", help="print the manifest and exit")
    args = ap.parse_args()

    if args.list:
        for name, src, _q, w, h in MANIFEST:
            print(f"{name:30s} {src:22s} css {w}x{h}  ->  {w * SCALE}x{h * SCALE}")
        return 0

    todo = [m for m in MANIFEST if not args.only or m[0][:2] in args.only]
    if args.only and len(todo) != len(args.only):
        print(f"unknown asset id in {args.only}", file=sys.stderr)
        return 2

    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(device_scale_factor=SCALE)
        page = ctx.new_page()
        problems: list[str] = []
        page.on("requestfailed", lambda r: problems.append(f"request failed: {r.url}"))
        page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
        page.route("**/*", guard)

        for name, src, query, w, h in todo:
            dst = KIT / name
            im = render(page, src, query, w, h, dst)
            expected = (w * SCALE, h * SCALE)
            stat = ImageStat.Stat(im.convert("L"))
            ok = im.size == expected and max(stat.stddev) > 1.0 and not problems
            print(f"{'ok ' if ok else 'FAIL'} {name:30s} {im.size[0]}x{im.size[1]}  "
                  f"stddev={stat.stddev[0]:.1f}  {dst.stat().st_size // 1024} KB")
            if not ok:
                failures += 1
                if problems:
                    print("     " + " | ".join(problems))
                    problems.clear()
        browser.close()

    print(f"\n{len(todo) - failures}/{len(todo)} rendered -> {KIT}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
