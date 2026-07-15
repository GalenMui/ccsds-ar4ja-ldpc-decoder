#!/usr/bin/env python3
"""Analyse and plot LDPC hardware-benchmark result files.

Reads the per-frame JSON Lines emitted by ``software/pynq_z2/benchmark.py`` and
re-derives every aggregate from those records, so results are correct even after
a resumed/interrupted run.  ``matplotlib`` is imported lazily; ``csv`` and
``summary`` work without it.

Subcommands
-----------
* ``csv <jsonl>``        write a plotting-friendly per-point aggregate CSV.
* ``ber-fer <jsonl>``    BER/FER vs Eb/N0 (Wilson 95 % band) + iterations.
* ``latency <jsonl>``    core-cycle and host-wall latency histograms.
* ``soak <jsonl>``       throughput / error history over the soak run.

Nothing is hard-coded: axis labels carry units, titles carry the decoder
configuration and sample counts, and no smoothing is applied to raw points.
"""

from __future__ import annotations

import argparse
import csv as csvmod
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from software.pynq_z2 import experiment, metrics  # noqa: E402

CONFIG_LABEL = "CCSDS AR4JA r=1/2, k=1024, LANES=8, max_iter=8, 100 MHz"


def _group_by_ebn0(jsonl: Path) -> dict[float, metrics.PointAccumulator]:
    groups: dict[float, metrics.PointAccumulator] = {}
    for rec in experiment.iter_records(jsonl):
        ebn0 = rec.get("ebn0_db")
        key = float(ebn0) if ebn0 is not None else float("nan")
        acc = groups.setdefault(key, metrics.PointAccumulator(label=f"ebn0_{key}"))
        _fold(acc, rec)
    return groups


def _fold(acc: metrics.PointAccumulator, rec: dict) -> None:
    if not rec.get("ok", False):
        err = str(rec.get("error") or "")
        acc.add_infrastructure_failure(timeout=err.startswith("TimeoutError"),
                                       dma_error=not err.startswith("TimeoutError"))
        return
    timing = rec.get("timing_ns") or {}
    acc.add(bit_errors=int(rec.get("bit_errors", 0)),
            frame_error=bool(rec.get("frame_error", False)),
            decoder_failure=bool(rec.get("failure", 0)),
            undetected_error=bool(rec.get("undetected_error", False)),
            iterations=int(rec.get("iterations", 0)),
            saturation=int(rec.get("saturation", 0)),
            input_saturation_events=int(rec.get("input_saturation_events", 0)),
            cycles=rec.get("cycles"),
            host_wall_ns=timing.get("total_ns"),
            wait_ns=timing.get("wait_ns"))


def _source(jsonl: Path) -> str:
    for rec in experiment.iter_records(jsonl):
        return str(rec.get("source", "unknown"))
    return "unknown"


def cmd_csv(args: argparse.Namespace) -> int:
    groups = _group_by_ebn0(args.jsonl)
    out = args.output or args.jsonl.with_suffix(".aggregate.csv")
    fields = ["ebn0_db", "frames_completed", "frame_errors", "ber", "fer",
              "fer_wilson95_low", "fer_wilson95_high", "undetected_errors",
              "decoder_failures", "infrastructure_failures", "mean_iterations",
              "mean_core_cycles", "p95_core_cycles"]
    with Path(out).open("w", newline="", encoding="ascii") as handle:
        writer = csvmod.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for ebn0 in sorted(groups):
            s = groups[ebn0].summary()
            writer.writerow({
                "ebn0_db": ebn0, "frames_completed": s["frames_completed"],
                "frame_errors": s["frame_errors"], "ber": s["ber"], "fer": s["fer"],
                "fer_wilson95_low": s["fer_wilson95_low"],
                "fer_wilson95_high": s["fer_wilson95_high"],
                "undetected_errors": s["undetected_errors"],
                "decoder_failures": s["decoder_failures"],
                "infrastructure_failures": s["infrastructure_failures"],
                "mean_iterations": s["iterations"]["mean"],
                "mean_core_cycles": s["core_cycles"]["mean"],
                "p95_core_cycles": s["core_cycles"]["p95"]})
    print(f"wrote {out}")
    return 0


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def cmd_ber_fer(args: argparse.Namespace) -> int:
    plt = _plt()
    groups = _group_by_ebn0(args.jsonl)
    src = _source(args.jsonl)
    xs = sorted(k for k in groups if k == k)  # drop nan
    fers, ber, lo, hi, iters, ns = [], [], [], [], [], []
    for x in xs:
        s = groups[x].summary()
        fers.append(s["fer"]); ber.append(s["ber"])
        lo.append(s["fer"] - s["fer_wilson95_low"])
        hi.append(s["fer_wilson95_high"] - s["fer"])
        iters.append(s["iterations"]["mean"]); ns.append(s["frames_completed"])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    ax1.errorbar(xs, fers, yerr=[lo, hi], fmt="o-", capsize=3, label="FER (Wilson 95%)")
    ax1.plot(xs, ber, "s--", label="BER")
    ax1.set_yscale("log")
    ax1.set_xlabel("Eb/N0 (dB)")
    ax1.set_ylabel("error rate")
    ax1.set_title(f"BER/FER vs Eb/N0 [{src}]")
    ax1.grid(True, which="both", alpha=0.3)
    ax1.legend()
    for x, n in zip(xs, ns):
        ax1.annotate(f"n={n}", (x, max(fers) if fers else 1), fontsize=7)

    ax2.plot(xs, iters, "o-")
    ax2.set_xlabel("Eb/N0 (dB)")
    ax2.set_ylabel("mean iterations")
    ax2.set_title("Mean decoder iterations vs Eb/N0")
    ax2.grid(True, alpha=0.3)
    fig.suptitle(CONFIG_LABEL, fontsize=9)
    fig.tight_layout()
    out = args.output or args.jsonl.with_suffix(".ber_fer.png")
    fig.savefig(out, dpi=130)
    print(f"wrote {out}")
    return 0


def cmd_latency(args: argparse.Namespace) -> int:
    plt = _plt()
    cycles, wall_us = [], []
    for rec in experiment.iter_records(args.jsonl):
        if not rec.get("ok", False):
            continue
        if rec.get("cycles") is not None:
            cycles.append(int(rec["cycles"]))
        t = (rec.get("timing_ns") or {}).get("total_ns")
        if t is not None:
            wall_us.append(t / 1000.0)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    if cycles:
        axes[0].hist(cycles, bins=40)
        axes[0].set_xlabel("decoder core cycles")
        axes[0].set_ylabel("frames")
        axes[0].set_title(f"Core-cycle latency (n={len(cycles)})")
    else:
        axes[0].text(0.5, 0.5, "no hardware cycle data\n(software-model run)",
                     ha="center", va="center")
    axes[1].hist(wall_us, bins=40)
    axes[1].set_xlabel("host wall time (us)")
    axes[1].set_ylabel("frames")
    axes[1].set_title(f"End-to-end host latency (n={len(wall_us)})")
    fig.suptitle(CONFIG_LABEL, fontsize=9)
    fig.tight_layout()
    out = args.output or args.jsonl.with_suffix(".latency.png")
    fig.savefig(out, dpi=130)
    print(f"wrote {out}")
    return 0


def cmd_soak(args: argparse.Namespace) -> int:
    plt = _plt()
    idx, cumulative_errors, wall_us = [], [], []
    errs = 0
    for i, rec in enumerate(experiment.iter_records(args.jsonl)):
        errs += int(bool(rec.get("frame_error")) or not rec.get("ok", True))
        idx.append(i)
        cumulative_errors.append(errs)
        t = (rec.get("timing_ns") or {}).get("total_ns")
        wall_us.append((t / 1000.0) if t is not None else float("nan"))
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].plot(idx, cumulative_errors)
    axes[0].set_xlabel("frame index")
    axes[0].set_ylabel("cumulative errors (frame + infra)")
    axes[0].set_title("Soak error history")
    axes[1].plot(idx, wall_us, ",")
    axes[1].set_xlabel("frame index")
    axes[1].set_ylabel("host wall time (us)")
    axes[1].set_title("Soak per-frame host latency")
    fig.suptitle(CONFIG_LABEL, fontsize=9)
    fig.tight_layout()
    out = args.output or args.jsonl.with_suffix(".soak.png")
    fig.savefig(out, dpi=130)
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("csv", cmd_csv), ("ber-fer", cmd_ber_fer),
                       ("latency", cmd_latency), ("soak", cmd_soak)):
        p = sub.add_parser(name)
        p.add_argument("jsonl", type=Path)
        p.add_argument("--output", type=Path)
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
