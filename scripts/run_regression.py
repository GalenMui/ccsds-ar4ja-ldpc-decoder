#!/usr/bin/env python3
"""Run the repository regression from the repository root."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "sim" / "build"
DECODER_RTL = [
    "rtl/ar4ja_1024_pkg.sv",
    "rtl/ldpc_schedule_pkg.sv",
    "rtl/posterior_memory.sv",
    "rtl/message_memory.sv",
    "rtl/ldpc_decoder_top.sv",
    "sim/tb_ldpc_decoder_top.sv",
]


@dataclass(frozen=True)
class Step:
    name: str
    command: list[str]
    timeout: int | None = None
    tools: tuple[str, ...] = ()
    optional_module: str | None = None


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    detail: str


def _missing_tools(step: Step) -> list[str]:
    return [tool for tool in step.tools if shutil.which(tool) is None]


def _module_skip_detail(step: Step) -> str | None:
    if not step.optional_module:
        return None
    probe = subprocess.run(
        [sys.executable, "-c", f"import {step.optional_module}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if probe.returncode == 0:
        return None
    stderr_lines = [line.strip() for line in probe.stderr.splitlines() if line.strip()]
    reason = stderr_lines[-1] if stderr_lines else f"could not import {step.optional_module}"
    return f"missing or unusable Python module: {step.optional_module}; {reason}"


def run_step(step: Step) -> Result:
    missing_tools = _missing_tools(step)
    if missing_tools:
        return Result(step.name, "SKIP", "missing tool(s): " + ", ".join(missing_tools))

    module_skip = _module_skip_detail(step)
    if module_skip:
        return Result(step.name, "SKIP", module_skip)

    print(f"+ {' '.join(step.command)}", flush=True)
    try:
        completed = subprocess.run(step.command, cwd=ROOT, timeout=step.timeout, check=False)
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT {step.name} after {step.timeout}s")
        return Result(step.name, "FAIL", "124")

    if completed.returncode == 0:
        return Result(step.name, "PASS", "0")
    return Result(step.name, "FAIL", str(completed.returncode))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-axis-sim",
        action="store_true",
        help="build the AXI wrapper but skip its simulation",
    )
    args = parser.parse_args()

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    py = sys.executable

    steps: list[Step] = [
        Step("phase1_phase3", [py, "scripts/run_phase1_phase3_tests.py"]),
        Step("parallel_schedule", [py, "scripts/gen_parallel_schedule.py"]),
        Step("decoder_vectors", [py, "scripts/gen_decoder_vectors.py"]),
        Step("decoder_check", [py, "scripts/check_decoder_output.py"]),
        Step(
            "decoder_build",
            [
                "iverilog",
                "-g2012",
                "-o",
                "sim/build/ldpc_decoder_top.vvp",
                *DECODER_RTL,
            ],
            tools=("iverilog",),
        ),
        Step("decoder_sim", ["vvp", "sim/build/ldpc_decoder_top.vvp"], timeout=60, tools=("vvp",)),
        Step(
            "decoder_lanes1_build",
            [
                "iverilog",
                "-g2012",
                "-P",
                "tb_ldpc_decoder_top.LANES=1",
                "-o",
                "sim/build/ldpc_decoder_top_lanes1.vvp",
                *DECODER_RTL,
            ],
            tools=("iverilog",),
        ),
        Step(
            "decoder_lanes1_sim",
            ["vvp", "sim/build/ldpc_decoder_top_lanes1.vvp"],
            timeout=180,
            tools=("vvp",),
        ),
        Step(
            "decoder_lanes16_build",
            [
                "iverilog",
                "-g2012",
                "-P",
                "tb_ldpc_decoder_top.LANES=16",
                "-o",
                "sim/build/ldpc_decoder_top_lanes16.vvp",
                *DECODER_RTL,
            ],
            tools=("iverilog",),
        ),
        Step(
            "decoder_lanes16_sim",
            ["vvp", "sim/build/ldpc_decoder_top_lanes16.vvp"],
            timeout=120,
            tools=("vvp",),
        ),
        Step(
            "axis_build",
            [
                "iverilog",
                "-g2012",
                "-o",
                "sim/build/ldpc_axis_wrapper.vvp",
                "rtl/ar4ja_1024_pkg.sv",
                "rtl/ldpc_schedule_pkg.sv",
                "rtl/posterior_memory.sv",
                "rtl/message_memory.sv",
                "rtl/ldpc_decoder_top.sv",
                "rtl/ldpc_axis_wrapper.sv",
                "sim/tb_ldpc_axis_wrapper.sv",
            ],
            tools=("iverilog",),
        ),
    ]

    if args.skip_axis_sim:
        axis_skip = Result("axis_sim", "SKIP", "disabled by --skip-axis-sim")
    else:
        axis_skip = None
        steps.append(
            Step(
                "axis_sim",
                ["vvp", "sim/build/ldpc_axis_wrapper.vvp"],
                timeout=60,
                tools=("vvp",),
            )
        )

    steps.extend(
        [
            Step("ber_fer_smoke", [py, "scripts/run_ber_fer.py", "--frames", "1", "--ebn0", "2.0"]),
            Step("summarize_results", [py, "scripts/summarize_results.py"]),
            Step(
                "plot_ber_fer",
                [py, "scripts/plot_ber_fer.py"],
                optional_module="matplotlib.pyplot",
            ),
            Step("parse_synthesis_reports", [py, "scripts/parse_synthesis_reports.py"]),
        ]
    )

    required_pass = {
        "decoder_sim": "decoder_build",
        "decoder_lanes1_sim": "decoder_lanes1_build",
        "decoder_lanes16_sim": "decoder_lanes16_build",
        "axis_sim": "axis_build",
    }

    results: list[Result] = []
    status_by_name: dict[str, str] = {}
    for step in steps:
        required = required_pass.get(step.name)
        if required is not None and status_by_name.get(required) != "PASS":
            detail = f"requires {required} to pass"
            result = Result(step.name, "SKIP", detail)
        else:
            result = run_step(step)
        results.append(result)
        status_by_name[result.name] = result.status
        if result.status == "FAIL":
            break
        if step.name == "axis_build" and axis_skip is not None:
            results.append(axis_skip)
            status_by_name[axis_skip.name] = axis_skip.status

    print("\nRegression summary:")
    for result in results:
        print(f"  {result.status:4s} {result.name} ({result.detail})")

    return 1 if any(result.status == "FAIL" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
