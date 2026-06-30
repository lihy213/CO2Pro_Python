"""Generate a 2D CO2 property table with CoolProp.

This is a Python rewrite of CO2_STARCCM2.jl.  It keeps the same default
temperature and pressure ranges, writes the same physical quantities, and
uses process-based parallelism for faster CoolProp evaluations.
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from CoolProp.CoolProp import PropsSI


# Default settings for direct execution in PyCharm.
# Edit these values when you want to run the script without command-line args.
DEFAULT_FLUID = "CO2"
DEFAULT_T_MIN = 220.0
DEFAULT_T_MAX = 1500.0
DEFAULT_T_COUNT = 1500
DEFAULT_P_MIN = 0.05e6
DEFAULT_P_MAX = 40.0e6
DEFAULT_P_COUNT = 1000
DEFAULT_OUTPUT = Path("CO2.csv")
DEFAULT_ERROR_LOG = Path("CO2_property_errors.log")
DEFAULT_WORKERS = max(1, (os.cpu_count() or 2) - 1)


CSV_COLUMNS = [
    "Pressure",
    "Temperature",
    "Density",
    "Viscosity",
    "Entropy",
    "Enthalpy",
    "SpecificHeatCapacity",
    "Cv",
    "Gamma",
    "ThermalConductivity",
    "SpeedOfSound",
]


@dataclass(frozen=True)
class TableConfig:
    fluid: str
    t_min: float
    t_max: float
    t_count: int
    p_min: float
    p_max: float
    p_count: int
    output: Path
    error_log: Path
    workers: int


def linspace(start: float, stop: float, count: int) -> list[float]:
    if count <= 0:
        raise ValueError("count must be positive")
    if count == 1:
        return [float(start)]
    step = (stop - start) / (count - 1)
    return [start + i * step for i in range(count)]


def calc_properties(p: float, t: float, fluid: str) -> list[float]:
    density = PropsSI("D", "T", t, "P", p, fluid)
    viscosity = PropsSI("V", "T", t, "P", p, fluid)
    entropy = PropsSI("S", "T", t, "P", p, fluid)
    enthalpy = PropsSI("H", "T", t, "P", p, fluid)
    cp = PropsSI("C", "T", t, "P", p, fluid)
    cv = PropsSI("CVMASS", "T", t, "P", p, fluid)
    gamma = cp / cv
    conductivity = PropsSI("L", "T", t, "P", p, fluid)
    speed_of_sound = PropsSI("A", "T", t, "P", p, fluid)
    return [
        p,
        t,
        density,
        viscosity,
        entropy,
        enthalpy,
        cp,
        cv,
        gamma,
        conductivity,
        speed_of_sound,
    ]


def calc_temperature_row(args: tuple[int, float, list[float], str]) -> tuple[int, list[list[float]], list[str]]:
    row_index, temperature, pressures, fluid = args
    rows: list[list[float]] = []
    errors: list[str] = []

    for pressure in pressures:
        try:
            rows.append(calc_properties(pressure, temperature, fluid))
        except Exception as exc:  # CoolProp raises several backend-specific exceptions.
            errors.append(f"Error at T={temperature} K and p={pressure} Pa: {exc}")

    return row_index, rows, errors


def write_error_log(path: Path, errors: Iterable[str]) -> None:
    with path.open("a", encoding="utf-8") as file:
        for error in errors:
            file.write(error)
            file.write("\n")


def generate_table(config: TableConfig) -> None:
    temperatures = linspace(config.t_min, config.t_max, config.t_count)
    pressures = linspace(config.p_min, config.p_max, config.p_count)
    total_points = len(temperatures) * len(pressures)

    config.output.parent.mkdir(parents=True, exist_ok=True)
    if config.error_log.exists():
        config.error_log.unlink()

    tasks = [
        (row_index, temperature, pressures, config.fluid)
        for row_index, temperature in enumerate(temperatures)
    ]

    started = time.time()
    completed_rows = 0
    written_points = 0

    with config.output.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(CSV_COLUMNS)

        with ProcessPoolExecutor(max_workers=config.workers) as executor:
            future_to_row = {
                executor.submit(calc_temperature_row, task): task[0]
                for task in tasks
            }

            for future in as_completed(future_to_row):
                row_index, rows, errors = future.result()
                writer.writerows(rows)
                written_points += len(rows)
                completed_rows += 1

                if errors:
                    write_error_log(config.error_log, errors)

                if completed_rows == 1 or completed_rows % 25 == 0 or completed_rows == len(temperatures):
                    elapsed = time.time() - started
                    print(
                        f"Completed {completed_rows}/{len(temperatures)} temperature rows; "
                        f"written {written_points}/{total_points} valid points; "
                        f"elapsed {elapsed:.1f} s"
                    )

                # Keep the same temperature-major logical order as the Julia code when
                # users sort by Temperature and Pressure; writing is completion-ordered
                # for better parallel throughput.
                _ = row_index

    print(f"Data saved to {config.output}")
    if config.error_log.exists():
        print(f"Some states failed. See {config.error_log}")
    print("Data processing completed.")


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def parse_args() -> TableConfig:
    parser = argparse.ArgumentParser(
        description="Generate a pressure-temperature CO2 property table with CoolProp."
    )
    parser.add_argument("--fluid", default=DEFAULT_FLUID, help=f"CoolProp fluid name. Default: {DEFAULT_FLUID}")
    parser.add_argument("--t-min", type=float, default=DEFAULT_T_MIN, help="Minimum temperature, K")
    parser.add_argument("--t-max", type=float, default=DEFAULT_T_MAX, help="Maximum temperature, K")
    parser.add_argument("--t-count", type=positive_int, default=DEFAULT_T_COUNT, help="Number of temperature points")
    parser.add_argument("--p-min", type=float, default=DEFAULT_P_MIN, help="Minimum pressure, Pa")
    parser.add_argument("--p-max", type=float, default=DEFAULT_P_MAX, help="Maximum pressure, Pa")
    parser.add_argument("--p-count", type=positive_int, default=DEFAULT_P_COUNT, help="Number of pressure points")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output CSV path")
    parser.add_argument(
        "--error-log",
        type=Path,
        default=DEFAULT_ERROR_LOG,
        help="Path for failed CoolProp states",
    )
    parser.add_argument(
        "--workers",
        type=positive_int,
        default=DEFAULT_WORKERS,
        help="Number of parallel worker processes",
    )

    args = parser.parse_args()
    return TableConfig(
        fluid=args.fluid,
        t_min=args.t_min,
        t_max=args.t_max,
        t_count=args.t_count,
        p_min=args.p_min,
        p_max=args.p_max,
        p_count=args.p_count,
        output=args.output,
        error_log=args.error_log,
        workers=args.workers,
    )


if __name__ == "__main__":
    generate_table(parse_args())
