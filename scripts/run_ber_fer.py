#!/usr/bin/env python3
"""Run a small deterministic BER/FER sweep using the fixed-point model."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import ar4ja_matrix as ar4ja
from models import bpsk_awgn
from models import ldpc_encoder
from models import llr_quant
from models.ldpc_decoder_fixed import decode_normalized_min_sum_fixed

DEFAULT_OUTPUT = Path("results/reports/ber_fer.csv")


def run_sweep(
    ebn0_db: list[float],
    frames: int,
    seed: int,
    output: Path,
    max_iters: int = 8,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    rows: list[dict[str, float | int]] = []

    for point_index, point in enumerate(ebn0_db):
        pre_errors = 0
        pre_bits = 0
        post_errors = 0
        post_bits = 0
        frame_errors = 0
        decoder_failures = 0
        iterations = 0

        # For BPSK with unit-energy symbols, approximate Es/N0 = Eb/N0 + 10log10(R)
        # for the transmitted rate-1/2 code.
        esn0_db = point + 10.0 * np.log10(0.5)
        for frame_idx in range(frames):
            payload = rng.integers(0, 2, ar4ja.INFO_N, dtype=np.uint8)
            tx = ldpc_encoder.encode(payload)
            channel = bpsk_awgn.transmit_bpsk_awgn(
                tx,
                snr_db=esn0_db,
                seed=seed + point_index * 1000 + frame_idx,
                llr_scale=0.25,
            )
            hard_tx = llr_quant.hard_decision_from_llr(channel.quantized_llr)
            pre_errors += int(np.count_nonzero(hard_tx != tx))
            pre_bits += ar4ja.TX_N

            result = decode_normalized_min_sum_fixed(
                channel.quantized_llr,
                iterations=max_iters,
            )
            decoded_payload = result.hard_transmitted[: ar4ja.INFO_N]
            payload_errors = int(np.count_nonzero(decoded_payload != payload))
            post_errors += payload_errors
            post_bits += ar4ja.INFO_N
            frame_errors += int(payload_errors != 0 or result.decoder_fail)
            decoder_failures += int(result.decoder_fail)
            iterations += int(result.iterations)

        rows.append(
            {
                "ebn0_db": point,
                "frames": frames,
                "pre_ber": pre_errors / pre_bits,
                "post_ber": post_errors / post_bits,
                "fer": frame_errors / frames,
                "avg_iterations": iterations / frames,
                "decoder_failure_rate": decoder_failures / frames,
            }
        )

    with output.open("w", newline="", encoding="ascii") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ebn0", nargs="+", type=float, default=[1.0, 2.0, 3.0])
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument("--long", action="store_true", help="use a larger deterministic run")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    frames = max(args.frames, 20) if args.long else args.frames
    path = run_sweep(args.ebn0, frames, args.seed, args.output)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

