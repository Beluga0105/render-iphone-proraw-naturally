from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline  # noqa: E402


class LocalHighlightCheckTests(unittest.TestCase):
    def _analyze(self, pixels: np.ndarray) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.jpg"
            Image.fromarray(pixels).save(
                path,
                format="JPEG",
                quality=100,
                subsampling=0,
            )
            return pipeline._analyze_final_jpeg(path)

    def test_concentrated_clipping_triggers_when_global_average_passes(self) -> None:
        pixels = np.full((1600, 1200, 3), 80, dtype=np.uint8)
        pixels[1220:1280, 320:380] = 255

        report = self._analyze(pixels)
        local = report["metrics"]["local_highlight_check"]

        self.assertLess(report["metrics"]["white_clip_percent"], 1.0)
        self.assertLess(report["metrics"]["bright_highlight_percent"], 5.0)
        self.assertTrue(local["triggered"])
        self.assertGreater(local["peak_white_clip_percent"], 5.0)
        self.assertIn(
            "possible_local_overexposure: concentrated near-white or clipped region exceeds local thresholds; inspect peak_tile before delivery",
            report["warnings"],
        )

    def test_sparse_point_highlights_do_not_trigger_local_warning(self) -> None:
        pixels = np.full((1600, 1200, 3), 80, dtype=np.uint8)
        for y in range(50, 1600, 100):
            for x in range(50, 1200, 100):
                pixels[y, x] = 255

        report = self._analyze(pixels)
        local = report["metrics"]["local_highlight_check"]

        self.assertFalse(local["triggered"])
        self.assertNotIn(
            "possible_local_overexposure: concentrated near-white or clipped region exceeds local thresholds; inspect peak_tile before delivery",
            report["warnings"],
        )

    def test_concentrated_near_white_region_triggers_before_clipping(self) -> None:
        pixels = np.full((1600, 1200, 3), 80, dtype=np.uint8)
        pixels[1220:1280, 320:380] = 240

        report = self._analyze(pixels)
        local = report["metrics"]["local_highlight_check"]

        self.assertEqual(report["metrics"]["white_clip_percent"], 0.0)
        self.assertTrue(local["triggered"])
        self.assertGreater(local["peak_near_white_percent"], 20.0)
        self.assertIn(
            "possible_local_overexposure: concentrated near-white or clipped region exceeds local thresholds; inspect peak_tile before delivery",
            report["warnings"],
        )


if __name__ == "__main__":
    unittest.main()
