#!/usr/bin/env python3
"""Generate deterministic vectors for the scheduled RTL LDPC decoder."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import ar4ja_matrix as ar4ja
from models import bpsk_awgn
from models import ldpc_encoder
from models.ldpc_decoder_fixed import decode_normalized_min_sum_fixed

DEFAULT_OUTPUT_DIR = Path("vectors/decoder")
MAX_ITERS = 8
LLR_W = 8


@dataclass(frozen=True)
class DecoderVector:
    name: str
    payload: np.ndarray
    llr: np.ndarray
    expect_payload: np.ndarray
    syndrome_pass: int
    decoder_success: int
    decoder_fail: int
    iterations_used: int
    saturation_count: int
    cycle_min: int
    cycle_max: int


def _pack_unsigned(values: np.ndarray, width: int) -> str:
    packed = 0
    mask = (1 << width) - 1
    for index, value in enumerate(values.reshape(-1)):
        packed |= (int(value) & mask) << (index * width)
    hex_width = (len(values.reshape(-1)) * width + 3) // 4
    return f"{packed:0{hex_width}x}"


def _pack_bits(bits: np.ndarray) -> str:
    packed = 0
    flat = bits.reshape(-1)
    for index, bit in enumerate(flat):
        if int(bit):
            packed |= 1 << index
    hex_width = (len(flat) + 3) // 4
    return f"{packed:0{hex_width}x}"


def _noiseless_vector(name: str, payload: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    tx = ldpc_encoder.encode(payload)
    llr = bpsk_awgn.noiseless_llr(tx, magnitude=32.0, llr_width=LLR_W)
    return tx, llr


def _make_vector(name: str, payload: np.ndarray, llr: np.ndarray) -> DecoderVector:
    result = decode_normalized_min_sum_fixed(llr, iterations=MAX_ITERS)
    # Bounds are intentionally loose so the same vectors can exercise LANES=1,
    # LANES=8, and LANES=16 while still checking deterministic convergence and
    # saturation metadata.
    cycle_min = 0
    # Upper bound uses the LANES=1 (fully serial) worst case, which bounds every
    # supported LANES value (more lanes => fewer cycles).  The decoder reads hard
    # decisions straight from the banked posterior sign bits, so the syndrome
    # check and the final output read are now serialised over the P-wide banked
    # read port instead of a single-cycle combinational scan (that removed the
    # flat 2560-bit hard-decision register and its wide mux cones).  At P=1:
    #   decode/iter    = M*13 + (CHECKS-M)*22 + CHECKS  (+CHECKS = one extra
    #                    S_GROUP_MIN_DRAIN cycle per group for the pipelined
    #                    min1/min2 reduction; at P=1 there are CHECKS groups)
    #   syndrome/sweep = M*7  + (CHECKS-M)*13 + 1     (P reads/edge, 2 cyc/edge)
    #   init           = PUNCTURED_N + CHECKS         (puncture-clear + msg-clear)
    #   output read    = 2 * INFO_N                   (2 cyc per hard bit)
    # with one syndrome sweep before decoding plus one per iteration.
    decode_iter = (ar4ja.M * 13) + ((ar4ja.CHECKS - ar4ja.M) * 22) + ar4ja.CHECKS
    syndrome_sweep = (ar4ja.M * 7) + ((ar4ja.CHECKS - ar4ja.M) * 13) + 1
    init_cycles = ar4ja.PUNCTURED_N + ar4ja.CHECKS
    output_cycles = 2 * ar4ja.INFO_N
    worst = (
        init_cycles
        + syndrome_sweep
        + MAX_ITERS * (decode_iter + syndrome_sweep)
        + output_cycles
    )
    # Small slack for FSM transition cycles; still a meaningful hang/runaway cap.
    cycle_max = worst + ar4ja.CHECKS + ar4ja.INFO_N
    return DecoderVector(
        name=name,
        payload=payload,
        llr=llr.astype(np.int16),
        expect_payload=result.hard_transmitted[: ar4ja.INFO_N].astype(np.uint8),
        syndrome_pass=int(result.converged),
        decoder_success=int(result.decoder_success),
        decoder_fail=int(result.decoder_fail),
        iterations_used=int(result.iterations),
        saturation_count=int(result.saturation_count),
        cycle_min=int(cycle_min),
        cycle_max=int(cycle_max),
    )


def build_vectors() -> list[DecoderVector]:
    vectors: list[DecoderVector] = []

    zero = np.zeros(ar4ja.INFO_N, dtype=np.uint8)
    _, llr = _noiseless_vector("zero_noiseless", zero)
    vectors.append(_make_vector("zero_noiseless", zero, llr))

    for bit in (0, 511, 512, 1023):
        payload = np.zeros(ar4ja.INFO_N, dtype=np.uint8)
        payload[bit] = 1
        _, llr = _noiseless_vector(f"walk_{bit}_noiseless", payload)
        vectors.append(_make_vector(f"walk_{bit}_noiseless", payload, llr))

    for seed in (1, 2):
        rng = np.random.default_rng(seed)
        payload = rng.integers(0, 2, ar4ja.INFO_N, dtype=np.uint8)
        _, llr = _noiseless_vector(f"random_seed_{seed}_noiseless", payload)
        vectors.append(_make_vector(f"random_seed_{seed}_noiseless", payload, llr))

    rng = np.random.default_rng(3)
    payload = rng.integers(0, 2, ar4ja.INFO_N, dtype=np.uint8)
    _, base_llr = _noiseless_vector("random_seed_3", payload)
    for name, bit in (
        ("info_region_error_bit_0", 0),
        ("parity_region_error_bit_1024", 1024),
        ("parity_region_error_bit_1500", 1500),
    ):
        llr = base_llr.copy()
        llr[bit] = -llr[bit]
        vectors.append(_make_vector(name, payload, llr))

    rng = np.random.default_rng(0)
    unknown_payload = np.zeros(ar4ja.INFO_N, dtype=np.uint8)
    failure_llr = rng.integers(-2, 3, ar4ja.TX_N, dtype=np.int16)
    vectors.append(_make_vector("low_confidence_failure_seed_0", unknown_payload, failure_llr))

    return vectors


def generate_vectors(output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    vectors = build_vectors()

    files = {
        "llr.mem": [_pack_unsigned(v.llr, LLR_W) for v in vectors],
        "payload_expected.mem": [_pack_bits(v.expect_payload) for v in vectors],
        "success.mem": [f"{v.decoder_success:x}" for v in vectors],
        "syndrome_pass.mem": [f"{v.syndrome_pass:x}" for v in vectors],
        "fail.mem": [f"{v.decoder_fail:x}" for v in vectors],
        "iterations.mem": [f"{v.iterations_used:x}" for v in vectors],
        "saturation.mem": [f"{v.saturation_count:08x}" for v in vectors],
        "cycle_min.mem": [f"{v.cycle_min:08x}" for v in vectors],
        "cycle_max.mem": [f"{v.cycle_max:08x}" for v in vectors],
    }

    for name, lines in files.items():
        (output_dir / name).write_text("\n".join(lines) + "\n", encoding="ascii")

    with (output_dir / "decoder_vectors.txt").open("w", encoding="ascii") as handle:
        handle.write("# name success syndrome_pass fail iterations saturation cycle_min cycle_max\n")
        for vector in vectors:
            handle.write(
                f"{vector.name} {vector.decoder_success} {vector.syndrome_pass} "
                f"{vector.decoder_fail} {vector.iterations_used} "
                f"{vector.saturation_count} {vector.cycle_min} {vector.cycle_max}\n"
            )

    with (output_dir / "decoder_meta.svh").open("w", encoding="ascii") as handle:
        handle.write("// Generated by scripts/gen_decoder_vectors.py. Do not edit by hand.\n")
        handle.write(f"localparam int DECODER_VECTOR_COUNT = {len(vectors)};\n")
        handle.write(f"localparam int DECODER_VECTOR_LLR_W = {LLR_W};\n")
        handle.write(f"localparam int DECODER_VECTOR_MAX_ITERS = {MAX_ITERS};\n")

    return output_dir / "decoder_vectors.txt"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    path = generate_vectors(args.output_dir)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
