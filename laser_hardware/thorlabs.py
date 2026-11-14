"""Thorlabs XA backend, verified against official thorlabs-xa 1.9.2.29178."""
from math import isfinite
import logging
from threading import Lock
from .core import Axis, Stage

_session_lock = Lock()
_log = logging.getLogger(__name__)


def _open_device(manager, info, mode):
    """Keep ownership if XA opens a handle but Python wrapper creation fails.

    Mirrors SystemManager.open_device in the pinned SDK, adding rollback.
    """
    native = manager.native_functions
    handle = native.open(info.device, info.transport, mode)
    try:
        return manager.device_factory.create(handle, native.get_device_info(handle))
    except BaseException:
        try:
            native.close(handle)
        except Exception:
            _log.exception('XA failed to close handle after wrapper creation failed')
        raise


def _matches_device(info, serial, part, parent=None):
    """XA fixed-width discovery fields may contain surrounding whitespace."""
    return (info.device.strip() == serial.strip()
            and info.part_number.strip() == part
            and (parent is None or info.parent_device.strip() == parent.strip()))


def _describe_devices(devices):
    if not devices:
        return 'XA returned no devices.'
    return '\n'.join(
        f"  part={d.part_number!r}, device={d.device!r}, "
        f"parent={d.parent_device!r}, transport={d.transport!r}"
        for d in devices)


class _XAAxis(Axis):
    def __init__(self, device, enums, product, timeout_ms, limits=None):
        self.device, self.e, self.timeout_ms = device, enums, timeout_ms
        # Explicitly select the same profile used in the supplied C++ adapter.
        if product not in device.get_supported_connected_products():
            raise RuntimeError(f'Unsupported stage profile: {product}')
        device.set_connected_product(product)
        info = device.get_connected_product_info()
        if info.product_name != product:
            raise RuntimeError(f'Profile mismatch: {info.product_name}')
        self.unit = info.unit_type
        self.factor = self._factor(self.unit)
        self.limits = (info.min_position * self.factor, info.max_position * self.factor)
        if not all(isfinite(v) for v in self.limits) or self.limits[0] >= self.limits[1]:
            raise RuntimeError('XA profile did not provide valid travel limits')
        if limits is not None:
            self.limits = (max(self.limits[0], limits[0]), min(self.limits[1], limits[1]))
            if self.limits[0] >= self.limits[1]:
                raise ValueError('User limits do not overlap profile travel')
        self.position()  # Fail at connection time on conversion/configuration errors.

    def _factor(self, unit):
        if unit == self.e.TLMC_Unit.TLMC_Unit_Millimetres:
            return 1000.0
        if unit == self.e.TLMC_Unit.TLMC_Unit_Micrometres:
            return 1.0
        raise RuntimeError(f'Unsupported XA distance unit: {unit}')

    def position(self):
        value, unit = self.device.convert_from_device_units_to_physical(
            self.e.TLMC_ScaleType.TLMC_ScaleType_Distance,
            self.device.get_position_counter(1000))
        return value * self._factor(unit)

    def validate_target(self, target):
        if not isfinite(target) or not self.limits[0] <= target <= self.limits[1]:
            raise ValueError(f'Target {target} um outside {self.limits}')

    def move_absolute(self, target):
        self.validate_target(target)
        counts = self.device.convert_from_physical_to_device(
            self.e.TLMC_ScaleType.TLMC_ScaleType_Distance, self.unit, target / self.factor)
        if not -(2**31) <= counts < 2**31:
            raise ValueError('Target exceeds XA signed 32-bit motion range')
        self.device.move(self.e.TLMC_MoveMode.TLMC_MoveMode_Absolute, counts, self.timeout_ms)

    def home(self):
        self.device.home(self.timeout_ms)

    def stop(self):
        self.device.stop(self.e.TLMC_StopMode.TLMC_StopMode_Immediate, 1000)

    def close(self):
        self.device.close()


class ThorlabsStage(Stage):
    """Owns one XA session. Do not share with other XA clients in this process.

    Opens SCC201 children directly, never the parent transport a second time.
    Connection configures profiles but never homes or commands motion.
    """
    def __init__(self, controller='70876912', channels=None, timeout_ms=60000, limits=None):
        from thorlabs_xa.shared.system_manager import SystemManager
        from thorlabs_xa.shared import enums
        if not isinstance(timeout_ms, int) or timeout_ms <= 0:
            raise ValueError('timeout_ms must be a positive integer')
        channels = channels or dict(x='90876914', y='90876915', z='90876913')
        if set(channels) != {'x', 'y', 'z'} or len(set(channels.values())) != 3:
            raise ValueError('Provide distinct x, y, z channel serials')
        if not _session_lock.acquire(blocking=False):
            raise RuntimeError('Another ThorlabsStage XA session is already open in this process; '
                               'close it before creating a new one.')
        self._owns_session = True
        self._closed = True
        self._devices = []
        self.manager = None
        operation = 'creating XA manager'
        try:
            self.manager = SystemManager.instance()
            operation = 'starting XA'
            self.manager.startup()
            operation = 'discovering XA devices'
            devices = self.manager.get_device_list()
            if not any(_matches_device(d, controller, 'BSC203') for d in devices):
                raise RuntimeError(
                    f'BSC203 {controller!r} not discovered.\n{_describe_devices(devices)}\n'
                    'Check controller power and USB, verify detection in the Thorlabs XA '
                    'GUI, then close other controller applications before retrying. '
                    'If XA reports a different controller identifier, pass that exact '
                    'identifier as controller=... .')
            axes = {}
            for name in ('x', 'y', 'z'):
                matches = [d for d in devices
                           if _matches_device(d, channels[name], 'SCC201', controller)]
                if len(matches) != 1:
                    raise RuntimeError(
                        f'Expected one SCC201 {channels[name]!r} under {controller!r}.\n'
                        f'{_describe_devices(devices)}')
                info = matches[0]
                operation = f'opening {name.upper()} channel {info.device!r} on {info.transport!r}'
                device = _open_device(self.manager, info,
                    enums.TLMC_OperatingMode.TLMC_OperatingMode_Default)
                self._devices.append(device)
                operation = f'configuring {name.upper()} channel {info.device!r}'
                axes[name] = _XAAxis(device, enums,
                    f'NanoMax 300 {name.upper()} Axis (DRV001)', timeout_ms,
                    (limits or {}).get(name))
            super().__init__(**axes)
        except BaseException as exc:
            _log.error('Thorlabs connection failed while %s: %s', operation, exc)
            for error in self._release_session():
                _log.error('Additional XA cleanup failure: %s', error)
            raise

    def _release_session(self):
        """Close children in reverse order, then shut down; attempt every step."""
        errors = []
        try:
            actions = [d.close for d in reversed(self._devices)]
            if self.manager is not None:
                actions.append(self.manager.shutdown)
            for action in actions:
                try:
                    action()
                except BaseException as exc:
                    errors.append(exc)
        finally:
            self._devices.clear()
            self._closed = True
            if self._owns_session:
                self._owns_session = False
                _session_lock.release()
        return errors

    def close(self):
        if self._owns_session:
            errors = self._release_session()
            if errors:
                for error in errors[1:]:
                    _log.error('Additional XA cleanup failure: %s', error)
                raise errors[0]

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.close()
        except BaseException:
            if exc is None:
                raise
            _log.exception('XA cleanup failed while handling another exception')
