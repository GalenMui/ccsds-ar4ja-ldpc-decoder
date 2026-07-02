#!/usr/bin/env python3
"""Pack and parse board-independent AXI DMA test files for the LDPC decoder."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

MAGIC = 0x4C445043
TX_N = 2048
K_BITS = 1024
LLRS_PER_WORD = 4
INPUT_WORDS = TX_N // LLRS_PER_WORD
OUTPUT_WORDS = 8 + (K_BITS // 32)


def _read_numeric(path: Path, dtype: np.dtype) -> np.ndarray:
    if path.suffix == ".npy":
        return np.asarray(np.load(path), dtype=dtype).reshape(-1)
    if path.suffix == ".bin":
        return np.fromfile(path, dtype=dtype)
    return np.loadtxt(path, dtype=dtype).reshape(-1)


def read_llrs(path: Path) -> np.ndarray:
    llr = _read_numeric(path, np.int16)
    if llr.size != TX_N:
        raise ValueError(f"expected exactly {TX_N} LLRs, got {llr.size}")
    if np.any(llr < -128) or np.any(llr > 127):
        raise ValueError("LLRs must fit in signed int8 range [-128, 127]")
    return llr.astype(np.int8)


def pack_llrs_to_words(llr: np.ndarray) -> np.ndarray:
    llr = np.asarray(llr, dtype=np.int8).reshape(-1)
    if llr.size != TX_N:
        raise ValueError(f"expected exactly {TX_N} LLRs, got {llr.size}")

    lanes = llr.reshape(INPUT_WORDS, LLRS_PER_WORD).astype(np.uint8)
    words = (
        lanes[:, 0].astype(np.uint32)
        | (lanes[:, 1].astype(np.uint32) << 8)
        | (lanes[:, 2].astype(np.uint32) << 16)
        | (lanes[:, 3].astype(np.uint32) << 24)
    )
    return words.astype("<u4")


def write_dma_input(llr_path: Path, output_path: Path) -> None:
    words = pack_llrs_to_words(read_llrs(llr_path))
    words.tofile(output_path)


def parse_response(path: Path) -> dict[str, object]:
    words = np.fromfile(path, dtype="<u4")
    if words.size != OUTPUT_WORDS:
        raise ValueError(f"expected {OUTPUT_WORDS} response words, got {words.size}")
    if int(words[0]) != MAGIC:
        raise ValueError(f"bad magic 0x{int(words[0]):08x}; expected 0x{MAGIC:08x}")

    decoded = np.zeros(K_BITS, dtype=np.uint8)
    for word_index in range(K_BITS // 32):
        word = int(words[8 + word_index])
        for bit in range(32):
            decoded[word_index * 32 + bit] = (word >> bit) & 1

    return {
        "success": int(words[1]),
        "syndrome_pass": int(words[2]),
        "iterations": int(words[3]),
        "cycles": int(words[4]),
        "failure": int(words[5]),
        "saturation": int(words[6]),
        "decoded_bits": decoded,
    }


def read_bits(path: Path) -> np.ndarray:
    bits = _read_numeric(path, np.uint8)
    if bits.size != K_BITS:
        raise ValueError(f"expected {K_BITS} expected bits, got {bits.size}")
    if np.any((bits != 0) & (bits != 1)):
        raise ValueError("expected bits must be 0 or 1")
    return bits.astype(np.uint8)


def cmd_pack(args: argparse.Namespace) -> int:
    write_dma_input(args.llr_file, args.output)
    print(f"wrote {INPUT_WORDS} AXI input words to {args.output}")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    parsed = parse_response(args.response)
    print(f"success={parsed['success']}")
    print(f"syndrome_pass={parsed['syndrome_pass']}")
    print(f"iterations={parsed['iterations']}")
    print(f"cycles={parsed['cycles']}")
    print(f"failure={parsed['failure']}")
    print(f"saturation={parsed['saturation']}")
    if args.expected_bits is not None:
        expected = read_bits(args.expected_bits)
        match = np.array_equal(parsed["decoded_bits"], expected)
        print(f"expected_bits_match={int(match)}")
        return 0 if match else 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    pack = sub.add_parser("pack", help="pack 2048 signed int8 LLRs into 512 uint32 words")
    pack.add_argument("llr_file", type=Path)
    pack.add_argument("output", type=Path)
    pack.set_defaults(func=cmd_pack)

    parse = sub.add_parser("parse", help="parse a 40-word decoder response")
    parse.add_argument("response", type=Path)
    parse.add_argument("--expected-bits", type=Path)
    parse.set_defaults(func=cmd_parse)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
