"""Run from the project root: python -m tests.move_axis_and_read."""
from decimal import Decimal

import matplotlib.pyplot as plt

from laser_hardware import DigilentAD3, ThorlabsStage

# Axis
AXIS = "Z_AXIS"

# Input Params
STEP_SIZE_UM = 2
MEASUREMENT_BREADTH_UM = 500
MEASUREMENT_START_UM = 2500


def scan_axis(stage, adc, axis=AXIS, step_size_um=STEP_SIZE_UM,
              breadth_um=MEASUREMENT_BREADTH_UM, start_um=MEASUREMENT_START_UM):
    """Return [(absolute_position_um, voltage_v), ...] after blocking moves.

    Breadth is a positive distance from start. Include the endpoint when it falls
    on a full step; otherwise stop at the last full step within the breadth.
    Other axes remain unchanged. The selected axis stays at the final position.
    """
    axis = axis.lower().removesuffix('_axis')
    if axis not in ('x', 'y', 'z'):
        raise ValueError('AXIS must be X_AXIS, Y_AXIS, or Z_AXIS (or x, y, z)')
    start, step, breadth = map(lambda value: Decimal(str(value)),
                               (start_um, step_size_um, breadth_um))
    if not all(value.is_finite() for value in (start, step, breadth)):
        raise ValueError('Scan parameters must be finite')
    if step <= 0 or breadth < 0:
        raise ValueError('Step size must be positive and breadth must be nonnegative')
    positions = [float(start + index * step)
                 for index in range(int(breadth // step) + 1)]

    # Check the entire scan against axis travel before issuing any motion.
    for position in positions:
        stage.axes[axis].validate_target(position)

    measurements = []
    for position in positions:
        stage.stage_move_absolute(**{axis: position})
        measurement = adc.measure()
        measurements.append((position, measurement))
        print(f'{axis.upper()} = {position:g} um, ADC = {measurement:.6f} V')
    return measurements


def main():
    with ThorlabsStage() as stage, DigilentAD3() as adc:
        measurements = scan_axis(stage, adc)
    print('Measurements (position_um, voltage_v):', measurements)
    positions_um, voltages_v = zip(*measurements)
    fig, ax = plt.subplots()
    ax.plot(positions_um, voltages_v, marker='.', linestyle='-')
    axis_name = AXIS.upper().removesuffix('_AXIS')
    ax.set_xlabel(f'{axis_name} position (µm)')
    ax.set_ylabel('ADC measurement (V)')
    ax.set_title(f'ADC measurement vs. {axis_name} position')
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    plt.show()
    return measurements


if __name__ == '__main__':
    measurements = main()
