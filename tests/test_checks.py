import argparse
import sys
import tempfile
import unittest
from pathlib import Path
import trimesh
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import generate_tray as generator
from check_mesh import check


class Checks(unittest.TestCase):
    def params(self, **changes):
        values = dict(length=240, width=148.3, height=12, floor=3,
                      rib_height=6, rib_width=2.2, pitch=5.5)
        values.update(changes)
        return argparse.Namespace(**values)

    def test_mask_height_tracks_changed_rib_height(self):
        generator.configure(self.params(height=15, floor=4, rib_height=8))
        mask = generator.cylinder((0, 0), 10)
        self.assertAlmostEqual(mask.BoundingBox().zmin, 4)
        self.assertAlmostEqual(mask.BoundingBox().zmax, 12)

    def test_impossible_vertical_stack_rejected(self):
        with self.assertRaises(ValueError):
            generator.configure(self.params(height=8))

    def test_closed_grooves_rejected(self):
        with self.assertRaises(ValueError):
            generator.configure(self.params(pitch=2.2))

    def test_open_mesh_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            mesh = trimesh.creation.box()
            mesh.update_faces(list(range(len(mesh.faces) - 1)))
            path = Path(tmp) / 'open.stl'
            mesh.export(path)
            self.assertFalse(check(path)['geometry_passed'])

    def test_disconnected_solids_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            one = trimesh.creation.box()
            two = one.copy()
            two.apply_translation([5, 0, 0])
            path = Path(tmp) / 'split.stl'
            (one + two).export(path)
            result = check(path)
            self.assertEqual(result['connected_components'], 2)
            self.assertFalse(result['geometry_passed'])


if __name__ == '__main__':
    unittest.main()
