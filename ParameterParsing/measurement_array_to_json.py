"""Write the version-2 point format used by GradientCubeTestData.json."""
import json
from math import isfinite
from pathlib import Path


class measurement_array_to_json:
    """Convert [((x_um, y_um, z_um), measurement), ...] to a JSON file.

    By default measurements must be integer intensity counts in the selected
    bit depth. For ADC voltages, supply measurement_range=(low_v, high_v) to
    linearly map that range to integer counts. Out-of-range readings are rejected.
    Coordinate values remain absolute and input point order is preserved.
    """

    def __init__(self, measurements, sample_name='measurement', *,
                 intensity_bit_depth=8, measurement_range=None, step_um=None):
        if not isinstance(sample_name, str) or not sample_name.strip():
            raise ValueError('sample_name must be a nonempty string')
        if (isinstance(intensity_bit_depth, bool)
                or not isinstance(intensity_bit_depth, int)
                or not 1 <= intensity_bit_depth <= 32):
            raise ValueError('intensity_bit_depth must be an integer from 1 to 32')
        maximum = (1 << intensity_bit_depth) - 1
        bounds = None
        if measurement_range is not None:
            bounds = self._numbers(measurement_range, 2, 'measurement_range')
            if bounds[0] >= bounds[1]:
                raise ValueError('measurement_range must have low < high')

        points = []
        for index, item in enumerate(measurements):
            try:
                coordinate, measurement = item
            except (ValueError, TypeError) as exc:
                raise ValueError(f'Item {index} must be ((x, y, z), measurement)') from exc
            coordinate = self._numbers(coordinate, 3, f'Coordinate at item {index}')
            value = self._numbers([measurement], 1, f'Measurement at item {index}')[0]
            if bounds is not None:
                low, high = bounds
                if not low <= value <= high:
                    raise ValueError(f'Measurement at item {index} is outside measurement_range')
                intensity = int((value - low) / (high - low) * maximum + 0.5)
            else:
                if not value.is_integer() or not 0 <= value <= maximum:
                    raise ValueError(f'Measurement at item {index} must be integer counts '
                                     f'in [0, {maximum}]; supply measurement_range for voltages')
                intensity = int(value)
            points.append([*coordinate, intensity])
        if not points:
            raise ValueError('measurements must contain at least one point')

        axes = [sorted({point[i] for point in points}) for i in range(3)]
        origin = [values[0] for values in axes]
        size = [values[-1] - values[0] for values in axes]
        if step_um is None:
            # Minimum observed spacing per axis; a fixed axis uses 0.
            step = [min((b - a for a, b in zip(values, values[1:])), default=0.0)
                    for values in axes]
        else:
            step = self._numbers(step_um, 3, 'step_um')
            if any(value < 0 for value in step):
                raise ValueError('step_um values must be nonnegative')
        self._document = dict(version=2, sample_name=sample_name, units='um',
                              origin_um=origin, size_um=size, step_um=step,
                              intensity_bit_depth=intensity_bit_depth,
                              point_format=['x', 'y', 'z', 'intensity'], points=points)

    @staticmethod
    def _numbers(values, length, name):
        try:
            values = list(values)
            if len(values) != length or any(isinstance(v, (str, bytes, bool)) for v in values):
                raise ValueError()
            result = [float(value) for value in values]
            if not all(isfinite(value) for value in result):
                raise ValueError()
            return result
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f'{name} must contain {length} finite numbers') from exc

    def write(self, output_path):
        """Write UTF-8 JSON, replacing an existing file; return its Path.

        step_um is minimum observed spacing, not a claim that the scan is a
        complete grid. Pass explicit spacing when samples are missing. A fixed
        axis defaults to zero spacing; override if your consumer requires it.
        """
        path = Path(output_path)
        path.write_text(json.dumps(self._document, indent=2, allow_nan=False) + '\n',
                        encoding='utf-8')
        return path
