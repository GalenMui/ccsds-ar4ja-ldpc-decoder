"""Reusable frame runners for the LDPC benchmark.

Two runners share one :class:`FrameResult` shape so the benchmark CLI is
agnostic to the backend:

* :class:`BoardRunner` drives the physical PYNQ-Z2 overlay through
  ``PynqLdpcDecoder`` with allocate-once / reuse buffers and per-stage host
  timing.  Its ``source`` is ``"hardware"`` and it reports the decoder's own
  cycle counter.
* :class:`SoftwareRunner` runs the checked-in bit-accurate fixed-point model
  (``decode_normalized_min_sum_fixed``).  Its ``source`` is
  ``"software-model"``; it never reports a hardware cycle count (only a modeled
  core-cycle estimate) so its output can never be mistaken for a board
  measurement.  It exists for offline validation of the whole harness and as
  the primary hardware-equivalence reference.

Both consume a :class:`channel.Frame` and grade the decoded payload against the
transmitted payload carried by that frame.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

try:  # flat layout on the board deploy directory
    import channel
    from ccsds_ldpc_pynq import K_BITS, PynqLdpcDecoder, pack_llrs_to_words
except ImportError:  # package layout in the repository / tests
    from software.pynq_z2 import channel
    from software.pynq_z2.ccsds_ldpc_pynq import K_BITS, PynqLdpcDecoder, pack_llrs_to_words

from models.ldpc_decoder_fixed import decode_normalized_min_sum_fixed

# LANES=8 functional core-cycle model (RTL-simulation counts, excludes AXI
# stream transfer).  Used only as a modeled estimate; never compared to the
# hardware cycle counter, which includes DMA/stream overhead.
_MODEL_INITIAL_CYCLES = 480
_MODEL_CYCLES_PER_ITER = 3840


def modeled_core_cycles(iterations: int) -> int:
    """Functional core-cycle estimate for LANES=8 (excludes AXI transfer)."""

    return _MODEL_INITIAL_CYCLES + int(iterations) * _MODEL_CYCLES_PER_ITER


@dataclass
class FrameResult:
    """Graded outcome of one decoded frame from either backend."""

    index: int
    source: str                    # "hardware" | "software-model"
    ok: bool                       # a valid decoder response was obtained
    success: int = 0
    syndrome_pass: int = 0
    failure: int = 0
    iterations: int = 0
    saturation: int = 0
    cycles: int | None = None      # hardware decoder cycle counter only
    modeled_core_cycles: int | None = None
    bit_errors: int = 0
    frame_error: bool = False
    undetected_error: bool = False
    input_saturation_events: int = 0
    decoded_sha256: str | None = None
    timing_ns: dict[str, int] = field(default_factory=dict)
    dma_status: dict[str, int | None] | None = None
    error: str | None = None       # host/DMA exception or timeout message

    def to_record(self, frame: "channel.Frame") -> dict:
        """Compact JSON-serialisable per-frame record (no large arrays)."""

        return {
            "index": self.index,
            "source": self.source,
            "ok": self.ok,
            "seed": frame.seed,
            "ebn0_db": frame.ebn0_db,
            "pattern": frame.pattern,
            "payload_sha256": frame.payload_sha256,
            "llr_sha256": frame.llr_sha256,
            "success": self.success,
            "syndrome_pass": self.syndrome_pass,
            "failure": self.failure,
            "iterations": self.iterations,
            "saturation": self.saturation,
            "cycles": self.cycles,
            "modeled_core_cycles": self.modeled_core_cycles,
            "bit_errors": self.bit_errors,
            "frame_error": self.frame_error,
            "undetected_error": self.undetected_error,
            "input_saturation_events": self.input_saturation_events,
            "decoded_sha256": self.decoded_sha256,
            "timing_ns": self.timing_ns,
            "dma_status": self.dma_status,
            "error": self.error,
        }


def _grade(
    index: int,
    source: str,
    frame: "channel.Frame",
    decoded_bits: np.ndarray,
    *,
    success: int,
    syndrome_pass: int,
    failure: int,
    iterations: int,
    saturation: int,
) -> FrameResult:
    decoded_info = np.asarray(decoded_bits, dtype=np.uint8)[:channel.INFO_N]
    bit_errors = int(np.count_nonzero(decoded_info != frame.payload))
    frame_error = bool(bit_errors != 0 or failure)
    undetected = bool(success and bit_errors != 0)
    return FrameResult(
        index=index,
        source=source,
        ok=True,
        success=int(success),
        syndrome_pass=int(syndrome_pass),
        failure=int(failure),
        iterations=int(iterations),
        saturation=int(saturation),
        bit_errors=bit_errors,
        frame_error=frame_error,
        undetected_error=undetected,
        input_saturation_events=int(frame.saturated_inputs),
        decoded_sha256=channel.array_sha256(decoded_info),
    )


class SoftwareRunner:
    """Bit-accurate fixed-point reference backend (no hardware)."""

    source = "software-model"

    def __init__(self, *, iterations: int = 8, lanes: int = 8) -> None:
        self.iterations = iterations
        self.lanes = lanes

    def __enter__(self) -> "SoftwareRunner":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def decode_frame(self, frame: "channel.Frame") -> FrameResult:
        t0 = time.perf_counter_ns()
        result = decode_normalized_min_sum_fixed(
            frame.quantized_llr, iterations=self.iterations, lanes=self.lanes
        )
        t1 = time.perf_counter_ns()
        graded = _grade(
            frame.index, self.source, frame, result.hard_transmitted,
            success=int(result.decoder_success),
            syndrome_pass=int(result.converged),
            failure=int(result.decoder_fail),
            iterations=int(result.iterations),
            saturation=int(result.saturation_count),
        )
        graded.modeled_core_cycles = modeled_core_cycles(result.iterations)
        graded.timing_ns = {"decode_ns": t1 - t0, "total_ns": t1 - t0}
        return graded


class BoardRunner:
    """Physical PYNQ-Z2 backend with reusable buffers and per-stage timing."""

    source = "hardware"

    def __init__(
        self,
        decoder: PynqLdpcDecoder,
        *,
        timeout_s: float = 10.0,
        capture_status: bool = False,
    ) -> None:
        self.decoder = decoder
        self.timeout_s = timeout_s
        self.capture_status = capture_status
        self._in_buf: Any | None = None
        self._out_buf: Any | None = None

    @classmethod
    def open(
        cls,
        bitfile: str,
        *,
        hwhfile: str | None = None,
        timeout_s: float = 10.0,
        capture_status: bool = False,
    ) -> "BoardRunner":
        decoder = PynqLdpcDecoder(bitfile, hwhfile=hwhfile)
        return cls(decoder, timeout_s=timeout_s, capture_status=capture_status)

    def __enter__(self) -> "BoardRunner":
        self._in_buf, self._out_buf = self.decoder.allocate_io_buffers()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._in_buf is not None:
            self.decoder.free_io_buffers(self._in_buf, self._out_buf)
            self._in_buf = self._out_buf = None

    def decode_frame(self, frame: "channel.Frame") -> FrameResult:
        if self._in_buf is None:
            raise RuntimeError("BoardRunner must be used as a context manager")
        t0 = time.perf_counter_ns()
        words = pack_llrs_to_words(frame.quantized_llr)
        t1 = time.perf_counter_ns()
        try:
            response, timing = self.decoder.run_prepacked(
                words, self._in_buf, self._out_buf,
                timeout_s=self.timeout_s, capture_status=self.capture_status,
            )
        except TimeoutError as exc:
            return self._failure(frame, exc, timeout=True)
        except Exception as exc:  # noqa: BLE001 - surface DMA/host errors as data
            return self._failure(frame, exc, timeout=False)
        graded = _grade(
            frame.index, self.source, frame, response.decoded_bits,
            success=response.success, syndrome_pass=response.syndrome_pass,
            failure=response.failure, iterations=response.iterations,
            saturation=response.saturation,
        )
        graded.cycles = int(response.cycles)
        graded.modeled_core_cycles = modeled_core_cycles(response.iterations)
        graded.timing_ns = {"pack_ns": t1 - t0, **{k: v for k, v in timing.items() if k != "dma_status"}}
        graded.dma_status = timing.get("dma_status")  # type: ignore[assignment]
        return graded

    def _failure(self, frame: "channel.Frame", exc: BaseException, *, timeout: bool) -> FrameResult:
        status = None
        try:
            status = self.decoder.dma_status()
        except Exception:  # noqa: BLE001
            status = None
        return FrameResult(
            index=frame.index,
            source=self.source,
            ok=False,
            input_saturation_events=int(frame.saturated_inputs),
            dma_status=status,
            error=f"{type(exc).__name__}: {exc}",
            timing_ns={},
        )
