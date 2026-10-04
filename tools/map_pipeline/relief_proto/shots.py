"""Take preview screenshots with headless Chromium/Chrome.

python -m tools.map_pipeline.relief_proto.shots
Writes reference/relief_shot_*.png (1920x1080).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import proto_common as pc
from .register import CROPS  # reuse crop centres (lon/lat)
from .transform import load as load_transform

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
WINDOW = "1920,1080"
Z1_W = 217.3 * 1920 / 1080   # visible width at z=1 (frame height fill)
ZOOM_W = 217.3 / 10.8 * 1920 / 1080  # visible width at zoom_max


def find_browser() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    raise SystemExit("no chromium/edge found")


def shot(browser, html, name, cx, cy, w, preset):
    """Screenshot via headless Chromium into a temp file, then move.

    (Chrome can't write into the repo dir from a sandboxed spawn, so the
    screenshot lands in the temp dir and is moved over by us.)
    """
    out = pc.REF_DIR / f"relief_shot_{name}.png"
    tmp = Path(tempfile.gettempdir()) / f"relief_shot_{name}.png"
    url = (html.as_uri()
           + f"#cx={cx:.2f}&cy={cy:.2f}&w={w:.2f}&preset={preset}")
    subprocess.run(
        [browser, "--headless", f"--window-size={WINDOW}",
         "--hide-scrollbars", "--disable-gpu",
         "--virtual-time-budget=20000",
         f"--screenshot={tmp}", url],
        check=True, capture_output=True, timeout=120)
    shutil.move(str(tmp), out)
    if out.stat().st_size > 1_400_000:
        from PIL import Image
        im = Image.open(out)
        im.quantize(colors=256, method=Image.MEDIANCUT,
                    dither=Image.FLOYDSTEINBERG).save(out, optimize=True)
    print(f"  {out.name} {out.stat().st_size // 1024} KB")


def main() -> int:
    browser = find_browser()
    html = pc.REF_DIR / "relief_preview.html"
    cfg = pc.load_map_config()
    f = cfg["view"]["frame"]
    tr = load_transform()

    cx = f["x"] + f["width"] / 2
    cy = f["y"] + f["height"] / 2
    for preset in ("pol", "rel"):
        shot(browser, html, f"overview_{preset}", cx, cy, Z1_W, preset)
    for name, (lon, lat) in CROPS.items():
        bx, by = tr.fwd(lon, lat)
        for preset in ("pol", "rel"):
            shot(browser, html, f"{name}_{preset}", float(bx), float(by),
                 ZOOM_W, preset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
