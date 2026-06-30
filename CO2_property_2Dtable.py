"""Generate Fluent-friendly 2D CO2 property tables with CoolProp.

This script rewrites create_CO2_properties.jl in Python.  It creates one CSV
file per property.  Each CSV uses pressure as rows and temperature as columns.
CoolProp calculations use Pa internally, while the output pressure column is
written in MPa for easier Fluent/UDF table use:

    P(MPa)/T(K), 220.0, 220.5, ...
    0.05, rho(P,T1), rho(P,T2), ...

The default ranges match the Julia script:
    T = 220.0:0.5:1500.0 K
    P = 50000.0:100000.0:40000000.0 Pa

Two grid modes are supported:
    uniform  : one temperature step and one pressure step for the full range
    critical : full-range base grid plus refined T/P points near the critical region

The Julia range with a fixed step stops at the last value not greater than the
maximum, so the default pressure grid ends at 39,950,000 Pa.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from CoolProp.CoolProp import PhaseSI, PropsSI


# Default settings for direct execution in PyCharm.
# Edit these values when you want to run without command-line arguments.
DEFAULT_FLUID = "CO2"
DEFAULT_T_MIN = 220.0
DEFAULT_T_MAX = 1500.0
DEFAULT_T_STEP = 0.5
DEFAULT_P_MIN = 50_000.0
DEFAULT_P_MAX = 40_000_000.0
DEFAULT_P_STEP = 100_000.0
DEFAULT_OUTPUT_DIR = Path(".")
DEFAULT_WORKERS = max(1, (os.cpu_count() or 2) - 1)
DEFAULT_ERROR_LOG = Path("CO2_2Dtable_errors.log")
DEFAULT_GRID_MODE = "uniform"
DEFAULT_CRITICAL_T_MIN = 300.0
DEFAULT_CRITICAL_T_MAX = 310.0
DEFAULT_CRITICAL_T_STEP = 0.05
DEFAULT_CRITICAL_P_MIN = 7.0e6
DEFAULT_CRITICAL_P_MAX = 8.0e6
DEFAULT_CRITICAL_P_STEP = 10_000.0


PROPERTY_FILES = {
    "density": "co2_density.csv",
    "viscosity": "co2_viscosity.csv",
    "cp": "co2_cp.csv",
    "conductivity": "co2_conductivity.csv",
    "phase": "co2_phase.csv",
}


@dataclass(frozen=True)
class TableConfig:
    fluid: str
    grid_mode: str
    t_min: float
    t_max: float
    t_step: float
    p_min: float
    p_max: float
    p_step: float
    critical_t_min: float
    critical_t_max: float
    critical_t_step: float
    critical_p_min: float
    critical_p_max: float
    critical_p_step: float
    output_dir: Path
    workers: int
    error_log: Path


def stepped_range(start: float, stop: float, step: float) -> list[float]:
    if step <= 0:
        raise ValueError("step must be positive")
    if stop < start:
        raise ValueError("stop must be greater than or equal to start")

    values: list[float] = []
    current = float(start)
    tolerance = abs(step) * 1.0e-9

    while current <= stop + tolerance:
        values.append(round(current, 10))
        current += step

    return values


def merge_grids(base_grid: list[float], refined_grid: list[float]) -> list[float]:
    values = sorted(round(value, 10) for value in [*base_grid, *refined_grid])
    merged: list[float] = []
    tolerance = 1.0e-9

    for value in values:
        if not merged or abs(value - merged[-1]) > tolerance:
            merged.append(value)

    return merged


def clipped_stepped_range(
    start: float,
    stop: float,
    step: float,
    global_min: float,
    global_max: float,
) -> list[float]:
    clipped_start = max(start, global_min)
    clipped_stop = min(stop, global_max)
    if clipped_stop < clipped_start:
        return []
    return stepped_range(clipped_start, clipped_stop, step)


def build_axis_grid(
    start: float,
    stop: float,
    step: float,
    grid_mode: str,
    critical_start: float,
    critical_stop: float,
    critical_step: float,
) -> list[float]:
    base_grid = stepped_range(start, stop, step)
    if grid_mode == "uniform":
        return base_grid

    refined_grid = clipped_stepped_range(
        critical_start,
        critical_stop,
        critical_step,
        start,
        stop,
    )
    return merge_grids(base_grid, refined_grid)


def calc_row(args: tuple[int, float, list[float], str]) -> tuple[int, float, dict[str, list[float]], list[str]]:
    row_index, pressure, temperatures, fluid = args
    row_data = {name: [] for name in PROPERTY_FILES}
    errors: list[str] = []

    for temperature in temperatures:
        try:
            phase = PhaseSI("T", temperature, "P", pressure, fluid)
            density = PropsSI("D", "T", temperature, "P", pressure, fluid)
            viscosity = PropsSI("V", "T", temperature, "P", pressure, fluid)
            cp = PropsSI("C", "T", temperature, "P", pressure, fluid)
            conductivity = PropsSI("L", "T", temperature, "P", pressure, fluid)
        except Exception as exc:  # CoolProp raises backend-specific exceptions.
            errors.append(f"Error at P={pressure} Pa, T={temperature} K: {exc}")
            phase = "invalid"
            density = math.nan
            viscosity = math.nan
            cp = math.nan
            conductivity = math.nan

        row_data["density"].append(density)
        row_data["viscosity"].append(viscosity)
        row_data["cp"].append(cp)
        row_data["conductivity"].append(conductivity)
        row_data["phase"].append(phase)

    return row_index, pressure, row_data, errors


def write_property_table(path: Path, temperatures: list[float], rows: list[tuple[float, list[float]]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["P(MPa)/T(K)", *[str(temperature) for temperature in temperatures]])
        for pressure, values in rows:
            writer.writerow([pressure / 1.0e6, *values])


def write_error_log(path: Path, errors: list[str]) -> None:
    if not errors:
        return
    with path.open("w", encoding="utf-8") as file:
        for error in errors:
            file.write(error)
            file.write("\n")


def generate_tables(config: TableConfig) -> None:
    temperatures = build_axis_grid(
        config.t_min,
        config.t_max,
        config.t_step,
        config.grid_mode,
        config.critical_t_min,
        config.critical_t_max,
        config.critical_t_step,
    )
    pressures = build_axis_grid(
        config.p_min,
        config.p_max,
        config.p_step,
        config.grid_mode,
        config.critical_p_min,
        config.critical_p_max,
        config.critical_p_step,
    )
    total_rows = len(pressures)
    total_points = len(temperatures) * len(pressures)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    error_log = config.error_log
    if not error_log.is_absolute():
        error_log = config.output_dir / error_log

    print(f"Fluid: {config.fluid}")
    print(f"Grid mode: {config.grid_mode}")
    print(f"Temperature grid: {len(temperatures)} points, {temperatures[0]}-{temperatures[-1]} K")
    print(
        f"Pressure grid: {len(pressures)} points, "
        f"{pressures[0]}-{pressures[-1]} Pa "
        f"({pressures[0] / 1.0e6}-{pressures[-1] / 1.0e6} MPa in CSV)"
    )
    print(f"Total states: {total_points}")
    print(f"Workers: {config.workers}")
    if config.grid_mode == "critical":
        print(
            "Critical refinement: "
            f"T={config.critical_t_min}-{config.critical_t_max} K "
            f"step {config.critical_t_step} K; "
            f"P={config.critical_p_min}-{config.critical_p_max} Pa "
            f"step {config.critical_p_step} Pa"
        )

    tasks = [
        (row_index, pressure, temperatures, config.fluid)
        for row_index, pressure in enumerate(pressures)
    ]

    property_rows: dict[str, list[tuple[int, float, list[float]]]] = {
        name: [] for name in PROPERTY_FILES
    }
    all_errors: list[str] = []
    started = time.time()
    completed = 0

    with ProcessPoolExecutor(max_workers=config.workers) as executor:
        futures = [executor.submit(calc_row, task) for task in tasks]

        for future in as_completed(futures):
            row_index, pressure, row_data, errors = future.result()
            completed += 1

            for property_name, values in row_data.items():
                property_rows[property_name].append((row_index, pressure, values))

            all_errors.extend(errors)

            if completed == 1 or completed % 10 == 0 or completed == total_rows:
                elapsed = time.time() - started
                print(f"Processed {completed}/{total_rows} pressure rows; elapsed {elapsed:.1f} s")

    for property_name, rows in property_rows.items():
        rows.sort(key=lambda item: item[0])
        output_path = config.output_dir / PROPERTY_FILES[property_name]
        write_property_table(
            output_path,
            temperatures,
            [(pressure, values) for _, pressure, values in rows],
        )
        print(f"Saved {output_path}")

    write_error_log(error_log, all_errors)
    if all_errors:
        print(f"Some states failed. See {error_log}")

    print("Data processing completed.")


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def parse_args() -> TableConfig:
    parser = argparse.ArgumentParser(
        description="Generate Fluent-friendly 2D CO2 property CSV tables with CoolProp."
    )
    parser.add_argument("--fluid", default=DEFAULT_FLUID, help=f"CoolProp fluid name. Default: {DEFAULT_FLUID}")
    parser.add_argument(
        "--grid-mode",
        choices=("uniform", "critical"),
        default=DEFAULT_GRID_MODE,
        help="Grid mode: uniform uses one step over the full range; critical adds refined points near the critical region.",
    )
    parser.add_argument("--t-min", type=float, default=DEFAULT_T_MIN, help="Minimum temperature, K")
    parser.add_argument("--t-max", type=float, default=DEFAULT_T_MAX, help="Maximum temperature, K")
    parser.add_argument("--t-step", type=positive_float, default=DEFAULT_T_STEP, help="Temperature step, K")
    parser.add_argument("--p-min", type=float, default=DEFAULT_P_MIN, help="Minimum pressure, Pa")
    parser.add_argument("--p-max", type=float, default=DEFAULT_P_MAX, help="Maximum pressure, Pa")
    parser.add_argument("--p-step", type=positive_float, default=DEFAULT_P_STEP, help="Pressure step, Pa")
    parser.add_argument(
        "--critical-t-min",
        type=float,
        default=DEFAULT_CRITICAL_T_MIN,
        help="Critical-region minimum temperature, K",
    )
    parser.add_argument(
        "--critical-t-max",
        type=float,
        default=DEFAULT_CRITICAL_T_MAX,
        help="Critical-region maximum temperature, K",
    )
    parser.add_argument(
        "--critical-t-step",
        type=positive_float,
        default=DEFAULT_CRITICAL_T_STEP,
        help="Critical-region temperature step, K",
    )
    parser.add_argument(
        "--critical-p-min",
        type=float,
        default=DEFAULT_CRITICAL_P_MIN,
        help="Critical-region minimum pressure, Pa",
    )
    parser.add_argument(
        "--critical-p-max",
        type=float,
        default=DEFAULT_CRITICAL_P_MAX,
        help="Critical-region maximum pressure, Pa",
    )
    parser.add_argument(
        "--critical-p-step",
        type=positive_float,
        default=DEFAULT_CRITICAL_P_STEP,
        help="Critical-region pressure step, Pa",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for output CSV files")
    parser.add_argument(
        "--workers",
        type=positive_int,
        default=DEFAULT_WORKERS,
        help="Number of parallel worker processes",
    )
    parser.add_argument(
        "--error-log",
        type=Path,
        default=DEFAULT_ERROR_LOG,
        help="Path for failed CoolProp states",
    )

    args = parser.parse_args()
    return TableConfig(
        fluid=args.fluid,
        grid_mode=args.grid_mode,
        t_min=args.t_min,
        t_max=args.t_max,
        t_step=args.t_step,
        p_min=args.p_min,
        p_max=args.p_max,
        p_step=args.p_step,
        critical_t_min=args.critical_t_min,
        critical_t_max=args.critical_t_max,
        critical_t_step=args.critical_t_step,
        critical_p_min=args.critical_p_min,
        critical_p_max=args.critical_p_max,
        critical_p_step=args.critical_p_step,
        output_dir=args.output_dir,
        workers=args.workers,
        error_log=args.error_log,
    )


if __name__ == "__main__":
    generate_tables(parse_args())
