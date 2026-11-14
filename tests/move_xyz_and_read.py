"""Run from the project root: python -m tests.move_xyz_and_read.

Uses the current stage origin without homing. All distances are micrometres.
"""
from decimal import Decimal
from datetime import datetime
from pathlib import Path

from laser_hardware import AD3Config, DigilentAD3, ThorlabsStage
from ParameterParsing import measurement_array_to_json


# Input parameters: breadth is the distance from start, not the endpoint.
X_STEP_SIZE_UM = 100
X_MEASUREMENT_BREADTH_UM = 100
X_MEASUREMENT_START_UM = 500

Y_STEP_SIZE_UM = 100
Y_MEASUREMENT_BREADTH_UM = 100
Y_MEASUREMENT_START_UM = 500

Z_STEP_SIZE_UM = 2
Z_MEASUREMENT_BREADTH_UM = 500
Z_MEASUREMENT_START_UM = 2500

ADC_CHANNEL = 1  # Zero-based: physical Scope 2, matching move_axis_and_read.py.

OUTPUT_DIRECTORY = Path(__file__).resolve().parents[1] / 'scan_results'
SAMPLE_NAME = 'xyz_scan'
INTENSITY_BIT_DEPTH = 8
# Map the detector signal (0 to 1 V) to JSON intensity counts (0 to 255).
# Adjust this range to your signal when a different intensity scale is desired.
JSON_MEASUREMENT_RANGE_V = (0.0, 1.0)


def axis_positions(start_um, breadth_um, step_size_um):
    """Include the endpoint only when it lies on a full step."""
    start, breadth, step = (Decimal(str(value))
                            for value in (start_um, breadth_um, step_size_um))
    if not all(value.is_finite() for value in (start, breadth, step)):
        raise ValueError('Scan parameters must be finite')
    if step <= 0 or breadth < 0:
        raise ValueError('Step size must be positive and breadth must be nonnegative')
    return [float(start + index * step) for index in range(int(breadth // step) + 1)]


def scan_xyz(stage, adc, *,
             x_start_um=X_MEASUREMENT_START_UM, x_breadth_um=X_MEASUREMENT_BREADTH_UM,
             x_step_um=X_STEP_SIZE_UM,
             y_start_um=Y_MEASUREMENT_START_UM, y_breadth_um=Y_MEASUREMENT_BREADTH_UM,
             y_step_um=Y_STEP_SIZE_UM,
             z_start_um=Z_MEASUREMENT_START_UM, z_breadth_um=Z_MEASUREMENT_BREADTH_UM,
             z_step_um=Z_STEP_SIZE_UM):
    """Return [((x_um, y_um, z_um), voltage_v), ...], with Z varying fastest.

    Each measurement follows a completed blocking move. Z returns to its start
    for each new X/Y pair. The stage remains at the final coordinate afterward.
    """
    xs = axis_positions(x_start_um, x_breadth_um, x_step_um)
    ys = axis_positions(y_start_um, y_breadth_um, y_step_um)
    zs = axis_positions(z_start_um, z_breadth_um, z_step_um)
    # Validate the full scan before moving any axis.
    for name, positions in (('x', xs), ('y', ys), ('z', zs)):
        for position in positions:
            stage.axes[name].validate_target(position)

    measurements = []
    for x in xs:
        stage.stage_move_absolute(x=x)
        for y in ys:
            stage.stage_move_absolute(y=y)
            for z in zs:
                stage.stage_move_absolute(z=z)
                measurement = adc.measure()
                measurements.append(((x, y, z), measurement))
                print(f'X={x:g}, Y={y:g}, Z={z:g} um, ADC={measurement:.6f} V')
    return measurements


def save_measurements(measurements, output_directory=OUTPUT_DIRECTORY):
    """Save a timestamped version-2 JSON file and return its absolute path."""
    exporter = measurement_array_to_json(
        measurements, sample_name=SAMPLE_NAME,
        intensity_bit_depth=INTENSITY_BIT_DEPTH,
        measurement_range=JSON_MEASUREMENT_RANGE_V,
        step_um=(X_STEP_SIZE_UM, Y_STEP_SIZE_UM, Z_STEP_SIZE_UM))
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    filename = f'xyz_scan_{datetime.now():%Y%m%d_%H%M%S_%f}.json'
    path = exporter.write(directory / filename)
    print(f'Saved measurements to: {path}')
    return path


def plot_measurements(measurements):
    """Display all points initially; slider hides ADC values below its threshold.

    Filtering changes only the display, never the recorded or exported data.
    Return the figure and slider so callers can retain the interactive widget.
    """
    import matplotlib.pyplot as plt
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import Normalize
    from matplotlib.widgets import Slider
    import numpy as np

    if not measurements:
        raise ValueError('No measurements to plot')
    coordinates, voltages = zip(*measurements)
    coordinates = np.asarray(coordinates, dtype=float)
    voltages = np.asarray(voltages, dtype=float)
    if coordinates.shape != (len(voltages), 3) or not (
            np.isfinite(coordinates).all() and np.isfinite(voltages).all()):
        raise ValueError('Expected finite coordinate triplets and voltages')
    low, high = float(voltages.min()), float(voltages.max())
    # Give constant-valued scans a usable slider and nonzero color range.
    span = max(high - low, 0.001)
    slider_high = high + span * 0.01
    norm = Normalize(vmin=low, vmax=high if high > low else low + span)
    fig = plt.figure()
    fig.subplots_adjust(bottom=0.22, right=0.85)
    ax = fig.add_subplot(111, projection='3d')
    points = ax.scatter(*coordinates.T, c=voltages, cmap='viridis', norm=norm)
    ax.set_xlabel('X position (um)')
    ax.set_ylabel('Y position (um)')
    ax.set_zlabel('Z position (um)')
    # Hold the full scan bounds even when every point is filtered out.
    ax.set_xlim(ax.get_xlim())
    ax.set_ylim(ax.get_ylim())
    ax.set_zlim(ax.get_zlim())
    ax.set_title(f'XYZ scan: {len(voltages)}/{len(voltages)} points visible')
    fig.colorbar(ScalarMappable(norm=norm, cmap='viridis'), ax=ax,
                 label='ADC measurement (V)', pad=0.15)
    slider_ax = fig.add_axes([0.24, 0.08, 0.60, 0.03])
    slider = Slider(slider_ax, 'Minimum ADC (V)', low, slider_high,
                    valinit=low, valfmt='%.6f')

    def update(threshold):
        nonlocal points
        visible = voltages >= threshold
        points.remove()
        points = ax.scatter(*coordinates[visible].T, c=voltages[visible],
                            cmap='viridis', norm=norm)
        ax.set_title(f'XYZ scan: {int(visible.sum())}/{len(voltages)} points visible')
        fig.canvas.draw_idle()

    slider.on_changed(update)
    # Matplotlib widgets require a strong reference while their window is open.
    fig.threshold_slider = slider
    return fig, slider


def main():
    import matplotlib.pyplot as plt

    with ThorlabsStage() as stage, DigilentAD3(AD3Config(channel=ADC_CHANNEL)) as adc:
        measurements = scan_xyz(stage, adc)
    print(f'Collected {len(measurements)} measurements (coordinates_um, voltage_v).')
    save_measurements(measurements)
    fig, slider = plot_measurements(measurements)
    plt.show()
    return measurements


if __name__ == '__main__':
    measurements = main()
