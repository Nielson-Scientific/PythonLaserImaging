# Python hardware control

Run commands from this project's root with 64-bit Python 3.10 or newer.

```powershell
python -m pip install -r requirements-hardware.txt
python -m examples.simple_control
python -m unittest discover -s tests -p test_python_hardware.py
```

The example defaults to simulation. `python -m examples.simple_control --hardware`
connects and reads real devices without issuing motion commands.

## Hardware recorded in the supplied C++ files

| Role | Device/profile | Serial / channel |
| --- | --- | --- |
| Controller | Thorlabs BSC203 | 70876912 |
| Z | SCC201, NanoMax 300 Z Axis (DRV001) | 90876913 / 1 |
| X | SCC201, NanoMax 300 X Axis (DRV001) | 90876914 / 2 |
| Y | SCC201, NanoMax 300 Y Axis (DRV001) | 90876915 / 3 |
| ADC | Digilent Analog Discovery 3 | No serial or acquisition parameters supplied |

The source uses the XA SDK, so this implementation uses the official `thorlabs-xa`
package. Its Python API was inspected at version 1.9.2.29178. The original files
are reference material; their TODO comments are not additional user instructions.

## Drivers and SDKs

* Install the **Thorlabs XA software and USB drivers** appropriate for the BSC203.
  Verify detection and the NanoMax/DRV001 profiles in the vendor GUI, then close
  the GUI before opening Python. The official Python package includes its native
  binary: https://pypi.org/project/thorlabs-xa/1.9.2.29178/ . The C++ XA SDK,
  a C++ compiler, Kinesis, and pythonnet are not used by this Python adapter.
* Install **Digilent WaveForms**, including **WaveForms Runtime / Adept USB
  drivers** and **WaveForms SDK**. The Python adapter loads the installed `dwf`
  runtime directly through ctypes; do not install an unrelated package named dwf.
  Official setup: https://digilent.com/reference/test-and-measurement/guides/waveforms-sdk-getting-started .
  Match the native runtime architecture to Python. If DLL discovery fails, pass
  `AD3Config(dll_path=r'C:\path\to\dwf.dll')`.
* Python's standard library is sufficient for simulation and the AD3 wrapper.
  No SDKs were installed globally during implementation. The expected XA install
  directory was absent on this machine.

## Writing a script

```python
from laser_hardware import ThorlabsStage, DigilentAD3, AD3Config

with ThorlabsStage() as stage, DigilentAD3(AD3Config(
    channel=0, sample_rate_hz=10_000, samples=100, range_v=10.0,
    # serial='YOUR_AD3_SERIAL',  # Specify if multiple AD3s are connected.
)) as ADC:
    stage_move_relative = stage.stage_move_relative
    stage_move_absolute = stage.stage_move_absolute

    print(stage.position())        # {'x': ..., 'y': ..., 'z': ...}, in um
    # stage.home('z')              # Explicit physical homing, if needed.
    # Uncomment motion only after checking homing, origin, and clearances.
    # stage_move_relative(10, 0, 0)
    # stage_move_absolute(x=100, y=200, z=50)
    # stage_move_absolute(z=75)    # X/Y remain unchanged.
    print(ADC.measure())           # Fresh averaged voltage, in volts.
    # samples_v = ADC.measure_samples()
    # stage.stop()
```

All motion arguments are **micrometres**. Absolute coordinates use the controller's
current origin; connection does not establish an origin or home automatically.
Moves block using the XA completion timeout (default 60 s per axis), executing
X then Y then Z. These are sequential paths, not synchronized diagonal moves.
All targets are checked before starting motion. Travel bounds come from the XA
connected-product profile; optional `limits={'x': (0, 500), ...}` further restricts
travel. These limits do not describe collisions or optical clearances. An error
or interruption during a move attempts to stop every axis; earlier axes may
already have moved. Software stop requires a responsive connection. Homing uses
the controller's configured procedure and can traverse outside user soft limits.
Closing releases connections; it does not home or disable motors.

The ADC settings above are **chosen defaults**, not settings recovered from the
files. Channel 0 is physical Scope 1; channel 1 is Scope 2. `range_v` is the full
voltage span around `offset_v`. Use the differential input wiring and input limits
in the AD3 manual. BNC accessory attenuation/coupling must match the signal;
external probe attenuation is not inferred. `actual_sample_rate_hz` and
`actual_range_v` report settings selected by the SDK. Near-range samples raise
`OverflowError` instead of silently returning clipped data. This is a range check,
not detection of upstream detector/amplifier saturation. `measure()` returns raw
volts, not calibrated optical intensity; apply your detector calibration separately.

Each call starts a fresh single-shot buffer and returns its arithmetic mean.
Defaults collect 100 samples at approximately 10 kHz; a 50 ms configuration
settling delay precedes the first capture. Buffer sizes unsupported by the device
configuration are rejected. Timeout aborts the acquisition. The hardware objects
are intended for single-threaded scripts, with one owner per physical device;
do not share the XA session with another XA client in the same process.

## Replacing hardware

`ADC` and `Axis` in `laser_hardware/core.py` define the capability contracts. A new
ADC implements `measure()` and `close()`. A new axis implements position, target
validation, blocking absolute motion, home, stop, and close. Compose any three
axes with `Stage(x=..., y=..., z=...)`; the high-level motion commands stay the
same. This also allows XY hardware and a separate Z actuator to be mixed.
`SimulatedAxis` and `SimulatedADC` provide examples without vendor dependencies.

Validation covers coordinate composition, preflight limits, stop and cleanup on
failure, XA unit/count conversion, fresh ADC captures, clipping, and timeout
abort using fake backends. Real motion, USB discovery, and analog accuracy still
require commissioning with the physical hardware.
