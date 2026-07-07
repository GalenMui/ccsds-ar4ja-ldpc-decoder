#!/usr/bin/env python3
"""Run open-source RTL elaboration checks available in this repository."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "sim" / "build"

ICARUS_WARNING_FLAGS = [
    "-Wall",
    # These two are known Icarus 11 diagnostics for generated packages and
    # indexed unpacked arrays. They do not indicate mismatched hardware.
    "-Wno-timescale",
    "-Wno-sensitivity-entire-array",
]


@dataclass(frozen=True)
class Step:
    name: str
    command: list[str]


def run(step: Step) -> int:
    print(f"+ {' '.join(step.command)}", flush=True)
    completed = subprocess.run(step.command, cwd=ROOT, check=False)
    if completed.returncode == 0:
        print(f"PASS {step.name}")
    else:
        print(f"FAIL {step.name} ({completed.returncode})")
    return completed.returncode


def main() -> int:
    if shutil.which("iverilog") is None:
        print("ERROR: iverilog is required for make lint")
        return 127

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    common = ["iverilog", *ICARUS_WARNING_FLAGS, "-g2012"]
    assertion_common = ["iverilog", "-g2012", "-DLDPC_ENABLE_ASSERTS"]

    steps = [
        Step(
            "axis_ip_elaboration",
            [
                *common,
                "-s",
                "ldpc_axis_decoder_ip",
                "-o",
                "sim/build/lint_axis_ip.vvp",
                "-c",
                "rtl/ldpc_sources.f",
            ],
        ),
        Step(
            "axis_ip_assertion_elaboration",
            [
                *assertion_common,
                "-s",
                "ldpc_axis_decoder_ip",
                "-o",
                "sim/build/lint_axis_ip_asserts.vvp",
                "-c",
                "rtl/ldpc_sources.f",
            ],
        ),
        Step(
            "syndrome_checker_elaboration",
            [
                *common,
                "-s",
                "syndrome_checker",
                "-o",
                "sim/build/lint_syndrome_checker.vvp",
                "rtl/ar4ja_1024_pkg.sv",
                "rtl/syndrome_checker.sv",
            ],
        ),
    ]

    results = [run(step) for step in steps]
    if all(code == 0 for code in results):
        print("Lint/elaboration summary: PASS")
        return 0
    print("Lint/elaboration summary: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
