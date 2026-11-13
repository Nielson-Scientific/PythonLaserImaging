"""WaveForms SDK ctypes adapter. No third-party Python dependencies."""
import ctypes as C
import ctypes.util
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import sys
import time
from .core import ADC


@dataclass(frozen=True)
class AD3Config:
    serial: str | None = None  # Required when more than one AD3 is attached.
    channel: int = 0  # Zero-based: 0 = scope input 1, 1 = scope input 2.
    sample_rate_hz: float = 10000.0
    samples: int = 100
    range_v: float = 10.0  # Full span, centered on offset_v; not +/-10 V.
    offset_v: float = 0.0
    timeout_s: float = 5.0
    settling_s: float = 0.05
    dll_path: str | None = None


class DigilentAD3(ADC):
    """Fresh single-shot acquisition per measure(); arithmetic mean in volts.

    The adapter owns only its device handle. It does not configure analog outputs
    or supplies. The caller supplies any detector voltage-to-intensity calibration.
    """
    def __init__(self, config=AD3Config()):
        self.config = config
        if config.channel not in (0, 1):
            raise ValueError('channel must be 0 or 1')
        if not isinstance(config.samples, int) or config.samples <= 0:
            raise ValueError('samples must be a positive integer')
        for value in (config.sample_rate_hz, config.range_v, config.timeout_s):
            if not isfinite(value) or value <= 0:
                raise ValueError('Rate, range and timeout must be finite and positive')
        if not isfinite(config.offset_v) or not isfinite(config.settling_s) or config.settling_s < 0:
            raise ValueError('Invalid offset or settling time')
        path = config.dll_path or ctypes_library_path()
        self.dwf = C.CDLL(path)
        self.handle = C.c_int(0)
        self._bind()
        count = C.c_int()
        self._call('FDwfEnum', C.c_int(0), C.byref(count))
        matches = []
        for index in range(count.value):
            name, serial = C.create_string_buffer(64), C.create_string_buffer(64)
            self._call('FDwfEnumDeviceName', C.c_int(index), name)
            self._call('FDwfEnumSN', C.c_int(index), serial)
            if 'Analog Discovery 3' in name.value.decode():
                if config.serial is None or serial.value.decode() == config.serial:
                    matches.append(index)
        if len(matches) != 1:
            raise RuntimeError(f'Expected exactly one matching Analog Discovery 3; found {len(matches)}')
        try:
            self._call('FDwfDeviceOpen', C.c_int(matches[0]), C.byref(self.handle))
            self._configure()
        except BaseException:
            self.close()
            raise

    def _bind(self):
        I, D, P = C.c_int, C.c_double, C.POINTER
        signatures = {
            'FDwfEnum': [I, P(I)], 'FDwfEnumDeviceName': [I, P(C.c_char)],
            'FDwfEnumSN': [I, P(C.c_char)], 'FDwfDeviceOpen': [I, P(I)],
            'FDwfDeviceClose': [I], 'FDwfGetLastErrorMsg': [P(C.c_char)],
            'FDwfAnalogInChannelEnableSet': [I, I, I],
            'FDwfAnalogInChannelRangeSet': [I, I, D],
            'FDwfAnalogInChannelRangeGet': [I, I, P(D)],
            'FDwfAnalogInChannelOffsetSet': [I, I, D],
            'FDwfAnalogInFrequencySet': [I, D], 'FDwfAnalogInFrequencyGet': [I, P(D)],
            'FDwfAnalogInBufferSizeSet': [I, I], 'FDwfAnalogInBufferSizeGet': [I, P(I)],
            'FDwfAnalogInAcquisitionModeSet': [I, I],
            'FDwfAnalogInTriggerSourceSet': [I, C.c_ubyte],
            'FDwfAnalogInConfigure': [I, I, I],
            'FDwfAnalogInStatus': [I, I, P(C.c_ubyte)],
            'FDwfAnalogInStatusData': [I, I, P(D), I],
        }
        for name, args in signatures.items():
            fn = getattr(self.dwf, name)
            fn.argtypes = args
            fn.restype = None if name in ('FDwfDeviceClose', 'FDwfGetLastErrorMsg') else I

    def _call(self, name, *args):
        if not getattr(self.dwf, name)(*args):
            message = C.create_string_buffer(512)
            self.dwf.FDwfGetLastErrorMsg(message)
            raise RuntimeError(f'{name}: {message.value.decode(errors="replace")}')

    def _configure(self):
        cfg, h = self.config, self.handle
        self._call('FDwfAnalogInChannelEnableSet', h, C.c_int(-1), C.c_int(0))
        self._call('FDwfAnalogInChannelEnableSet', h, C.c_int(cfg.channel), C.c_int(1))
        self._call('FDwfAnalogInChannelRangeSet', h, C.c_int(cfg.channel), C.c_double(cfg.range_v))
        self._call('FDwfAnalogInChannelOffsetSet', h, C.c_int(cfg.channel), C.c_double(cfg.offset_v))
        self._call('FDwfAnalogInFrequencySet', h, C.c_double(cfg.sample_rate_hz))
        self._call('FDwfAnalogInBufferSizeSet', h, C.c_int(cfg.samples))
        self._call('FDwfAnalogInAcquisitionModeSet', h, C.c_int(0))  # acqmodeSingle
        self._call('FDwfAnalogInTriggerSourceSet', h, C.c_ubyte(0))  # trigsrcNone
        actual_count, rate, span = C.c_int(), C.c_double(), C.c_double()
        self._call('FDwfAnalogInBufferSizeGet', h, C.byref(actual_count))
        self._call('FDwfAnalogInFrequencyGet', h, C.byref(rate))
        self._call('FDwfAnalogInChannelRangeGet', h, C.c_int(cfg.channel), C.byref(span))
        if actual_count.value != cfg.samples:
            raise ValueError(f'Unsupported buffer size {cfg.samples}; SDK selected {actual_count.value}')
        self.actual_sample_rate_hz = rate.value
        self.actual_range_v = span.value
        if rate.value <= 0 or cfg.samples / rate.value >= cfg.timeout_s:
            raise ValueError('Acquisition duration exceeds timeout')
        self._call('FDwfAnalogInConfigure', h, C.c_int(1), C.c_int(0))
        time.sleep(cfg.settling_s)

    def measure_samples(self):
        """Return a new list of input voltages; raises on near-range clipping."""
        if not self.handle.value:
            raise RuntimeError('ADC is closed')
        self._call('FDwfAnalogInConfigure', self.handle, C.c_int(0), C.c_int(1))
        deadline = time.monotonic() + self.config.timeout_s
        state = C.c_ubyte()
        try:
            while True:
                self._call('FDwfAnalogInStatus', self.handle, C.c_int(1), C.byref(state))
                if state.value == 2:  # DwfStateDone
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('AD3 acquisition did not finish')
                time.sleep(0.001)
            data = (C.c_double * self.config.samples)()
            self._call('FDwfAnalogInStatusData', self.handle, C.c_int(self.config.channel),
                       data, C.c_int(self.config.samples))
            values = list(data)
            if any(not isfinite(v) for v in values):
                raise RuntimeError('ADC returned nonfinite samples')
            if any(abs(v - self.config.offset_v) >= self.actual_range_v * 0.495 for v in values):
                raise OverflowError('ADC input is near the selected range limit; increase range or reduce signal')
            return values
        except BaseException:
            # Abort timed-out/interrupted acquisition before allowing another call.
            try:
                self._call('FDwfAnalogInConfigure', self.handle, C.c_int(0), C.c_int(0))
            except Exception:
                pass
            raise

    def measure(self):
        values = self.measure_samples()
        return sum(values) / len(values)

    def close(self):
        if self.handle.value:
            self.dwf.FDwfDeviceClose(self.handle)
            self.handle = C.c_int(0)


def ctypes_library_path():
    found = C.util.find_library('dwf')
    if found:
        return found
    if sys.platform == 'win32':
        path = Path(r'C:\Windows\System32\dwf.dll')
    elif sys.platform == 'darwin':
        path = Path('/Library/Frameworks/dwf.framework/dwf')
    else:
        path = Path('/usr/lib/libdwf.so')
    if path.exists():
        return str(path)
    raise FileNotFoundError('Install Digilent WaveForms and its USB drivers, or set AD3Config.dll_path')
