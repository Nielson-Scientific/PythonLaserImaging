from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from math import isfinite


class ADC(AbstractContextManager, ABC):
    """A detector input; measure returns mean input voltage in volts."""
    @abstractmethod
    def measure(self) -> float: ...

    @abstractmethod
    def close(self): ...

    def __exit__(self, *args):
        self.close()


class Axis(ABC):
    """One linear axis in micrometres; move_absolute blocks until complete."""
    @abstractmethod
    def position(self) -> float: ...

    @abstractmethod
    def validate_target(self, target: float): ...

    @abstractmethod
    def move_absolute(self, target: float): ...

    @abstractmethod
    def home(self): ...

    @abstractmethod
    def stop(self): ...

    @abstractmethod
    def close(self): ...


def attempt_all(actions):
    """Attempt every cleanup operation even if a previous one fails."""
    first = None
    for action in actions:
        try:
            action()
        except Exception as exc:
            first = first or exc
    if first:
        raise first


class Stage(AbstractContextManager):
    """Compose independent X/Y/Z backends. Moves are sequential X, Y, Z.

    Calls block; this object is intended for a single controlling thread.
    Partial motion can occur on device failure; failed moves stop all axes.
    """
    def __init__(self, x: Axis, y: Axis, z: Axis):
        self.axes = dict(x=x, y=y, z=z)
        self._closed = False

    def _check_open(self):
        if self._closed:
            raise RuntimeError('Stage is closed')

    def position(self):
        self._check_open()
        return {name: axis.position() for name, axis in self.axes.items()}

    def stage_move_absolute(self, x=None, y=None, z=None):
        """Omitted coordinates stay unchanged; no arguments performs no motion."""
        self._check_open()
        targets = {k: float(v) for k, v in dict(x=x, y=y, z=z).items() if v is not None}
        for name, target in targets.items():
            if not isfinite(target):
                raise ValueError('Position must be finite')
            self.axes[name].validate_target(target)
        try:
            for name, target in targets.items():
                self.axes[name].move_absolute(target)
        except BaseException:
            try:
                self.stop()
            except Exception:
                pass
            raise

    def stage_move_relative(self, x=0, y=0, z=0):
        self._check_open()
        deltas = dict(x=x, y=y, z=z)
        if any(not isfinite(float(v)) for v in deltas.values()):
            raise ValueError('Distance must be finite')
        targets = {k: self.axes[k].position() + float(v)
                   for k, v in deltas.items() if v != 0}
        self.stage_move_absolute(**targets)

    def home(self, *axes):
        """Explicitly home named axes, e.g. home('z'); no names homes X/Y/Z."""
        self._check_open()
        names = axes or tuple(self.axes)
        if any(name not in self.axes for name in names):
            raise ValueError('Axis names must be x, y, or z')
        try:
            for name in names:
                self.axes[name].home()
        except BaseException:
            try:
                self.stop()
            except Exception:
                pass
            raise

    def stop(self):
        self._check_open()
        attempt_all(axis.stop for axis in self.axes.values())

    def close(self):
        if not self._closed:
            self._closed = True
            attempt_all(axis.close for axis in self.axes.values())

    def __exit__(self, *args):
        self.close()


class SimulatedAxis(Axis):
    def __init__(self, limits=(0.0, 4000.0)):
        self.limits = limits
        self._position = 0.0
        self.closed = False

    def _check(self):
        if self.closed:
            raise RuntimeError('Axis is closed')

    def position(self):
        self._check()
        return self._position

    def validate_target(self, target):
        self._check()
        if not isfinite(target) or not self.limits[0] <= target <= self.limits[1]:
            raise ValueError(f'Target {target} outside limits {self.limits}')

    def move_absolute(self, target):
        self.validate_target(target)
        self._position = target

    def home(self):
        self.move_absolute(0.0)

    def stop(self):
        self._check()

    def close(self):
        self.closed = True


class SimulatedADC(ADC):
    def __init__(self, voltage=0.5):
        self.voltage = voltage
        self.closed = False

    def measure(self):
        if self.closed:
            raise RuntimeError('ADC is closed')
        return self.voltage

    def close(self):
        self.closed = True
