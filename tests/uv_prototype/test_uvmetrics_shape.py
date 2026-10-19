"""Package 1 synthetic checks; no Blender or production data required.

Copy this file and uvmetrics.py to tests/_work/uv_shape/, create a venv there,
install numpy into it, then run: venv/Scripts/python.exe -I test_uvmetrics_shape.py
The explicit import path supports isolated Python without importing other work dirs.
"""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uvmetrics as um


class ShapeMetricsTests(unittest.TestCase):
    def setUp(self):
        self.p = np.array([[0., 0., 0.], [1., 0., 0.], [2., 0., 0.],
                           [0., 1., 0.], [1., 1., 0.], [2., 1., 0.]])
        self.t = np.array([[0, 1, 4], [0, 4, 3], [1, 2, 5], [1, 5, 4]])
        self.u = self.p[self.t, :2].copy()

    def test_isometric_unwrap(self):
        result = um.shape_metrics(self.p, self.t, self.u)
        for key in ('conformal', 'area_distortion', 'singular_values'):
            np.testing.assert_allclose(result['faces'][key], 1., atol=1e-14)
        self.assertEqual(result['object']['island_count'], 1)
        for scope in (result['object'], result['islands'][0]):
            for key in ('conformal', 'area_distortion'):
                for statistic in ('mean', 'p95', 'max'):
                    self.assertAlmostEqual(scope[key][statistic], 1.)
            self.assertEqual(scope['conformal_area_share_above_threshold'], 0.)
            self.assertAlmostEqual(scope['planar']['conformal']['mean'], 1.)
            self.assertAlmostEqual(scope['planar']['area_distortion']['mean'], 1.)

    def test_known_unit_shear(self):
        shear = np.array([[1., 1.], [0., 1.]])
        result = um.shape_metrics(self.p, self.t, self.u @ shear.T)
        # J=[[1,1],[0,1]] has singular-value ratio (3 + sqrt(5))/2.
        expected = (3 + np.sqrt(5)) / 2
        np.testing.assert_allclose(result['faces']['conformal'], expected)
        np.testing.assert_allclose(result['faces']['area_distortion'], 1.)
        self.assertAlmostEqual(result['object']['conformal']['p95'], expected)
        self.assertEqual(result['object']['conformal_area_share_above_threshold'], 1.)

    def test_uniform_scale_rotation_reflection_and_translation(self):
        angle = .71
        rotation = np.array([[np.cos(angle), -np.sin(angle)],
                             [np.sin(angle), np.cos(angle)]])
        for scale in (1e-6, .25, 7., 1e6):
            with self.subTest(scale=scale):
                uv = self.u @ rotation * scale
                uv[:, :, 0] *= -1
                uv += scale * np.array([5., -3.])
                p = self.p[:, [2, 0, 1]] * .13 + [2., 4., -7.]
                result = um.shape_metrics(p, self.t, uv)
                np.testing.assert_allclose(result['faces']['conformal'], 1., atol=1e-12)
                np.testing.assert_allclose(result['faces']['area_distortion'], 1., atol=1e-12)
                self.assertAlmostEqual(result['object']['straight_edges']['preserved_fraction'], 1.)

    def test_each_island_normalizes_its_own_scale(self):
        uv = self.u.copy()
        uv[2:] = uv[2:] * 8 + 10
        result = um.shape_metrics(self.p, self.t, uv)
        self.assertEqual(result['object']['island_count'], 2)
        np.testing.assert_allclose(result['faces']['area_distortion'], 1.)
        np.testing.assert_allclose(sorted(r['uv_scale'] for r in result['islands']), [1., 8.])

    def test_area_normalization_and_reciprocal(self):
        p = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.],
                      [2., 0., 0.], [3., 0., 0.], [2., 1., 0.]])
        t = np.array([[0, 1, 2], [3, 4, 5]])
        uv = p[t, :2].copy()
        uv[1] *= 2
        # Explicit labels exercise two differently scaled faces in one island.
        result = um.shape_metrics(p, t, uv, np.array([7, 7]))
        np.testing.assert_allclose(result['faces']['conformal'], 1.)
        np.testing.assert_allclose(result['faces']['area_distortion'], [2.5, 1.6])
        self.assertAlmostEqual(result['object']['area_distortion']['mean'], 2.05)
        self.assertAlmostEqual(result['object']['area_distortion']['p95'], 2.5)

    def test_area_weighted_percentile_not_face_count(self):
        p = np.array([[0., 0., 0.], [99., 0., 0.], [0., 1., 0.],
                      [0., 2., 0.], [1., 2., 0.], [0., 3., 0.]])
        t = np.array([[0, 1, 2], [3, 4, 5]])
        uv = p[t, :2].copy()
        uv[1, :, 0] *= 10
        result = um.shape_metrics(p, t, uv)
        self.assertAlmostEqual(result['object']['conformal']['mean'], 1.09)
        self.assertAlmostEqual(result['object']['conformal']['p95'], 1.)
        self.assertAlmostEqual(result['object']['conformal']['max'], 10.)
        self.assertAlmostEqual(result['object']['conformal_area_share_above_threshold'], .01)

    def test_straight_boundary_chains(self):
        straight = um.shape_metrics(self.p, self.t, self.u)['object']['straight_edges']
        self.assertEqual(straight['chain_count'], 2)
        self.assertAlmostEqual(straight['eligible_length'], 4.)
        self.assertAlmostEqual(straight['preserved_fraction'], 1.)
        vertices = self.p[:, :2].copy()
        vertices[[1, 4], 1] += .3
        bent = um.shape_metrics(self.p, self.t, vertices[self.t])['object']['straight_edges']
        self.assertAlmostEqual(bent['preserved_fraction'], 0.)
        vertices = self.p[:, :2].copy()
        vertices[4, 1] += .3
        half = um.shape_metrics(self.p, self.t, vertices[self.t])['object']['straight_edges']
        self.assertAlmostEqual(half['preserved_fraction'], .5)

    def test_straightness_angle_tolerance(self):
        for degrees, expected in ((1., 1.), (3., 0.)):
            with self.subTest(degrees=degrees):
                vertices = self.p[:, :2].copy()
                vertices[[1, 4], 1] += np.tan(np.radians(degrees / 2))
                result = um.shape_metrics(self.p, self.t, vertices[self.t])
                self.assertEqual(result['object']['straight_edges']['preserved_fraction'], expected)

    def test_no_eligible_chain_is_not_a_perfect_score(self):
        result = um.shape_metrics(self.p, self.t[:1], self.u[:1])
        self.assertIsNone(result['object']['straight_edges']['preserved_fraction'])
        self.assertEqual(result['object']['straight_edges']['eligible_length'], 0.)

    def test_dominant_plane_excludes_perpendicular_wall(self):
        p = np.array([[0., 0., 0.], [4., 0., 0.], [0., 3., 0.],
                      [0., 0., 0.], [0., 1., 0.], [0., 0., 2.]])
        t = np.array([[0, 1, 2], [3, 4, 5]])
        uv = np.array([[[0., 0.], [4., 0.], [0., 3.]],
                       [[5., 0.], [6., 0.], [5., 2.]]])
        result = um.shape_metrics(p, t, uv, np.array([0, 0]))
        np.testing.assert_array_equal(result['faces']['planar'], [True, False])
        self.assertEqual(result['object']['planar']['face_count'], 1)
        self.assertAlmostEqual(result['object']['planar']['area_3d'], 6.)
        self.assertAlmostEqual(result['object']['planar']['conformal']['mean'], 1.)

    def test_reversed_winding_does_not_cancel_dominant_plane(self):
        t, uv = self.t.copy(), self.u.copy()
        t[1] = t[1, ::-1]
        uv[1] = uv[1, ::-1]
        result = um.shape_metrics(self.p, t, uv)
        self.assertTrue(result['faces']['planar'].all())
        np.testing.assert_allclose(result['faces']['conformal'], 1.)

    def test_collapsed_uvs_are_infinite_not_omitted(self):
        for uv in (np.zeros_like(self.u), self.u * [1, 0]):
            result = um.shape_metrics(self.p, self.t, uv)
            self.assertTrue(np.isinf(result['faces']['conformal']).all())
            self.assertTrue(np.isinf(result['faces']['area_distortion']).all())
            self.assertTrue(np.isinf(result['object']['conformal']['mean']))
            self.assertEqual(result['object']['collapsed_uv_faces'], 4)
            self.assertEqual(result['object']['conformal_area_share_above_threshold'], 1.)

    def test_degenerate_3d_faces_are_explicitly_excluded(self):
        p = np.array([[0., 0., 0.], [1., 0., 0.], [2., 0., 0.]])
        result = um.shape_metrics(p, np.array([[0, 1, 2]]), np.zeros((1, 3, 2)))
        self.assertEqual(result['object']['degenerate_3d_faces'], 1)
        self.assertTrue(np.isnan(result['faces']['conformal'][0]))
        self.assertIsNone(result['object']['conformal']['mean'])

    def test_tiny_isometric_triangle_is_not_lost_to_absolute_epsilon(self):
        result = um.shape_metrics(self.p * 1e-9, self.t, self.u * 1e-9)
        self.assertEqual(result['object']['valid_face_count'], 4)
        np.testing.assert_allclose(result['faces']['conformal'], 1., atol=1e-14)

    def test_empty_mesh(self):
        result = um.shape_metrics(np.empty((0, 3)), np.empty((0, 3), dtype=int), np.empty((0, 3, 2)))
        self.assertEqual(result['object']['island_count'], 0)
        self.assertIsNone(result['object']['conformal']['p95'])
        self.assertIsNone(result['object']['straight_edges']['preserved_fraction'])

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            um.shape_metrics(self.p, self.t.astype(float), self.u)
        with self.assertRaises(ValueError):
            um.shape_metrics(self.p, self.t + 100, self.u)
        with self.assertRaises(ValueError):
            um.shape_metrics(self.p, self.t, self.u * np.nan)
        with self.assertRaises(ValueError):
            um.shape_metrics(self.p, self.t, self.u, np.array([0]))
        with self.assertRaises(ValueError):
            um.shape_metrics(self.p, self.t, self.u, straight_degrees=180)

    def test_existing_round3_area_metric_is_unchanged(self):
        mean, maximum, faces = um.area_distortion(self.p[self.t], self.u)
        self.assertAlmostEqual(mean, 1.)
        self.assertAlmostEqual(maximum, 1.)
        np.testing.assert_allclose(faces, 1.)


if __name__ == '__main__':
    unittest.main(verbosity=2)
