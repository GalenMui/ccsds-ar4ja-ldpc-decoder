#!/usr/bin/env python3
"""PYNQ-Z2 smoke test for the generated LDPC decoder overlay."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from ccsds_ldpc_pynq import K_BITS, PynqLdpcDecoder


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
        from models.ldpc_decoder_fixed import decode_normalized_min_sum_fixed
    except ImportError as exc:
        raise RuntimeError(
            "could not import repository golden-model modules; copy the packaged "
            "overlay directory or run this script from the repository root"
        ) from exc
    return ar4ja, bpsk_awgn, ldpc_encoder, decode_normalized_min_sum_fixed


def _frame_from_payload(payload: np.ndarray) -> tuple[np.ndarray, np.ndarray, object]:
    _ar4ja, bpsk_awgn, ldpc_encoder, decode = _load_models()
    tx = ldpc_encoder.encode(payload)
    llr = bpsk_awgn.noiseless_llr(tx, magnitude=32.0, llr_width=8)
    golden = decode(llr, iterations=8, lanes=8)
    return tx, llr, golden


def _check_response(name: str, response: object, golden: object) -> list[str]:
    errors: list[str] = []
    expected_bits = golden.hard_transmitted[:K_BITS].astype(np.uint8)
    if response.success != int(golden.decoder_success):
        errors.append(f"{name}: success {response.success} != expected {int(golden.decoder_success)}")
    if response.syndrome_pass != int(golden.converged):
        errors.append(f"{name}: syndrome_pass {response.syndrome_pass} != expected {int(golden.converged)}")
    if response.failure != int(golden.decoder_fail):
        errors.append(f"{name}: failure {response.failure} != expected {int(golden.decoder_fail)}")
    if response.iterations != int(golden.iterations):
        errors.append(f"{name}: iterations {response.iterations} != expected {int(golden.iterations)}")
    if response.saturation != int(golden.saturation_count):
        errors.append(f"{name}: saturation {response.saturation} != expected {int(golden.saturation_count)}")
    if not np.array_equal(response.decoded_bits, expected_bits):
        mismatch = np.flatnonzero(response.decoded_bits != expected_bits)
        preview = ", ".join(str(int(idx)) for idx in mismatch[:16])
        errors.append(f"{name}: decoded bit mismatch count={mismatch.size} first=[{preview}]")
    return errors


def _run_frame(decoder: PynqLdpcDecoder, name: str, payload: np.ndarray, timeout_s: float) -> bool:
    _tx, llr, golden = _frame_from_payload(payload)
    response = decoder.decode_llrs(llr, timeout_s=timeout_s)
    errors = _check_response(name, response, golden)
    if errors:
        print(f"FAIL {name}")
        for error in errors:
            print(f"  {error}")
        print(
            "  hardware status: "
            f"success={response.success} syndrome={response.syndrome_pass} "
            f"failure={response.failure} iterations={response.iterations} "
            f"cycles={response.cycles} saturation={response.saturation}"
        )
        return False

    print(
        f"PASS {name}: success={response.success} iterations={response.iterations} "
        f"cycles={response.cycles} saturation={response.saturation}"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay-dir", type=Path, default=Path.cwd())
    parser.add_argument("--bitfile", type=Path)
    parser.add_argument("--hwhfile", type=Path)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--random-frames", type=int, default=0)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    bitfile = args.bitfile
    if bitfile is None:
        bitfile = args.overlay_dir / "ccsds_ldpc_pynq_z2.bit"
    hwhfile = args.hwhfile
    if hwhfile is None:
        hwhfile = args.overlay_dir / "ccsds_ldpc_pynq_z2.hwh"

    ar4ja, _bpsk_awgn, _ldpc_encoder, _decode = _load_models()
    decoder = PynqLdpcDecoder(bitfile, hwhfile=hwhfile)

    passed = True
    zero_payload = np.zeros(ar4ja.INFO_N, dtype=np.uint8)
    passed &= _run_frame(decoder, "zero_noiseless", zero_payload, args.timeout)

    rng = np.random.default_rng(args.seed)
    for index in range(args.random_frames):
        payload = rng.integers(0, 2, ar4ja.INFO_N, dtype=np.uint8)
        passed &= _run_frame(decoder, f"random_noiseless_{index}", payload, args.timeout)

    if passed:
        print("PYNQ-Z2 LDPC smoke test passed")
        return 0
    print("PYNQ-Z2 LDPC smoke test failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
