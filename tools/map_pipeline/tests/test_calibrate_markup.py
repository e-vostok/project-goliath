"""calibrate_markup — the map_polish_1 registration tool.

Two layers, both real files (no mocks):

- a synthetic fixture: a tiny geometry/manifest pair and a markup image
  fabricated as an exact pixel crop of the same land mask at a known
  scale/offset — the search must recover the transform;
- the real acceptance run: ``data/map`` vs the committed
  ``reference/boundary_v2_markup.png`` must register at IoU >= 0.95 and
  produce the registration JSON + overlay that map_polish_2 consumes.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tools.map_pipeline import calibrate_markup as cm

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_DATA_DIR = REPO_ROOT / "data" / "map"
REFERENCE_DIR = (
    Path(cm.__file__).resolve().parent / "reference"
)

_LAND_RGB = (140, 140, 140)
_WATER_RGB = (30, 53, 71)

# A small world with irregular, non-translatable structure for the
# coarse FFT stage: excluded-land blob (outside), several playable LAND
# shapes, water = everything else; view_box 0..100 x 0..80.
_GEOMETRY = {
    "outside": "M 5 5 45 5 48 20 45 35 20 38 5 35 Z",
    "paths": {
        "1": "M 10 45 25 45 18 60 Z",
        "3": "M 50 50 62 50 62 66 56 70 50 66 Z",
        "4": "M 75 40 95 44 90 55 75 55 Z",
        "5": "M 65 60 78 62 75 75 60 70 Z",
        "2": "M 60 15 80 15 80 30 60 30 Z",
    },
}
_MANIFEST = {
    "view_box": [0.0, 0.0, 100.0, 80.0],
    "nodes": [
        {"id": 1, "kind": "LAND"},
        {"id": 2, "kind": "SEA"},
        {"id": 3, "kind": "LAND"},
        {"id": 4, "kind": "LAND"},
        {"id": 5, "kind": "LAND"},
    ],
}


def _fabricate_markup(
    geometry: dict, sea_ids: set[str], view_box, ppu: float
) -> Image.Image:
    """The Owner's image, faked: the land mask painted in his palette."""
    mask = cm.render_land_mask(geometry, sea_ids, view_box, ppu)
    arr = np.where(
        np.asarray(mask)[..., None] > 0, _LAND_RGB, _WATER_RGB
    ).astype(np.uint8)
    return Image.fromarray(arr, "RGB").convert("RGBA")


class TestSynthetic:
    """Recover a transform fabricated on the same renderer."""

    @pytest.mark.parametrize(
        "ox,oy,ppu,w,h",
        [
            (8.0, 4.0, 6.0, 480, 320),   # round ppu — the real-world case
            (3.5, 4.25, 4.0, 320, 280),  # non-integer offset, other scale
        ],
    )
    def test_recovers_known_transform(self, ox, oy, ppu, w, h):
        crop = [ox, oy, ox + w / ppu, oy + h / ppu]
        img = _fabricate_markup(
            _GEOMETRY, {"2"}, crop, ppu
        )
        land, valid = cm.classify_image(img)
        assert valid.all()

        base_img = cm.render_land_mask(
            _GEOMETRY, {"2"}, _MANIFEST["view_box"], cm._PPU_HI
        )
        fit = cm.calibrate(land, valid, base_img, cm._PPU_HI)

        assert fit.scale == pytest.approx(ppu, abs=0.02)
        assert fit.offset[0] == pytest.approx(ox, abs=0.15)
        assert fit.offset[1] == pytest.approx(oy, abs=0.15)
        assert fit.iou >= cm._IOU_MIN

    def test_classify_image_palette(self):
        """Border pixels are ignored; land/water split cleanly."""
        img = Image.new("RGBA", (4, 4), _WATER_RGB + (255,))
        px = img.load()
        px[0, 0] = _LAND_RGB + (255,)
        px[1, 1] = (58, 58, 58, 255)  # province border — ignored
        land, valid = cm.classify_image(img)
        assert land[0, 0] and not land[0, 1]
        assert not land[1, 1] and not valid[1, 1]
        assert land.sum() == 1 and valid.sum() == 15


@pytest.fixture(scope="module")
def real_calibration(tmp_path_factory):
    """One real ``cm.run`` shared by the acceptance tests."""
    out_dir = tmp_path_factory.mktemp("calibration")
    return cm.run(
        REAL_DATA_DIR,
        REFERENCE_DIR / cm.MARKUP_IMAGE,
        out_dir,
    ), out_dir


@pytest.mark.real_data
@pytest.mark.skipif(
    not (REAL_DATA_DIR / "geometry.json").exists()
    or not (REFERENCE_DIR / cm.MARKUP_IMAGE).exists(),
    reason="real map data or markup image absent",
)
class TestRealMarkup:
    """The committed markup registers against data/map at IoU >= 0.95."""

    def test_iou_acceptance(self, real_calibration):
        f, _ = real_calibration
        assert f.iou >= cm._IOU_MIN
        # The image is a crop of the 6 px/unit preview render.
        assert f.scale == pytest.approx(6.0, abs=0.02)

    def test_registration_document(self, real_calibration):
        _, out_dir = real_calibration
        doc = json.loads(
            (out_dir / cm.REGISTRATION).read_text(encoding="utf-8")
        )
        assert doc["image_size"] == [1328, 1304]
        assert doc["scale"] > 0
        assert len(doc["offset"]) == 2
        assert doc["iou"] >= cm._IOU_MIN
        rect = doc["base_rect"]
        # The whole image rectangle must fit inside the real view_box.
        assert rect["x"] >= 0 and rect["y"] >= 0
        assert rect["x"] + rect["width"] <= 1200
        assert rect["y"] + rect["height"] <= 680
        assert "px -> base" in doc["_comment"]

    def test_overlay_written(self, real_calibration):
        _, out_dir = real_calibration
        overlay = Image.open(out_dir / cm.OVERLAY)
        assert overlay.size == (1328, 1304)
        assert overlay.mode == "RGBA"
        # Cyan outline pixels must actually be present.
        arr = np.asarray(overlay)
        cyan = (
            (arr[..., 0] == 0)
            & (arr[..., 1] == 255)
            & (arr[..., 2] == 255)
        )
        assert cyan.sum() > 1000
