"""Run from the project root: python -m examples.simple_control [--hardware]."""
import argparse
from laser_hardware import ThorlabsStage, DigilentAD3, Stage, SimulatedAxis, SimulatedADC


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hardware', action='store_true', help='Connect real devices; reads only')
    args = parser.parse_args()
    stage_factory = ThorlabsStage if args.hardware else lambda: Stage(
        SimulatedAxis(), SimulatedAxis(), SimulatedAxis())
    adc_factory = DigilentAD3 if args.hardware else SimulatedADC
    with stage_factory() as stage, adc_factory() as ADC:
        stage_move_relative = stage.stage_move_relative
        stage_move_absolute = stage.stage_move_absolute
        print('Position (um):', stage.position())
        print('Detector voltage:', ADC.measure(), 'V')
        if not args.hardware:
            stage_move_relative(10, 20, 5)
            stage_move_absolute(x=50, y=50)  # Retains current Z.
            print('New position (um):', stage.position())
        # Real motion: verify clearances and home explicitly as needed, then use
        # the same commands above. Connection never homes automatically.


if __name__ == '__main__':
    main()
