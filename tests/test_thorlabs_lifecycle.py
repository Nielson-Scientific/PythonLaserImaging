"""XA ownership and failure rollback, without USB access."""
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from laser_hardware.thorlabs import ThorlabsStage


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.devices = [NS(device='70876912', part_number='BSC203 ', parent_device='', transport='')]
        for serial in ('90876913', '90876914', '90876915'):
            self.devices.append(NS(device=serial, part_number='SCC201',
                                   parent_device='70876912', transport='70876912'))
        self.native = Mock()
        self.native.open.side_effect = lambda serial, transport, mode: serial
        self.native.get_device_info.side_effect = lambda handle: handle
        self.native.close.side_effect = lambda handle: self.events.append(('close', handle))
        self.manager = Mock(native_functions=self.native)
        self.manager.get_device_list.return_value = self.devices
        self.manager.device_factory.create.side_effect = lambda handle, info: NS(
            close=lambda: self.native.close(handle))
        self.manager.shutdown.side_effect = lambda: self.events.append(('shutdown',))
        enums = NS(TLMC_OperatingMode=NS(TLMC_OperatingMode_Default=0))
        self.modules = patch.dict(sys.modules, {
            'thorlabs_xa': NS(),
            'thorlabs_xa.shared': NS(enums=enums),
            'thorlabs_xa.shared.system_manager': NS(SystemManager=NS(instance=lambda: self.manager)),
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.axis_patch = patch('laser_hardware.thorlabs._XAAxis', side_effect=lambda device, *args: device)
        self.axis_patch.start()
        self.addCleanup(self.axis_patch.stop)

    def test_overlapping_session_rejected_and_close_is_idempotent(self):
        with ThorlabsStage() as stage:
            with self.assertRaisesRegex(RuntimeError, 'already open'):
                ThorlabsStage()
            self.assertEqual(self.manager.startup.call_count, 1)
        stage.close()
        self.assertEqual(self.events, [('close', '90876913'), ('close', '90876915'),
                                      ('close', '90876914'), ('shutdown',)])
        with ThorlabsStage():
            pass

    def test_second_channel_open_failure_closes_first_and_shuts_down(self):
        self.native.open.side_effect = ['90876914', RuntimeError('operating modes')]
        with self.assertLogs('laser_hardware.thorlabs', level='ERROR'):
            with self.assertRaisesRegex(RuntimeError, 'operating modes'):
                ThorlabsStage()
        self.assertEqual(self.events, [('close', '90876914'), ('shutdown',)])

    def test_wrapper_creation_failure_closes_raw_handle(self):
        self.manager.device_factory.create.side_effect = RuntimeError('wrapper failed')
        with self.assertLogs('laser_hardware.thorlabs', level='ERROR'):
            with self.assertRaisesRegex(RuntimeError, 'wrapper failed'):
                ThorlabsStage()
        self.assertEqual(self.events, [('close', '90876914'), ('shutdown',)])

    def test_discovery_failure_shuts_down(self):
        self.manager.get_device_list.side_effect = RuntimeError('transport discovery aborted')
        with self.assertLogs('laser_hardware.thorlabs', level='ERROR'):
            with self.assertRaisesRegex(RuntimeError, 'transport discovery aborted'):
                ThorlabsStage()
        self.assertEqual(self.events, [('shutdown',)])

    def test_profile_failure_closes_newly_opened_channel(self):
        with patch('laser_hardware.thorlabs._XAAxis', side_effect=RuntimeError('profile failed')):
            with self.assertLogs('laser_hardware.thorlabs', level='ERROR'):
                with self.assertRaisesRegex(RuntimeError, 'profile failed'):
                    ThorlabsStage()
        self.assertEqual(self.events, [('close', '90876914'), ('shutdown',)])

    def test_startup_failure_runs_shutdown_and_releases_guard(self):
        self.manager.startup.side_effect = RuntimeError('discovery aborted')
        with self.assertLogs('laser_hardware.thorlabs', level='ERROR'):
            with self.assertRaisesRegex(RuntimeError, 'discovery aborted'):
                ThorlabsStage()
        self.assertEqual(self.events, [('shutdown',)])
        self.manager.startup.side_effect = None
        with ThorlabsStage():
            pass

    def test_close_failure_still_closes_other_channels_and_shuts_down(self):
        stage = ThorlabsStage()
        def close(handle):
            self.events.append(('close', handle))
            if handle == '90876913':
                raise RuntimeError('close failed')
        self.native.close.side_effect = close
        with self.assertRaisesRegex(RuntimeError, 'close failed'):
            stage.close()
        self.assertEqual(len(self.events), 4)
        self.assertEqual(self.events[-1], ('shutdown',))

    def test_body_exception_is_preserved_when_shutdown_also_fails(self):
        self.manager.shutdown.side_effect = RuntimeError('shutdown failed')
        with self.assertLogs('laser_hardware.thorlabs', level='ERROR'):
            with self.assertRaisesRegex(ValueError, 'measurement failed'):
                with ThorlabsStage():
                    raise ValueError('measurement failed')


if __name__ == '__main__':
    unittest.main()
