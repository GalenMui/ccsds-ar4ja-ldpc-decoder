#!/usr/bin/env python3
"""Package the generated PYNQ-Z2 overlay and host-side helpers."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROJECT_NAME = "ccsds_ldpc_pynq_z2"
BD_NAME = "ccsds_ldpc_pynq_z2_bd"
OVERLAY_BASENAME = "ccsds_ldpc_pynq_z2"
DEFAULT_PROJECT_DIR = ROOT / "results" / "pynq_z2" / "vivado" / PROJECT_NAME
DEFAULT_OUTPUT_DIR = ROOT / "results" / "pynq_z2" / "overlay"


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


def latest_source_mtime() -> float:
    patterns = [
        "rtl/*.sv",
        "rtl/*.f",
        "boards/pynq_z2/vivado/*.tcl",
        "software/pynq_z2/*.py",
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
                "Copy this directory to the PYNQ-Z2 board, then run:",
                "  python3 smoke_test.py",
                "  python3 benchmark.py --frames 10",
                "",
                "Generated overlay files:",
                f"  {OVERLAY_BASENAME}.bit",
                f"  {OVERLAY_BASENAME}.hwh",
                "",
            ]
        ),
        encoding="ascii",
    )


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
    source_mtime = latest_source_mtime()
    artifact_mtime = min(bit.stat().st_mtime, hwh.stat().st_mtime)
    if artifact_mtime < source_mtime and not args.allow_stale:
        raise RuntimeError(
            "Vivado artifacts are older than source/build scripts. "
            "Re-run make pynq-z2-bitstream, or pass --allow-stale knowingly."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    bit_out = output_dir / f"{OVERLAY_BASENAME}.bit"
    hwh_out = output_dir / f"{OVERLAY_BASENAME}.hwh"
    shutil.copy2(bit, bit_out)
    shutil.copy2(hwh, hwh_out)
    copy_python_support(output_dir)

    print(f"packaged {bit_out}")
    print(f"packaged {hwh_out}")
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
