"""Checks for the slicer-free analysis helpers (no CadQuery needed)."""
import sys
import unittest
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from rib_width import predict  # noqa: E402
import cup_stability as cs  # noqa: E402


class RibWidth(unittest.TestCase):
    """Calibrated against three Bambu Studio slices (0.12 mm layers, 0.42/0.45 lines)."""

    def test_v4i_centre_line_is_widened(self):
        r = predict(2.2)
        self.assertEqual(r['strands'], 5)
        self.assertAlmostEqual(r['lines_mm'][2], 0.563, delta=0.002)
        self.assertTrue(r['verdict'].startswith('不推荐'))

    def test_v4k_and_v4j_have_no_gap_fill(self):
        k, j = predict(2.58), predict(1.70)
        self.assertEqual(k['lines_mm'], [0.42, 0.45, 0.484, 0.484, 0.45, 0.42])
        self.assertAlmostEqual(j['lines_mm'][1], 0.469, delta=0.002)
        self.assertTrue(k['verdict'].startswith('OK') and j['verdict'].startswith('OK'))


def tray(gap_from=None):
    """100x60 plate, 3 mm floor, 6 mm straight ribs every 5.5 mm, 12 mm rim."""
    parts = [trimesh.creation.box((100, 60, 3), trimesh.transformations.translation_matrix((50, 30, 1.5)))]
    for x0, x1, y0, y1 in ((0, 4, 0, 60), (96, 100, 0, 60), (0, 100, 0, 4), (0, 100, 56, 60)):
        parts.append(trimesh.creation.box((x1 - x0, y1 - y0, 12), trimesh.transformations.translation_matrix(
            ((x0 + x1) / 2, (y0 + y1) / 2, 6))))
    for y in np.arange(9, 52, 5.5):
        x_end = gap_from if gap_from else 92
        parts.append(trimesh.creation.box((x_end - 8, 2.2, 6), trimesh.transformations.translation_matrix(
            ((8 + x_end) / 2, y, 6))))
    return trimesh.util.concatenate(parts)


class CupStability(unittest.TestCase):
    def run_case(self, mesh, centres, foot=30, flat=False):
        crown, _ = cs.detect_crown(mesh)
        tris = mesh.triangles
        on = (mesh.face_normals[:, 2] > 0.999) & (np.abs(tris[:, :, 2].mean(1) - crown) < 0.02)
        rs = cs.Raster(mesh.bounds)
        res, valid = cs.analyse(rs, rs.draw(tris[on]), rs.draw(tris[tris[:, :, 2].max(1) > crown + 0.05]),
                                rs.draw(tris), np.array(centres, float), foot, flat)
        return crown, res, valid

    def test_crown_detected_on_rib_tops(self):
        crown, res, valid = self.run_case(tray(), [[50, 30]])
        self.assertAlmostEqual(crown, 9.0, places=2)
        self.assertTrue(valid[0])
        self.assertLess(res['gap'][0], 90)

    def test_cup_hanging_off_rib_ends_is_one_sided(self):
        # Ribs stop at x=50: a cup centred on the rib ends has support on one side only.
        _, res, valid = self.run_case(tray(gap_from=50), [[50, 30], [30, 30]])
        self.assertTrue(valid.all())
        self.assertGreaterEqual(res['gap'][0], 180)
        self.assertLess(res['gap'][1], 90)

    def test_cup_overlapping_rim_is_rejected(self):
        _, _, valid = self.run_case(tray(), [[10, 30]])
        self.assertFalse(valid[0])


if __name__ == '__main__':
    unittest.main()
