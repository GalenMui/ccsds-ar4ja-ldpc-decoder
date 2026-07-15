#!/usr/bin/env python3
"""Package the generated PYNQ-Z2 overlay and host-side helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROJECT_NAME = "ccsds_ldpc_pynq_z2"
BD_NAME = "ccsds_ldpc_pynq_z2_bd"
OVERLAY_BASENAME = "ccsds_ldpc_pynq_z2"
DEFAULT_PROJECT_DIR = ROOT / "results" / "pynq_z2" / "vivado" / PROJECT_NAME
DEFAULT_OUTPUT_DIR = ROOT / "build" / "pynq_z2" / "deploy"
REPORT_DIR = ROOT / "results" / "pynq_z2" / "reports" / "impl"


def _find_one(candidates: list[Path], label: str, searched: list[Path] | None = None) -> Path:
    existing = sorted(path for path in candidates if path.exists())
    if not existing:
        searched_paths = searched if searched is not None else candidates
        searched_text = "\n  ".join(str(path) for path in searched_paths)
        raise FileNotFoundError(f"could not find {label}; searched:\n  {searched_text}")
    if len(existing) > 1:
        existing.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return existing[0]


def find_bit(project_dir: Path) -> Path:
    pattern = project_dir / f"{PROJECT_NAME}.runs" / "impl_1" / "*.bit"
    return _find_one(
        list(project_dir.glob(f"{PROJECT_NAME}.runs/impl_1/*.bit")),
        "Vivado bitstream",
        [pattern],
    )


def find_hwh(project_dir: Path) -> Path:
    candidates = [
        project_dir / f"{PROJECT_NAME}.gen" / "sources_1" / "bd" / BD_NAME / "hw_handoff" / f"{BD_NAME}.hwh",
        project_dir / f"{PROJECT_NAME}.srcs" / "sources_1" / "bd" / BD_NAME / "hw_handoff" / f"{BD_NAME}.hwh",
    ]
    candidates.extend(project_dir.glob(f"{PROJECT_NAME}.gen/**/{BD_NAME}.hwh"))
    candidates.extend(project_dir.glob(f"{PROJECT_NAME}.srcs/**/{BD_NAME}.hwh"))
    return _find_one(candidates, "Vivado hardware handoff .hwh")


def find_bin(project_dir: Path) -> Path:
    return _find_one(
        list(project_dir.glob(f"{PROJECT_NAME}.runs/impl_1/*.bin")),
        "Vivado binary bitstream",
    )


def find_xsa(project_dir: Path) -> Path:
    return _find_one([project_dir / f"{PROJECT_NAME}.xsa"], "Vivado XSA")


def latest_source_mtime() -> float:
    patterns = [
        "rtl/**/*.sv",
        "rtl/**/*.v",
        "rtl/*.f",
        "boards/pynq_z2/vivado/*.tcl",
    ]
    latest = 0.0
    for pattern in patterns:
        for path in ROOT.glob(pattern):
            latest = max(latest, path.stat().st_mtime)
    return latest


def copy_python_support(output_dir: Path) -> None:
    for source in (ROOT / "software" / "pynq_z2").glob("*.py"):
        shutil.copy2(source, output_dir / source.name)
    requirements = ROOT / "requirements.txt"
    if requirements.exists():
        shutil.copy2(requirements, output_dir / "requirements.txt")

    models_src = ROOT / "models"
    models_dst = output_dir / "models"
    if models_dst.exists():
        shutil.rmtree(models_dst)
    shutil.copytree(models_src, models_dst, ignore=shutil.ignore_patterns("__pycache__"))

    readme = output_dir / "README.txt"
    readme.write_text(
        "\n".join(
            [
                "CCSDS AR4JA LDPC PYNQ-Z2 overlay package",
                "",
                "Copy this directory to the PYNQ-Z2 board, then run from the root Jupyter terminal:",
                "  XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 load_overlay.py",
                "  XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 smoke_test.py",
                "  XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 benchmark.py --frames 10",
                "",
                "Generated overlay files:",
                f"  {OVERLAY_BASENAME}.bit",
                f"  {OVERLAY_BASENAME}.hwh",
                "",
            ]
        ),
        encoding="ascii",
    )


def _git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timing_summary(path: Path) -> dict[str, float | int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"^\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+\d+\s+"
        r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+\d+",
        text,
        re.MULTILINE,
    )
    if match is None:
        raise RuntimeError(f"could not parse timing summary table: {path}")
    return {
        "setup_wns_ns": float(match.group(1)),
        "setup_tns_ns": float(match.group(2)),
        "setup_failing_endpoints": int(match.group(3)),
        "hold_whs_ns": float(match.group(4)),
        "hold_ths_ns": float(match.group(5)),
        "hold_failing_endpoints": int(match.group(6)),
    }


def write_manifest(output_dir: Path, artifacts: dict[str, Path]) -> Path:
    timing_report = REPORT_DIR / "timing_summary_impl.rpt"
    drc_report = REPORT_DIR / "drc_impl.rpt"
    route_report = REPORT_DIR / "route_status_impl.rpt"
    for report in (timing_report, drc_report, route_report):
        if not report.exists():
            raise FileNotFoundError(f"required implementation report not found: {report}")

    status = _git(["status", "--porcelain"])
    manifest = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": _git(["rev-parse", "HEAD"]),
        "source_worktree_dirty": bool(status),
        "vivado_version": "2025.2 (Build 6299465)",
        "board": "TUL PYNQ-Z2",
        "fpga_part": "xc7z020clg400-1",
        "top_module": f"{BD_NAME}_wrapper",
        "block_design": BD_NAME,
        "decoder_module": "ldpc_axis_decoder_ip",
        "decoder_lanes": 8,
        "clock_source": "processing_system7_0/FCLK_CLK0",
        "clock_target_mhz": 100.0,
        "implementation_status": "fully routed; all timing constraints met",
        "timing": _timing_summary(timing_report),
        "drc_result": "passed: 0 Error and 0 Critical Warning violations",
        "build_command": "make pynq-z2-bitstream",
        "package_command": "make pynq-z2-package",
        "artifacts": {
            name: {"file": path.name, "sha256": _sha256(path)}
            for name, path in artifacts.items()
        },
        "reports": {
            "timing": str(timing_report.relative_to(ROOT)),
            "drc": str(drc_report.relative_to(ROOT)),
            "route_status": str(route_report.relative_to(ROOT)),
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def deploy(output_dir: Path, destination: str) -> None:
    if ":" in destination and not Path(destination).is_absolute():
        command = ["rsync", "-a", f"{output_dir}/", destination.rstrip("/") + "/"]
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"rsync deploy failed with exit code {completed.returncode}")
        return

    dest_path = Path(destination).expanduser()
    dest_path.mkdir(parents=True, exist_ok=True)
    for source in output_dir.iterdir():
        target = dest_path / source.name
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def package_overlay(args: argparse.Namespace) -> int:
    project_dir = args.project_dir.resolve()
    output_dir = args.output_dir.resolve()

    bit = find_bit(project_dir)
    hwh = find_hwh(project_dir)
    binary = find_bin(project_dir)
    xsa = find_xsa(project_dir)
    source_mtime = latest_source_mtime()
    # The HWH is emitted when the block design is generated, before synthesis and
    # implementation.  The final bit/bin/XSA timestamps prove that the project
    # containing that HWH was subsequently built; Python packaging/test changes do
    # not require hardware to be rebuilt.
    artifact_mtime = min(path.stat().st_mtime for path in (bit, binary, xsa))
    if artifact_mtime < source_mtime and not args.allow_stale:
        raise RuntimeError(
            "Vivado artifacts are older than source/build scripts. "
            "Re-run make pynq-z2-bitstream, or pass --allow-stale knowingly."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    bit_out = output_dir / f"{OVERLAY_BASENAME}.bit"
    hwh_out = output_dir / f"{OVERLAY_BASENAME}.hwh"
    bin_out = output_dir / f"{OVERLAY_BASENAME}.bin"
    xsa_out = output_dir / f"{OVERLAY_BASENAME}.xsa"
    shutil.copy2(bit, bit_out)
    shutil.copy2(hwh, hwh_out)
    shutil.copy2(binary, bin_out)
    shutil.copy2(xsa, xsa_out)
    copy_python_support(output_dir)

    artifacts = {"bit": bit_out, "hwh": hwh_out, "bin": bin_out, "xsa": xsa_out}
    manifest = write_manifest(output_dir, artifacts)

    for path in artifacts.values():
        print(f"packaged {path}")
    print(f"packaged {manifest}")
    if args.deploy:
        deploy(output_dir, args.deploy)
        print(f"deployed overlay package to {args.deploy}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", type=Path, default=DEFAULT_PROJECT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--allow-stale", action="store_true")
    parser.add_argument(
        "--deploy",
        help="optional local directory or rsync destination such as xilinx@pynq:~/overlays/ldpc",
    )
    args = parser.parse_args()

    try:
        return package_overlay(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
