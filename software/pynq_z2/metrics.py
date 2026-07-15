"""Communications and performance metric aggregation for the LDPC benchmark.

Metric definitions (fixed and explicit):

* BER  = total incorrect decoded information bits / total transmitted
         information bits.
* FER  = frames with any incorrect decoded information bit OR a decoder-declared
         failure / total attempted communications frames.
* Undetected error = decoder asserted success but the decoded payload is wrong.
* Decoder-declared failure = decoder asserted failure (syndrome not satisfied
         after the maximum iteration schedule).
* Infrastructure failure (DMA error / timeout / exception) is counted and
  reported *separately* and never folded into the communications FER.

Confidence intervals for error-rate proportions use the Wilson score interval,
which stays inside [0, 1] and gives a usable upper bound even when zero errors
are observed.  No SciPy dependency; the normal quantile is a fixed constant for
the common 95 % level and otherwise from a rational approximation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

INFO_BITS_PER_FRAME = 1024
CODED_BITS_PER_FRAME = 2048
CLOCK_HZ = 100_000_000  # verified PYNQ-Z2 decoder clock

# z for a two-sided 95 % interval; used directly to avoid a SciPy dependency.
Z_95 = 1.959963984540054


def normal_ppf(p: float) -> float:
    """Inverse standard-normal CDF via the Acklam rational approximation."""

    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
    b = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00)
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


def wilson_interval(successes: int, trials: int, confidence: float = 0.95) -> tuple[float, float]:
    """Two-sided Wilson score interval for a binomial proportion.

    ``successes`` here means "observed events" (e.g. frame errors).  Returns
    ``(low, high)`` bounds on the true proportion.  For zero events the lower
    bound is 0.0 and the upper bound is a meaningful non-zero value, so a
    zero-error point is never reported as a proven zero rate.
    """

    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError("require 0 <= successes <= trials")
    if trials == 0:
        return (0.0, 1.0)
    z = Z_95 if abs(confidence - 0.95) < 1e-9 else normal_ppf(0.5 + confidence / 2.0)
    phat = successes / trials
    z2 = z * z
    denom = 1.0 + z2 / trials
    center = (phat + z2 / (2.0 * trials)) / denom
    half = (z / denom) * math.sqrt(phat * (1.0 - phat) / trials + z2 / (4.0 * trials * trials))
    low = 0.0 if successes == 0 else max(0.0, center - half)
    high = 1.0 if successes == trials else min(1.0, center + half)
    return (low, high)


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile (q in [0, 100]); empty -> nan."""

    data = sorted(float(v) for v in values)
    n = len(data)
    if n == 0:
        return float("nan")
    if n == 1:
        return data[0]
    rank = (q / 100.0) * (n - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return data[lo]
    frac = rank - lo
    return data[lo] * (1.0 - frac) + data[hi] * frac


def _stats(values: Sequence[float]) -> dict[str, float]:
    data = [float(v) for v in values]
    n = len(data)
    if n == 0:
        return {"count": 0, "mean": float("nan"), "median": float("nan"),
                "min": float("nan"), "max": float("nan"), "p95": float("nan"),
                "p99": float("nan")}
    return {
        "count": n,
        "mean": sum(data) / n,
        "median": percentile(data, 50.0),
        "min": min(data),
        "max": max(data),
        "p95": percentile(data, 95.0),
        "p99": percentile(data, 99.0),
    }


@dataclass
class PointAccumulator:
    """Streaming accumulator for one Eb/N0 (or configuration) point.

    Communications outcomes and infrastructure failures are tracked in disjoint
    counters.  ``add`` ingests a per-frame outcome; frames that raised a host or
    DMA error are recorded via ``add_infrastructure_failure`` and excluded from
    BER/FER denominators, matching the guardrail that DMA failures must not be
    mixed into communications FER.
    """

    label: str = ""
    frames_attempted: int = 0
    frames_completed: int = 0          # frames with a valid decoder response
    frame_errors: int = 0
    decoder_failures: int = 0          # decoder asserted failure
    undetected_errors: int = 0         # success asserted but payload wrong
    info_bit_errors: int = 0
    info_bits_total: int = 0
    coded_bits_submitted: int = 0
    saturated_frames: int = 0
    input_saturation_events: int = 0
    infrastructure_failures: int = 0
    timeouts: int = 0
    dma_errors: int = 0
    iterations: list[int] = field(default_factory=list)
    cycles: list[int] = field(default_factory=list)
    host_wall_ns: list[int] = field(default_factory=list)
    wait_ns: list[int] = field(default_factory=list)

    def add(
        self,
        *,
        bit_errors: int,
        frame_error: bool,
        decoder_failure: bool,
        undetected_error: bool,
        iterations: int,
        saturation: int,
        input_saturation_events: int = 0,
        cycles: int | None = None,
        host_wall_ns: int | None = None,
        wait_ns: int | None = None,
    ) -> None:
        self.frames_attempted += 1
        self.frames_completed += 1
        self.info_bit_errors += int(bit_errors)
        self.info_bits_total += INFO_BITS_PER_FRAME
        self.coded_bits_submitted += CODED_BITS_PER_FRAME
        self.frame_errors += int(frame_error)
        self.decoder_failures += int(decoder_failure)
        self.undetected_errors += int(undetected_error)
        self.iterations.append(int(iterations))
        self.input_saturation_events += int(input_saturation_events)
        if int(saturation) > 0:
            self.saturated_frames += 1
        if cycles is not None:
            self.cycles.append(int(cycles))
        if host_wall_ns is not None:
            self.host_wall_ns.append(int(host_wall_ns))
        if wait_ns is not None:
            self.wait_ns.append(int(wait_ns))

    def add_infrastructure_failure(self, *, timeout: bool = False, dma_error: bool = False) -> None:
        self.frames_attempted += 1
        self.infrastructure_failures += 1
        self.timeouts += int(timeout)
        self.dma_errors += int(dma_error)

    # -- derived rates -----------------------------------------------------
    @property
    def ber(self) -> float:
        return self.info_bit_errors / self.info_bits_total if self.info_bits_total else float("nan")

    @property
    def fer(self) -> float:
        return self.frame_errors / self.frames_completed if self.frames_completed else float("nan")

    def summary(self, elapsed_s: float | None = None) -> dict:
        low, high = wilson_interval(self.frame_errors, self.frames_completed)
        out: dict = {
            "label": self.label,
            "frames_attempted": self.frames_attempted,
            "frames_completed": self.frames_completed,
            "frame_errors": self.frame_errors,
            "decoder_failures": self.decoder_failures,
            "undetected_errors": self.undetected_errors,
            "info_bit_errors": self.info_bit_errors,
            "info_bits_total": self.info_bits_total,
            "coded_bits_submitted": self.coded_bits_submitted,
            "ber": self.ber,
            "fer": self.fer,
            "fer_wilson95_low": low,
            "fer_wilson95_high": high,
            "saturated_frames": self.saturated_frames,
            "input_saturation_events": self.input_saturation_events,
            "infrastructure_failures": self.infrastructure_failures,
            "timeouts": self.timeouts,
            "dma_errors": self.dma_errors,
            "iterations": _stats(self.iterations),
            "core_cycles": _stats(self.cycles),
            "host_wall_ns": _stats(self.host_wall_ns),
            "dma_wait_ns": _stats(self.wait_ns),
        }
        if self.cycles:
            mean_cycles = out["core_cycles"]["mean"]
            out["core_latency_us_mean"] = mean_cycles / CLOCK_HZ * 1e6
        if elapsed_s is not None and elapsed_s > 0:
            out["elapsed_s"] = elapsed_s
            out["frames_per_second"] = self.frames_completed / elapsed_s
            out["info_throughput_mbps"] = self.info_bits_total / elapsed_s / 1e6
            out["coded_throughput_mbps"] = self.coded_bits_submitted / elapsed_s / 1e6
            # Successfully decoded information throughput (excludes frame errors).
            good_info_bits = (self.frames_completed - self.frame_errors) * INFO_BITS_PER_FRAME
            out["good_info_throughput_mbps"] = good_info_bits / elapsed_s / 1e6
        return out


def aggregate(summaries: Iterable[dict]) -> dict:
    """Combine per-point summaries into a compact plotting-friendly table."""

    rows = []
    for s in summaries:
        rows.append({
            "label": s.get("label", ""),
            "frames_completed": s.get("frames_completed", 0),
            "ber": s.get("ber"),
            "fer": s.get("fer"),
            "fer_wilson95_low": s.get("fer_wilson95_low"),
            "fer_wilson95_high": s.get("fer_wilson95_high"),
            "mean_iterations": s.get("iterations", {}).get("mean"),
            "mean_core_cycles": s.get("core_cycles", {}).get("mean"),
            "frames_per_second": s.get("frames_per_second"),
            "info_throughput_mbps": s.get("info_throughput_mbps"),
        })
    return {"points": rows}
