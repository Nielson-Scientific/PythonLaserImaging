import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ParameterParsing import measurement_array_to_json


class MeasurementExportTests(unittest.TestCase):
    def test_version_two_shape_and_coordinate_bounds(self):
        exporter = measurement_array_to_json([
            ((5, 2, 500), 0), ((5, 2, 600), 128), ((5, 2, 700), 255)],
            sample_name='z_scan')
        with TemporaryDirectory() as directory:
            path = exporter.write(Path(directory) / 'scan.json')
            data = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(data['version'], 2)
        self.assertEqual(data['origin_um'], [5, 2, 500])
        self.assertEqual(data['size_um'], [0, 0, 200])
        self.assertEqual(data['step_um'], [0, 0, 100])
        self.assertEqual(data['points'][-1], [5, 2, 700, 255])
        self.assertEqual(data['point_format'], ['x', 'y', 'z', 'intensity'])

    def test_explicit_voltage_conversion(self):
        exporter = measurement_array_to_json([
            ((0, 0, 0), -1), ((0, 0, 1), 0), ((0, 0, 2), 1)],
            measurement_range=(-1, 1), step_um=(1, 1, 1))
        self.assertEqual([p[3] for p in exporter._document['points']], [0, 128, 255])
        self.assertEqual(exporter._document['step_um'], [1, 1, 1])

    def test_invalid_data_rejected(self):
        for points in ([], [((1, 2), 0)], [((0, 0, float('nan')), 0)],
                       [((0, 0, 0), 0.01)], [((0, 0, 0), 256)]):
            with self.subTest(points=points), self.assertRaises(ValueError):
                measurement_array_to_json(points)
        with self.assertRaises(ValueError):
            measurement_array_to_json([((0, 0, 0), 6)], measurement_range=(0, 5))


if __name__ == '__main__':
    unittest.main()
