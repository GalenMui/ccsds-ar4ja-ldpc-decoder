"""PYNQ driver and pure-Python packing helpers for the LDPC decoder overlay."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

MAGIC = 0x4C445043
TX_N = 2048
K_BITS = 1024
LLRS_PER_WORD = 4
INPUT_WORDS = TX_N // LLRS_PER_WORD
OUTPUT_WORDS = 8 + (K_BITS // 32)
INPUT_BYTES = INPUT_WORDS * 4
OUTPUT_BYTES = OUTPUT_WORDS * 4
OVERLAY_BASENAME = "ccsds_ldpc_pynq_z2"
DEFAULT_DMA_NAME = "axi_dma_0"


@dataclass(frozen=True)
class DecoderResponse:
    """Parsed 40-word decoder response frame."""

    success: int
    syndrome_pass: int
    iterations: int
    cycles: int
    failure: int
    saturation: int
    decoded_bits: np.ndarray
    raw_words: np.ndarray


def _as_uint32_words(words: Sequence[int] | np.ndarray, expected_words: int) -> np.ndarray:
    arr = np.asarray(words, dtype=np.uint32).reshape(-1)
    if arr.size != expected_words:
        raise ValueError(f"expected {expected_words} uint32 words, got {arr.size}")
    return arr.astype("<u4", copy=True)


def pack_llrs_to_words(llrs: Sequence[int] | np.ndarray) -> np.ndarray:
    """Pack 2048 signed int8 LLRs into 512 little-lane uint32 AXI words."""

    arr = np.asarray(llrs, dtype=np.int16).reshape(-1)
    if arr.size != TX_N:
        raise ValueError(f"expected exactly {TX_N} LLRs, got {arr.size}")
    if np.any(arr < -128) or np.any(arr > 127):
        raise ValueError("LLRs must fit in signed int8 range [-128, 127]")

    lanes = arr.astype(np.int8).reshape(INPUT_WORDS, LLRS_PER_WORD).astype(np.uint8)
    words = (
        lanes[:, 0].astype(np.uint32)
        | (lanes[:, 1].astype(np.uint32) << 8)
        | (lanes[:, 2].astype(np.uint32) << 16)
        | (lanes[:, 3].astype(np.uint32) << 24)
    )
    return words.astype("<u4", copy=False)


def pack_decoded_bits_to_words(bits: Sequence[int] | np.ndarray) -> np.ndarray:
    """Pack 1024 decoded bits into the 32 payload words used in the response."""

    arr = np.asarray(bits, dtype=np.uint8).reshape(-1)
    if arr.size != K_BITS:
        raise ValueError(f"expected exactly {K_BITS} decoded bits, got {arr.size}")
    if np.any((arr != 0) & (arr != 1)):
        raise ValueError("decoded bits must be 0 or 1")

    words = np.zeros(K_BITS // 32, dtype="<u4")
    for word_index in range(K_BITS // 32):
        word = 0
        for bit_index in range(32):
            if int(arr[word_index * 32 + bit_index]):
                word |= 1 << bit_index
        words[word_index] = word
    return words


def unpack_response_words(words: Sequence[int] | np.ndarray) -> DecoderResponse:
    """Parse and validate the 40-word AXI DMA receive buffer."""

    arr = _as_uint32_words(words, OUTPUT_WORDS)
    if int(arr[0]) != MAGIC:
        raise ValueError(f"bad response magic 0x{int(arr[0]):08x}; expected 0x{MAGIC:08x}")

    decoded = np.zeros(K_BITS, dtype=np.uint8)
    for word_index in range(K_BITS // 32):
        word = int(arr[8 + word_index])
        for bit_index in range(32):
            decoded[word_index * 32 + bit_index] = (word >> bit_index) & 1

    return DecoderResponse(
        success=int(arr[1]),
        syndrome_pass=int(arr[2]),
        iterations=int(arr[3]),
        cycles=int(arr[4]),
        failure=int(arr[5]),
        saturation=int(arr[6]),
        decoded_bits=decoded,
        raw_words=arr,
    )


def locate_overlay(directory: Path | str = ".") -> tuple[Path, Path]:
    """Return matching .bit and .hwh paths from a directory."""

    root = Path(directory).expanduser().resolve()
    bit = root / f"{OVERLAY_BASENAME}.bit"
    hwh = root / f"{OVERLAY_BASENAME}.hwh"
    if not bit.exists():
        raise FileNotFoundError(f"overlay bitstream not found: {bit}")
    if not hwh.exists():
        raise FileNotFoundError(f"overlay hardware handoff not found: {hwh}")
    return bit, hwh


class PynqLdpcDecoder:
    """Small PYNQ wrapper around the AXI DMA connected to the LDPC decoder."""

    def __init__(
        self,
        bitfile: str | Path | None = None,
        *,
        hwhfile: str | Path | None = None,
        dma_name: str = DEFAULT_DMA_NAME,
        overlay: Any | None = None,
        download: bool = True,
    ) -> None:
        if overlay is None:
            from pynq import Overlay

            if bitfile is None:
                bitfile, inferred_hwh = locate_overlay(Path.cwd())
                hwhfile = hwhfile or inferred_hwh
            bit_path = Path(bitfile).expanduser().resolve()
            if not bit_path.exists():
                raise FileNotFoundError(f"overlay bitstream not found: {bit_path}")
            if hwhfile is not None and not Path(hwhfile).expanduser().resolve().exists():
                raise FileNotFoundError(f"overlay hardware handoff not found: {hwhfile}")
            self.overlay = Overlay(str(bit_path), download=download)
        else:
            self.overlay = overlay

        self.dma_name = dma_name
        self.dma = self._get_dma(dma_name)
        self._validate_dma()

    def _get_dma(self, dma_name: str) -> Any:
        if hasattr(self.overlay, dma_name):
            return getattr(self.overlay, dma_name)
        ip_dict = getattr(self.overlay, "ip_dict", {})
        if dma_name not in ip_dict:
            names = ", ".join(sorted(ip_dict)) or "<none>"
            raise RuntimeError(f"expected DMA IP '{dma_name}' not found; overlay IPs: {names}")
        raise RuntimeError(f"DMA IP '{dma_name}' is present in metadata but not exposed as an attribute")

    def _validate_dma(self) -> None:
        for attr in ("sendchannel", "recvchannel"):
            if not hasattr(self.dma, attr):
                raise RuntimeError(f"DMA '{self.dma_name}' is missing {attr}")

    @staticmethod
    def _allocate(shape: tuple[int, ...], dtype: np.dtype) -> Any:
        from pynq import allocate

        return allocate(shape=shape, dtype=dtype)

    @staticmethod
    def _free_buffer(buffer: Any) -> None:
        free = getattr(buffer, "freebuffer", None)
        if callable(free):
            free()

    @staticmethod
    def _wait_channel(channel: Any, name: str, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        if hasattr(channel, "idle"):
            while not bool(channel.idle):
                if time.monotonic() > deadline:
                    raise TimeoutError(f"{name} DMA channel did not become idle within {timeout_s:.3f}s")
                time.sleep(0.001)
            return
        channel.wait()

    def decode_words(self, input_words: Sequence[int] | np.ndarray, *, timeout_s: float = 10.0) -> DecoderResponse:
        words = _as_uint32_words(input_words, INPUT_WORDS)
        in_buf = self._allocate((INPUT_WORDS,), np.uint32)
        out_buf = self._allocate((OUTPUT_WORDS,), np.uint32)
        try:
            in_buf[:] = words
            out_buf[:] = 0
            flush = getattr(in_buf, "flush", None)
            if callable(flush):
                flush()
            self.dma.recvchannel.transfer(out_buf)
            self.dma.sendchannel.transfer(in_buf)
            self._wait_channel(self.dma.sendchannel, "MM2S", timeout_s)
            self._wait_channel(self.dma.recvchannel, "S2MM", timeout_s)
            invalidate = getattr(out_buf, "invalidate", None)
            if callable(invalidate):
                invalidate()
            return unpack_response_words(np.asarray(out_buf, dtype=np.uint32))
        finally:
            self._free_buffer(in_buf)
            self._free_buffer(out_buf)

    def decode_llrs(self, llrs: Sequence[int] | np.ndarray, *, timeout_s: float = 10.0) -> DecoderResponse:
        return self.decode_words(pack_llrs_to_words(llrs), timeout_s=timeout_s)
