#!/usr/bin/env python3
"""Measure PYNQ DMA plus LDPC decode wall-clock time on hardware."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from ccsds_ldpc_pynq import INPUT_BYTES, OUTPUT_BYTES, PynqLdpcDecoder


def _add_repo_or_package_root() -> None:
    here = Path(__file__).resolve().parent
    for candidate in (here, here.parent, here.parent.parent, Path.cwd()):
        if (candidate / "models").is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


def _load_models():
    _add_repo_or_package_root()
    try:
        from models import ar4ja_matrix as ar4ja
        from models import bpsk_awgn, ldpc_encoder
    except ImportError as exc:
        raise RuntimeError("could not import repository model modules") from exc
    return ar4ja, bpsk_awgn, ldpc_encoder


def _make_llrs(frames: int, seed: int) -> list[np.ndarray]:
    ar4ja, bpsk_awgn, ldpc_encoder = _load_models()
    rng = np.random.default_rng(seed)
    llrs: list[np.ndarray] = []
    for _index in range(frames):
        payload = rng.integers(0, 2, ar4ja.INFO_N, dtype=np.uint8)
        tx = ldpc_encoder.encode(payload)
        llrs.append(bpsk_awgn.noiseless_llr(tx, magnitude=32.0, llr_width=8))
    return llrs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay-dir", type=Path, default=Path.cwd())
    parser.add_argument("--bitfile", type=Path)
    parser.add_argument("--hwhfile", type=Path)
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=2)
    args = parser.parse_args()

    if args.frames <= 0:
        raise ValueError("--frames must be positive")

    bitfile = args.bitfile or (args.overlay_dir / "ccsds_ldpc_pynq_z2.bit")
    hwhfile = args.hwhfile or (args.overlay_dir / "ccsds_ldpc_pynq_z2.hwh")
    decoder = PynqLdpcDecoder(bitfile, hwhfile=hwhfile)
    frames = _make_llrs(args.frames, args.seed)

    elapsed: list[float] = []
    cycles: list[int] = []
    failures = 0
    for index, llr in enumerate(frames):
        start = time.perf_counter()
        response = decoder.decode_llrs(llr, timeout_s=args.timeout)
        end = time.perf_counter()
        elapsed.append(end - start)
        cycles.append(response.cycles)
        failures += int(response.failure != 0)
        print(
            f"frame={index} wall_s={elapsed[-1]:.6f} cycles={response.cycles} "
            f"success={response.success} iterations={response.iterations}"
        )

    total = float(np.sum(elapsed))
    mean = float(np.mean(elapsed))
    p95 = float(np.percentile(elapsed, 95))
    fps = args.frames / total if total > 0 else 0.0
    input_mib_s = (INPUT_BYTES * args.frames) / total / (1024 * 1024) if total > 0 else 0.0
    output_mib_s = (OUTPUT_BYTES * args.frames) / total / (1024 * 1024) if total > 0 else 0.0

    print("")
    print("Measured on hardware: Python + AXI DMA + decoder wall-clock time")
    print(f"frames={args.frames}")
    print(f"total_s={total:.6f}")
    print(f"mean_s={mean:.6f}")
    print(f"p95_s={p95:.6f}")
    print(f"frames_per_second={fps:.3f}")
    print(f"input_mib_per_second={input_mib_s:.3f}")
    print(f"output_mib_per_second={output_mib_s:.3f}")
    print(f"decoder_cycles_mean={float(np.mean(cycles)):.1f}")
    print(f"decoder_failures={failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
