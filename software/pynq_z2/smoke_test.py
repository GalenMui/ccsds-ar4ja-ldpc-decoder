#!/usr/bin/env python3
"""PYNQ-Z2 smoke test for the generated LDPC decoder overlay."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np

from ccsds_ldpc_pynq import (
    INPUT_WORDS,
    K_BITS,
    OUTPUT_WORDS,
    PynqLdpcDecoder,
    pack_llrs_to_words,
)


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


def _array_sha256(values: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()


def _free_buffer(buffer: object) -> None:
    free = getattr(buffer, "freebuffer", None)
    if callable(free):
        free()


def _validate_buffer_allocation(llr: np.ndarray) -> None:
    from pynq import allocate

    words = pack_llrs_to_words(llr)
    in_buf = allocate(shape=(INPUT_WORDS,), dtype=np.uint32)
    out_buf = allocate(shape=(OUTPUT_WORDS,), dtype=np.uint32)
    try:
        in_buf[:] = words
        out_buf[:] = 0
        flush = getattr(in_buf, "flush", None)
        if callable(flush):
            flush()
        print(
            f"  input: address=0x{int(in_buf.physical_address):08x} "
            f"words={in_buf.size} bytes={in_buf.nbytes} dtype={in_buf.dtype}"
        )
        print(
            f"  output: address=0x{int(out_buf.physical_address):08x} "
            f"words={out_buf.size} bytes={out_buf.nbytes} dtype={out_buf.dtype}"
        )
        print(
            f"  packed input: first=0x{int(words[0]):08x} "
            f"last=0x{int(words[-1]):08x} sha256={_array_sha256(words)}"
        )
    finally:
        _free_buffer(in_buf)
        _free_buffer(out_buf)


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
    tx, llr, golden = _frame_from_payload(payload)
    expected_bits = golden.hard_transmitted[:K_BITS].astype(np.uint8)
    print(
        f"  input {name}: payload_bits={payload.size} payload_sha256={_array_sha256(payload)} "
        f"codeword_sha256={_array_sha256(tx)} llr_sha256={_array_sha256(llr)}"
    )
    print(
        "  expected: "
        f"success={int(golden.decoder_success)} syndrome={int(golden.converged)} "
        f"failure={int(golden.decoder_fail)} iterations={int(golden.iterations)} "
        f"saturation={int(golden.saturation_count)} "
        f"decoded_sha256={_array_sha256(expected_bits)}"
    )
    response = decoder.decode_llrs(
        llr, timeout_s=timeout_s, trace=lambda message: print(f"  {message}")
    )
    print(
        "  actual: "
        f"success={response.success} syndrome={response.syndrome_pass} "
        f"failure={response.failure} iterations={response.iterations} "
        f"cycles={response.cycles} saturation={response.saturation} "
        f"words={response.raw_words.size} "
        f"decoded_sha256={_array_sha256(response.decoded_bits)}"
    )
    print(f"Stage E: output validation ({name})")
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
    zero_payload = np.zeros(ar4ja.INFO_N, dtype=np.uint8)
    _, zero_llr, _ = _frame_from_payload(zero_payload)

    print("Stage A: overlay metadata and DMA discovery")
    print(f"  bitstream: {bitfile.expanduser().resolve()}")
    print(f"  hardware metadata: {hwhfile.expanduser().resolve()}")
    decoder = PynqLdpcDecoder(bitfile, hwhfile=hwhfile)
    print(f"  overlay loaded: {decoder.overlay.is_loaded()}")
    print(f"  available addressable IP: {sorted(decoder.overlay.ip_dict)}")
    print(f"  DMA: {decoder.dma_name}")
    print(
        "  channels: "
        f"send={hasattr(decoder.dma, 'sendchannel')} "
        f"receive={hasattr(decoder.dma, 'recvchannel')}"
    )

    print("Stage B: contiguous buffer allocation")
    _validate_buffer_allocation(zero_llr)

    print("Stage C: DMA engine initialization")
    print(f"  {decoder.format_dma_status()}")
    print(
        "  channel state: "
        f"MM2S running={decoder.dma.sendchannel.running} idle={decoder.dma.sendchannel.idle}; "
        f"S2MM running={decoder.dma.recvchannel.running} idle={decoder.dma.recvchannel.idle}"
    )

    print("Stage D: minimal valid DMA transfer")
    passed = True
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
