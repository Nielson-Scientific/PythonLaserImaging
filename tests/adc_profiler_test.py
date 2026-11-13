"""Profile the real AD3: python -m tests.adc_profiler_test (from project root)."""
from statistics import mean
from time import perf_counter

from laser_hardware import DigilentAD3


def main():
    start = perf_counter()
    ADC = DigilentAD3()
    initialization_s = perf_counter() - start

    with ADC:
        print(f"DigilentAD3 initialization: {initialization_s * 1000:.3f} ms")
        durations_s = []
        for iteration in range(100):
            start = perf_counter()
            voltage = ADC.measure()
            elapsed_s = perf_counter() - start
            durations_s.append(elapsed_s)
            print(f"{iteration + 1:3d}: {elapsed_s * 1000:.3f} ms, {voltage:.6f} V")

        print(f"Measurement mean: {mean(durations_s) * 1000:.3f} ms")
        print(f"Measurement min:  {min(durations_s) * 1000:.3f} ms")
        print(f"Measurement max:  {max(durations_s) * 1000:.3f} ms")


if __name__ == "__main__":
    main()
