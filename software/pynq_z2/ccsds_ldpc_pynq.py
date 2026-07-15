"""PYNQ driver and pure-Python packing helpers for the LDPC decoder overlay."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

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

DMA_STATUS_BITS = {
    0: "halted",
    1: "idle",
    3: "scatter_gather",
    4: "internal_error",
    5: "slave_error",
    6: "decode_error",
    8: "sg_internal_error",
    9: "sg_slave_error",
    10: "sg_decode_error",
    12: "ioc_irq",
    13: "delay_irq",
    14: "error_irq",
}


def format_dma_status(value: int | None) -> str:
    """Format an AXI DMA DMASR value with the relevant decoded flags."""

    if value is None:
        return "unavailable"
    flags = [name for bit, name in DMA_STATUS_BITS.items() if value & (1 << bit)]
    return f"0x{value:08x} ({', '.join(flags) if flags else 'no flags'})"


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
    def _read_channel_status(channel: Any) -> int | None:
        mmio = getattr(channel, "_mmio", None)
        offset = getattr(channel, "_offset", None)
        if mmio is None or offset is None:
            return None
        return int(mmio.read(int(offset) + 4))

    def dma_status(self) -> dict[str, int | None]:
        """Return raw MM2S and S2MM DMASR values."""

        return {
            "MM2S": self._read_channel_status(self.dma.sendchannel),
            "S2MM": self._read_channel_status(self.dma.recvchannel),
        }

    def format_dma_status(self) -> str:
        """Return both DMA channel status registers in a readable form."""

        return ", ".join(
            f"{name}={format_dma_status(value)}"
            for name, value in self.dma_status().items()
        )

    @staticmethod
    def _allocate(shape: tuple[int, ...], dtype: np.dtype) -> Any:
        from pynq import allocate

        return allocate(shape=shape, dtype=dtype)

    @staticmethod
    def _free_buffer(buffer: Any) -> None:
        free = getattr(buffer, "freebuffer", None)
        if callable(free):
            free()

    @classmethod
    def _wait_channel(cls, channel: Any, name: str, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        if hasattr(channel, "idle"):
            while not bool(channel.idle):
                status = cls._read_channel_status(channel)
                if status is not None and status & 0x70:
                    raise RuntimeError(
                        f"{name} DMA error: {format_dma_status(status)}"
                    )
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"{name} DMA channel did not become idle within "
                        f"{timeout_s:.3f}s; status={format_dma_status(status)}"
                    )
                time.sleep(0.001)
            return
        channel.wait()

    def decode_words(
        self,
        input_words: Sequence[int] | np.ndarray,
        *,
        timeout_s: float = 10.0,
        trace: Callable[[str], None] | None = None,
    ) -> DecoderResponse:
        words = _as_uint32_words(input_words, INPUT_WORDS)
        in_buf = self._allocate((INPUT_WORDS,), np.uint32)
        out_buf = self._allocate((OUTPUT_WORDS,), np.uint32)
        try:
            in_buf[:] = words
            out_buf[:] = 0
            if trace is not None:
                trace(
                    f"input buffer: address=0x{int(in_buf.physical_address):08x} "
                    f"bytes={in_buf.nbytes} dtype={in_buf.dtype}"
                )
                trace(
                    f"output buffer: address=0x{int(out_buf.physical_address):08x} "
                    f"bytes={out_buf.nbytes} dtype={out_buf.dtype}"
                )
                trace(f"DMA before transfer: {self.format_dma_status()}")
            flush = getattr(in_buf, "flush", None)
            if callable(flush):
                flush()
            self.dma.recvchannel.transfer(out_buf)
            if trace is not None:
                trace("S2MM receive submitted before MM2S send")
            self.dma.sendchannel.transfer(in_buf)
            self._wait_channel(self.dma.sendchannel, "MM2S", timeout_s)
            self._wait_channel(self.dma.recvchannel, "S2MM", timeout_s)
            if trace is not None:
                trace(f"DMA after transfer: {self.format_dma_status()}")
            invalidate = getattr(out_buf, "invalidate", None)
            if callable(invalidate):
                invalidate()
            return unpack_response_words(np.asarray(out_buf, dtype=np.uint32))
        except Exception:
            if trace is not None:
                trace(f"DMA at failure: {self.format_dma_status()}")
            raise
        finally:
            self._free_buffer(in_buf)
            self._free_buffer(out_buf)

    def decode_llrs(
        self,
        llrs: Sequence[int] | np.ndarray,
        *,
        timeout_s: float = 10.0,
        trace: Callable[[str], None] | None = None,
    ) -> DecoderResponse:
        return self.decode_words(
            pack_llrs_to_words(llrs), timeout_s=timeout_s, trace=trace
        )

    # -- reusable-buffer fast path ----------------------------------------
    # decode_words() above allocates a fresh contiguous buffer pair per call and
    # stays the proven smoke-test path.  For steady-state benchmarking, allocate
    # the buffers once with allocate_io_buffers() and drive frames through
    # run_prepacked(), which reuses them and returns a per-stage timing
    # breakdown using time.perf_counter_ns().

    def allocate_io_buffers(self) -> tuple[Any, Any]:
        """Allocate one reusable (input, output) contiguous buffer pair."""

        in_buf = self._allocate((INPUT_WORDS,), np.uint32)
        out_buf = self._allocate((OUTPUT_WORDS,), np.uint32)
        return in_buf, out_buf

    def free_io_buffers(self, in_buf: Any, out_buf: Any) -> None:
        self._free_buffer(in_buf)
        self._free_buffer(out_buf)

    def run_prepacked(
        self,
        input_words: Sequence[int] | np.ndarray,
        in_buf: Any,
        out_buf: Any,
        *,
        timeout_s: float = 10.0,
        capture_status: bool = False,
    ) -> tuple[DecoderResponse, dict[str, int | dict]]:
        """Run one frame through preallocated buffers and time each stage.

        Returns the parsed response and a timing dict with nanosecond stage
        durations (``copy_ns``, ``submit_ns``, ``wait_ns``, ``parse_ns``,
        ``total_ns``).  ``capture_status`` additionally records the DMA status
        registers after completion.
        """

        words = _as_uint32_words(input_words, INPUT_WORDS)
        timing: dict[str, int | dict] = {}
        t0 = time.perf_counter_ns()
        in_buf[:] = words
        out_buf[:] = 0
        flush = getattr(in_buf, "flush", None)
        if callable(flush):
            flush()
        t1 = time.perf_counter_ns()
        self.dma.recvchannel.transfer(out_buf)
        self.dma.sendchannel.transfer(in_buf)
        t2 = time.perf_counter_ns()
        self._wait_channel(self.dma.sendchannel, "MM2S", timeout_s)
        self._wait_channel(self.dma.recvchannel, "S2MM", timeout_s)
        t3 = time.perf_counter_ns()
        invalidate = getattr(out_buf, "invalidate", None)
        if callable(invalidate):
            invalidate()
        response = unpack_response_words(np.asarray(out_buf, dtype=np.uint32))
        t4 = time.perf_counter_ns()
        timing["copy_ns"] = t1 - t0
        timing["submit_ns"] = t2 - t1
        timing["wait_ns"] = t3 - t2
        timing["parse_ns"] = t4 - t3
        timing["total_ns"] = t4 - t0
        if capture_status:
            timing["dma_status"] = self.dma_status()
        return response, timing
