from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline  # noqa: E402


def _luma(image: np.ndarray) -> np.ndarray:
    return np.sum(image * pipeline.P3_LUMA, axis=2)


class RegionalShadowRecoveryTests(unittest.TestCase):
    def test_auto_lifts_dense_foreground_without_changing_bright_sky(self) -> None:
        image = np.empty((600, 800, 3), dtype=np.float32)
        image[:300] = (0.34, 0.62, 0.84)
        image[300:] = (0.075, 0.105, 0.065)
        before = image.copy()

        report = pipeline._recover_regional_shadows_inplace(image, "auto", 1.0)

        self.assertTrue(report["applied"])
        self.assertEqual(report["reason"], "well_exposed_upper_region_with_dense_foreground")
        self.assertLess(float(np.max(np.abs(image[:260] - before[:260]))), 1e-6)
        self.assertGreater(float(np.mean(_luma(image)[400:] - _luma(before)[400:])), 0.01)
        self.assertLessEqual(report["maximum_actual_lift_ev"], pipeline.REGIONAL_MAX_LIFT_EV + 1e-6)
        self.assertEqual(report["protected_region_mean_luma_change"], 0.0)

    def test_auto_skips_uniform_scene(self) -> None:
        image = np.full((480, 640, 3), 0.27, dtype=np.float32)
        before = image.copy()

        report = pipeline._recover_regional_shadows_inplace(image, "auto", 1.0)

        self.assertFalse(report["applied"])
        self.assertEqual(report["reason"], "scene_does_not_need_regional_shadow_recovery")
        np.testing.assert_array_equal(image, before)

    def test_auto_skips_dark_night_with_only_small_lights(self) -> None:
        image = np.full((600, 800, 3), (0.055, 0.075, 0.10), dtype=np.float32)
        image[500:520, 100:140] = (0.95, 0.78, 0.42)
        before = image.copy()

        report = pipeline._recover_regional_shadows_inplace(image, "auto", 1.0)

        self.assertFalse(report["applied"])
        np.testing.assert_array_equal(image, before)

    def test_forced_mode_preserves_highlights_and_true_black(self) -> None:
        image = np.full((500, 700, 3), (0.07, 0.10, 0.06), dtype=np.float32)
        image[:180] = (0.32, 0.58, 0.82)
        image[350:390, 100:180] = 0.0
        image[300:360, 500:620] = 0.92
        before = image.copy()

        report = pipeline._recover_regional_shadows_inplace(image, "on", 0.75)

        self.assertTrue(report["applied"])
        np.testing.assert_array_equal(image[350:390, 100:180], before[350:390, 100:180])
        np.testing.assert_allclose(image[300:360, 500:620], before[300:360, 500:620], atol=1e-7)

    def test_horizon_transition_has_no_overshoot(self) -> None:
        image = np.empty((512, 768, 3), dtype=np.float32)
        image[:256] = 0.72
        image[256:] = 0.11

        report = pipeline._recover_regional_shadows_inplace(image, "auto", 1.0)
        luma = _luma(image)

        self.assertTrue(report["applied"])
        self.assertLessEqual(float(np.max(luma)), 0.720001)
        self.assertGreaterEqual(float(np.min(luma)), 0.109999)
        np.testing.assert_allclose(luma[:256], 0.72, atol=1e-7)
        ground_rows = np.mean(luma[256:300], axis=1)
        self.assertTrue(np.all(np.diff(ground_rows) >= -1e-6))


if __name__ == "__main__":
    unittest.main()
