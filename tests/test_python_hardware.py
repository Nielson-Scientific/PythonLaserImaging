import ctypes as C
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from laser_hardware import Stage, SimulatedAxis, SimulatedADC, DigilentAD3
from laser_hardware.thorlabs import _XAAxis, _describe_devices, _matches_device


class HardwareTests(unittest.TestCase):
    def test_discovery_matches_padded_fields_without_accepting_wrong_devices(self):
        controller = NS(device='70876912', part_number='BSC203 ', parent_device='')
        self.assertTrue(_matches_device(controller, '70876912', 'BSC203'))
        self.assertFalse(_matches_device(controller, 'different', 'BSC203'))
        channel = NS(device='90876913 ', part_number='SCC201 ', parent_device='70876912 ')
        self.assertTrue(_matches_device(channel, '90876913', 'SCC201', '70876912'))
        self.assertFalse(_matches_device(channel, '90876913', 'SCC201', 'other'))

    def test_discovery_diagnostics_show_identifiers(self):
        self.assertEqual(_describe_devices([]), 'XA returned no devices.')
        message = _describe_devices([NS(part_number='BSC203', device='controller-id',
                                       parent_device='', transport='USB')])
        self.assertIn("device='controller-id'", message)
        self.assertIn("part='BSC203'", message)
        self.assertIn("transport='USB'", message)

    def test_relative_and_partial_absolute(self):
        with Stage(*(SimulatedAxis() for _ in range(3))) as stage:
            stage.stage_move_relative(10, 20, 30)
            stage.stage_move_absolute(y=50)
            self.assertEqual(stage.position(), dict(x=10, y=50, z=30))
            stage.stage_move_absolute()
        with self.assertRaises(RuntimeError):
            stage.position()

    def test_validate_all_axes_before_any_motion(self):
        with Stage(*(SimulatedAxis() for _ in range(3))) as stage:
            with self.assertRaises(ValueError):
                stage.stage_move_absolute(x=50, z=5000)
            self.assertEqual(stage.position()['x'], 0)
            with self.assertRaises(ValueError):
                stage.stage_move_relative(float('nan'))

    def test_failure_stops_every_axis(self):
        axes = [SimulatedAxis() for _ in range(3)]
        stopped = []
        for i, axis in enumerate(axes):
            axis.stop = lambda i=i: stopped.append(i)
        def fail(target):
            raise TimeoutError()
        axes[1].move_absolute = fail
        with Stage(*axes) as stage:
            with self.assertRaises(TimeoutError):
                stage.stage_move_absolute(10, 20, 30)
        self.assertEqual(stopped, [0, 1, 2])

    def test_cleanup_attempts_every_axis(self):
        axes = [SimulatedAxis() for _ in range(3)]
        def fail():
            raise RuntimeError('close failure')
        axes[0].close = fail
        with self.assertRaises(RuntimeError):
            Stage(*axes).close()
        self.assertTrue(axes[1].closed and axes[2].closed)

    def test_xa_units_counts_and_blocking_timeout(self):
        enums = NS(TLMC_Unit=NS(TLMC_Unit_Millimetres=1, TLMC_Unit_Micrometres=5),
                   TLMC_ScaleType=NS(TLMC_ScaleType_Distance=1),
                   TLMC_MoveMode=NS(TLMC_MoveMode_Absolute=0))
        calls = []
        device = NS(
            get_supported_connected_products=lambda: ['profile'],
            set_connected_product=lambda p: None,
            get_connected_product_info=lambda: NS(product_name='profile', unit_type=1,
                                                   min_position=0, max_position=4),
            get_position_counter=lambda timeout: 100,
            convert_from_device_units_to_physical=lambda scale, counts: (0.1, 1),
            convert_from_physical_to_device=lambda scale, unit, v: round(v * 1000),
            move=lambda *args: calls.append(args))
        axis = _XAAxis(device, enums, 'profile', 60000)
        self.assertEqual(axis.position(), 100)
        axis.move_absolute(250)
        self.assertEqual(calls, [(0, 250, 60000)])
        with self.assertRaises(ValueError):
            axis.validate_target(4001)

    def test_adc_fresh_capture_mean_and_clipping(self):
        adc = object.__new__(DigilentAD3)
        from laser_hardware import AD3Config
        adc.config = AD3Config(samples=2)
        adc.handle = C.c_int(1)
        adc.actual_range_v = 10
        calls = []
        samples = [1.0, 3.0]
        def call(name, *args):
            calls.append(name)
            if name == 'FDwfAnalogInStatus':
                args[-1]._obj.value = 2
            if name == 'FDwfAnalogInStatusData':
                args[2][:] = samples
        adc._call = call
        self.assertEqual(adc.measure(), 2)
        self.assertEqual(adc.measure(), 2)
        self.assertEqual(calls.count('FDwfAnalogInConfigure'), 2)
        samples[0] = 5
        with self.assertRaises(OverflowError):
            adc.measure()

    def test_adc_timeout_aborts(self):
        adc = object.__new__(DigilentAD3)
        from laser_hardware import AD3Config
        adc.config = AD3Config()
        adc.handle = C.c_int(1)
        calls = []
        adc._call = lambda name, *args: calls.append((name, args))
        with patch('laser_hardware.digilent.time.monotonic', side_effect=[0, 10]):
            with self.assertRaises(TimeoutError):
                adc.measure_samples()
        self.assertEqual(calls[-1][0], 'FDwfAnalogInConfigure')
        self.assertEqual(calls[-1][1][-1].value, 0)


if __name__ == '__main__':
    unittest.main()
