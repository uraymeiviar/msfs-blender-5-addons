"""Pure decision tests; Blender/export integration is tested separately."""

import importlib.util
from pathlib import Path
import sys
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'fss_blender_tools' / 'lod_rules.py'
SPEC = importlib.util.spec_from_file_location('lod_rules', SOURCE)
lod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lod
SPEC.loader.exec_module(lod)


class LodRulesTest(unittest.TestCase):
    def decide(self, parts, level=3, **kwargs):
        return lod.decide(parts, level, 3.0, lod.DEFAULT_MIN_SIZES, **kwargs)

    def test_marks_and_parent_intervals(self):
        parts = [lod.Part('hide', None, 1, hide_from=3),
                 lod.Part('show', None, .0001, show_from=3),
                 lod.Part('child', 'hide', 1, keep=True)]
        for level in range(7):
            result = self.decide(parts, level)
            self.assertEqual('hide' in result.present, level < 3)
            self.assertEqual('child' in result.present, level < 3)
            self.assertEqual('show' in result.present, level >= 3)
            self.assertIn('Keep under hidden ancestor', result.warnings[0])

    def test_keep_protects_only_ancestor_chain(self):
        parts = [lod.Part('root', None, .0001),
                 lod.Part('middle', 'root', .0001),
                 lod.Part('keep', 'middle', .0001, keep=True),
                 lod.Part('sibling', 'root', .0001)]
        for level in range(1, 7):
            result = self.decide(parts, level)
            self.assertEqual(result.present, {'root', 'middle', 'keep'})
            self.assertEqual(result.by_size, {'sibling'})

    def test_size_boundary_and_large_child(self):
        cutoff = 3 * 2 / (.55 * 1440)
        parts = [lod.Part('below', None, cutoff * .999),
                 lod.Part('at', None, cutoff),
                 lod.Part('above', None, cutoff * 1.001),
                 lod.Part('small_parent_large_subtree', None, 1),
                 lod.Part('large_child', 'small_parent_large_subtree', 1)]
        result = self.decide(parts)
        self.assertEqual(result.by_size, {'below'})
        self.assertEqual(len(result.present), 4)

    def test_hidden_keep_does_not_protect_auto_ancestors(self):
        parts = [lod.Part('auto', None, .0001),
                 lod.Part('hidden', 'auto', .0001, hide_from=3),
                 lod.Part('keep', 'hidden', .0001, keep=True)]
        self.assertEqual(self.decide(parts, 2).present, {'auto', 'hidden', 'keep'})
        self.assertEqual(self.decide(parts, 3).present, set())

    def test_ancestor_outside_export_set_still_constrains_marks(self):
        parts = [lod.Part('child', None, .0001, keep=True, outside_ancestors=(('hidden_empty', 2, 0),))]
        self.assertEqual(self.decide(parts, 1).present, {'child'})
        result = self.decide(parts, 2)
        self.assertEqual(result.by_mark, {'child'})
        self.assertIn('Keep under hidden ancestor', result.warnings[0])

    def test_counts_are_not_culling_inputs(self):
        part = lod.Part('part', None, .004)
        self.assertNotIn('part', self.decide([part]).present)
        with self.assertRaises(TypeError):
            self.decide([part], previous_vertices=1000000)

    def test_explicit_marks_override_size_but_not_parent(self):
        parts = [lod.Part('explicit', None, .00001, hide_from=6),
                 lod.Part('auto_parent', None, .00001),
                 lod.Part('explicit_child', 'auto_parent', .00001, hide_from=6)]
        result = self.decide(parts)
        self.assertEqual(result.present, {'explicit'})
        self.assertEqual(result.by_size, {'auto_parent', 'explicit_child'})

    def test_interior_settings(self):
        with self.assertRaisesRegex(ValueError, 'exterior diameter missing'):
            lod.min_sizes('INTERIOR', False, lod.DEFAULT_MIN_SIZES, 3.5, 0, 'fs24')
        table = lod.min_sizes('INTERIOR', False, lod.DEFAULT_MIN_SIZES, 3.5, 40, 'fs24')
        self.assertAlmostEqual(table[1], .065625)
        explicit = lod.min_sizes('INTERIOR', True, table, 3.5, 0, 'fs24')
        self.assertEqual(explicit, table)
        result = self.decide([lod.Part('keep', None, 1, keep=True)], 6, model_type='INTERIOR')
        self.assertFalse(result.present)

    def test_fs20_penultimate_floor(self):
        table = lod.min_sizes('INTERIOR', False, lod.DEFAULT_MIN_SIZES, 3.5, 40, 'fs20')
        self.assertEqual(table[5], .01)

    def test_stored_vertices_shared_accessors(self):
        document = {'accessors': [{'count': 24}, {'count': 12}], 'meshes': [
            {'primitives': [{'attributes': {'POSITION': 0}}, {'attributes': {'POSITION': 0}}]},
            {'primitives': [{'attributes': {'POSITION': 1}}]}]}
        self.assertEqual(lod.gltf_vertex_count(document), 36)

    def test_curve_matches_high_reference_points(self):
        for count in (1000, 2500, 30000, 150000, 250000, 500000, 1000000):
            ratio = lod.lowest_screen_size_from_vcount(count)
            self.assertEqual(lod.max_vertex_count(ratio), count)

    def test_first_empty_ends_export_list(self):
        parts = [lod.Part('early', None, 1, hide_from=2),
                 lod.Part('late', None, 1, show_from=4)]
        decisions = [self.decide(parts, level) for level in range(7)]
        self.assertEqual(lod.written_lod_count(decisions), 2)
        self.assertTrue(decisions[4].present)

    def test_screen_ratio_and_lod_selection(self):
        import math
        fov_90 = math.radians(90.0)
        # At 90 deg vertical FOV, tan(fov/2) = 1.0, so ratio = radius / distance = (0.5 * diameter) / distance
        self.assertAlmostEqual(lod.screen_ratio(4.0, 2.0, fov_90), 1.0)
        self.assertAlmostEqual(lod.screen_ratio(4.0, 4.0, fov_90), 0.5)
        self.assertEqual(lod.screen_ratio(4.0, 0.0, fov_90), 10.0)
        self.assertEqual(lod.screen_ratio(0.0, 2.0, fov_90), 0.0)

        table = lod.DEFAULT_MIN_SIZES
        self.assertEqual(lod.lod_from_screen_ratio(1.2, table, 7), 0)
        self.assertEqual(lod.lod_from_screen_ratio(1.0, table, 7), 0)
        self.assertEqual(lod.lod_from_screen_ratio(0.8, table, 7), 1)
        self.assertEqual(lod.lod_from_screen_ratio(0.6, table, 7), 2)
        self.assertEqual(lod.lod_from_screen_ratio(0.4, table, 7), 3)
        self.assertEqual(lod.lod_from_screen_ratio(0.1, table, 7), 4)
        self.assertEqual(lod.lod_from_screen_ratio(0.06, table, 7), 5)
        self.assertEqual(lod.lod_from_screen_ratio(0.02, table, 7), 6)
        self.assertEqual(lod.lod_from_screen_ratio(0.002, table, 7), 6)
        # Interior with write_count=6 clamps to LOD05
        self.assertEqual(lod.lod_from_screen_ratio(0.0001, table, 6), 5)


if __name__ == '__main__':
    unittest.main()

