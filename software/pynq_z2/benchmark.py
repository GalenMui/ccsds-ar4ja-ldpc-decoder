#!/usr/bin/env python3
"""Configurable PYNQ-Z2 LDPC decoder benchmark and validation CLI.

Subcommands
-----------
* ``correctness``  deterministic correctness campaign (status + every bit).
* ``ber-fer``      Eb/N0 sweep with statistical stopping and Wilson bounds.
* ``throughput``   steady-state frames/s and information/coded throughput.
* ``latency``      core-cycle and host wall-clock latency distributions.
* ``soak``         long-duration stability with periodic checkpoints.

Backends
--------
By default the CLI drives the physical overlay (``BoardRunner``).  ``--simulate``
switches to the bit-accurate software model (``SoftwareRunner``); simulated runs
are explicitly labelled ``source="software-model"`` in every record and summary
and never report a hardware cycle count, so they cannot be mistaken for
board-measured results.  Use ``--simulate`` for offline validation of the whole
harness; run the same commands without it from the board's root Jupyter
terminal for real measurements.

Hardware invocation (root Jupyter terminal on the PYNQ-Z2)::

    cd /home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder
    XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 benchmark.py \\
        ber-fer --ebn0 1.0 1.5 2.0 2.5 3.0 --frames 200 \\
        --output results/hardware/ber_fer.jsonl
"""

from __future__ import annotations

import argparse
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import numpy as np

try:  # flat layout on the board deploy directory
    import channel
    import experiment
    import metrics
    import vectors
    from runner import BoardRunner, SoftwareRunner
except ImportError:  # package layout in the repository
    from software.pynq_z2 import channel, experiment, metrics, vectors
    from software.pynq_z2.runner import BoardRunner, SoftwareRunner

ROOT = Path(__file__).resolve().parents[2]


def _resolve_overlay(args: argparse.Namespace) -> tuple[Path, Path]:
    overlay_dir = args.overlay_dir
    bitfile = args.bitfile or (overlay_dir / "ccsds_ldpc_pynq_z2.bit")
    hwhfile = args.hwhfile or (overlay_dir / "ccsds_ldpc_pynq_z2.hwh")
    return bitfile, hwhfile


@contextmanager
def open_backend(args: argparse.Namespace) -> Iterator[tuple[object, dict]]:
    """Yield ``(runner, provenance)`` for the selected backend."""

    if args.simulate:
        with SoftwareRunner(iterations=8, lanes=8) as runner:
            yield runner, {"bitfile": None, "hwhfile": None, "source": "software-model"}
        return
    bitfile, hwhfile = _resolve_overlay(args)
    with BoardRunner.open(
        str(bitfile), hwhfile=str(hwhfile), timeout_s=args.timeout,
        capture_status=args.capture_dma_status,
    ) as runner:
        yield runner, {"bitfile": bitfile, "hwhfile": hwhfile, "source": "hardware"}


def _make_meta(args: argparse.Namespace, experiment_name: str, prov: dict, config: dict) -> dict:
    return experiment.environment_metadata(
        root=ROOT, experiment=experiment_name, config=config,
        bitfile=prov.get("bitfile"), hwhfile=prov.get("hwhfile"),
        source=prov.get("source", "hardware"),
    )


# ---------------------------------------------------------------------------
# correctness
# ---------------------------------------------------------------------------
def cmd_correctness(args: argparse.Namespace) -> int:
    vecs = vectors.correctness_vectors(llr_scale=args.llr_scale, seed=args.seed)
    software = SoftwareRunner(iterations=8, lanes=8)
    output = args.output or Path("results/hardware/correctness.jsonl")
    writer = experiment.JsonlWriter(output)
    passed = 0
    failed = 0
    records = []
    with open_backend(args) as (runner, prov):
        meta = _make_meta(args, "correctness", prov,
                          {"llr_scale": args.llr_scale, "seed": args.seed,
                           "vectors": len(vecs)})
        for vec in vecs:
            expected = software.decode_frame(vec.frame)
            runs = []
            vector_ok = True
            for rep in range(vec.repeat):
                res = runner.decode_frame(vec.frame)
                runs.append(res)
                agree = (
                    res.ok
                    and res.success == expected.success
                    and res.syndrome_pass == expected.syndrome_pass
                    and res.failure == expected.failure
                    and res.iterations == expected.iterations
                    and res.saturation == expected.saturation
                    and res.decoded_sha256 == expected.decoded_sha256
                )
                record = res.to_record(vec.frame)
                record.update({
                    "point": vec.name,
                    "category": vec.category,
                    "repeat_index": rep,
                    "agrees_with_model": bool(agree),
                    "expected_success": expected.success,
                    "expected_iterations": expected.iterations,
                    "expected_decoded_sha256": expected.decoded_sha256,
                })
                writer.write(record)
                vector_ok &= agree
            # repeatability: all repeats identical
            shas = {r.decoded_sha256 for r in runs if r.ok}
            deterministic = len(shas) <= 1
            vector_ok &= deterministic
            records.append({"name": vec.name, "category": vec.category,
                            "ok": vector_ok, "deterministic": deterministic,
                            "repeats": vec.repeat})
            status = "PASS" if vector_ok else "FAIL"
            print(f"[{status}] {vec.name:28s} {vec.category:24s} "
                  f"model(success={expected.success},iter={expected.iterations}) "
                  f"det={deterministic}", flush=True)
            passed += int(vector_ok)
            failed += int(not vector_ok)
    writer.close()
    summary = {"meta": meta, "results": records,
               "passed": passed, "failed": failed, "total": len(vecs)}
    experiment.atomic_write_json(Path(str(output) + ".summary.json"), summary)
    print(f"\ncorrectness: {passed}/{len(vecs)} vectors agree with the model "
          f"({prov['source']}); log={output}")
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# ber-fer
# ---------------------------------------------------------------------------
def _replay_records(acc: "metrics.PointAccumulator", records) -> None:
    """Fold previously logged per-frame records back into an accumulator."""

    for rec in records:
        if not rec.get("ok", False):
            err = str(rec.get("error") or "")
            acc.add_infrastructure_failure(
                timeout=err.startswith("TimeoutError"),
                dma_error=not err.startswith("TimeoutError"))
            continue
        timing = rec.get("timing_ns") or {}
        acc.add(
            bit_errors=int(rec.get("bit_errors", 0)),
            frame_error=bool(rec.get("frame_error", False)),
            decoder_failure=bool(rec.get("failure", 0)),
            undetected_error=bool(rec.get("undetected_error", False)),
            iterations=int(rec.get("iterations", 0)),
            saturation=int(rec.get("saturation", 0)),
            input_saturation_events=int(rec.get("input_saturation_events", 0)),
            cycles=rec.get("cycles"),
            host_wall_ns=timing.get("total_ns"),
            wait_ns=timing.get("wait_ns"))


def cmd_ber_fer(args: argparse.Namespace) -> int:
    output = args.output or Path("results/hardware/ber_fer.jsonl")
    resume_counts = experiment.completed_counts(output) if args.resume else {}
    writer = experiment.JsonlWriter(output)
    config = {
        "ebn0_db": args.ebn0, "frames": args.frames, "seed": args.seed,
        "llr_scale": args.llr_scale, "max_frame_errors": args.max_frame_errors,
        "min_frames": args.min_frames, "max_seconds": args.max_seconds,
        "pattern": args.pattern,
    }
    summaries = []
    with open_backend(args) as (runner, prov):
        meta = _make_meta(args, "ber-fer", prov, config)
        for pt_i, ebn0 in enumerate(args.ebn0):
            label = f"ebn0_{ebn0:g}"
            acc = metrics.PointAccumulator(label=label)
            already = resume_counts.get(label, 0)
            if already:
                _replay_records(acc, experiment.iter_records(output, label))
            t0 = time.perf_counter()
            for frame_i in range(args.frames):
                if frame_i < already:
                    continue
                seed = args.seed + pt_i * 1_000_000 + frame_i
                frame = channel.build_frame(index=frame_i, seed=seed, ebn0_db=ebn0,
                                            pattern=args.pattern, llr_scale=args.llr_scale)
                res = runner.decode_frame(frame)
                record = res.to_record(frame)
                record["point"] = label
                writer.write(record)
                if not res.ok:
                    acc.add_infrastructure_failure(
                        timeout=(res.error or "").startswith("TimeoutError"),
                        dma_error=not (res.error or "").startswith("TimeoutError"))
                else:
                    acc.add(
                        bit_errors=res.bit_errors, frame_error=res.frame_error,
                        decoder_failure=bool(res.failure),
                        undetected_error=res.undetected_error,
                        iterations=res.iterations, saturation=res.saturation,
                        input_saturation_events=res.input_saturation_events,
                        cycles=res.cycles,
                        host_wall_ns=res.timing_ns.get("total_ns"),
                        wait_ns=res.timing_ns.get("wait_ns"))
                # statistical stopping
                done = frame_i + 1
                if done >= args.min_frames:
                    if args.max_frame_errors and acc.frame_errors >= args.max_frame_errors:
                        break
                    if args.max_seconds and (time.perf_counter() - t0) >= args.max_seconds:
                        break
            elapsed = time.perf_counter() - t0
            summ = acc.summary(elapsed_s=elapsed)
            summ["ebn0_db"] = ebn0
            summaries.append(summ)
            print(f"Eb/N0={ebn0:5.2f}  frames={summ['frames_completed']:5d}  "
                  f"FER={summ['fer']:.3e} [{summ['fer_wilson95_low']:.2e},"
                  f"{summ['fer_wilson95_high']:.2e}]  BER={summ['ber']:.3e}  "
                  f"mean_iter={summ['iterations']['mean']:.2f}  "
                  f"undetected={summ['undetected_errors']}  "
                  f"infra_fail={summ['infrastructure_failures']}", flush=True)
    writer.close()
    experiment.atomic_write_json(Path(str(output) + ".summary.json"),
                                 {"meta": meta, "points": summaries,
                                  "aggregate": metrics.aggregate(summaries)})
    print(f"\nber-fer complete; log={output}")
    return 0


# ---------------------------------------------------------------------------
# throughput / latency
# ---------------------------------------------------------------------------
def _run_steady(runner, args, ebn0) -> tuple[metrics.PointAccumulator, float, dict]:
    acc = metrics.PointAccumulator(label=f"ebn0_{ebn0}" if ebn0 is not None else "noiseless")
    warmup_ns = []
    # Cold-start warmup frames excluded from steady-state timing.
    for w in range(args.warmup):
        frame = channel.build_frame(index=w, seed=args.seed + w, ebn0_db=ebn0,
                                    pattern=args.pattern, llr_scale=args.llr_scale)
        res = runner.decode_frame(frame)
        warmup_ns.append(res.timing_ns.get("total_ns", 0))
    t0 = time.perf_counter()
    for frame_i in range(args.frames):
        seed = args.seed + 10_000 + frame_i
        frame = channel.build_frame(index=frame_i, seed=seed, ebn0_db=ebn0,
                                    pattern=args.pattern, llr_scale=args.llr_scale)
        res = runner.decode_frame(frame)
        if not res.ok:
            acc.add_infrastructure_failure(
                timeout=(res.error or "").startswith("TimeoutError"),
                dma_error=not (res.error or "").startswith("TimeoutError"))
            continue
        acc.add(bit_errors=res.bit_errors, frame_error=res.frame_error,
                decoder_failure=bool(res.failure), undetected_error=res.undetected_error,
                iterations=res.iterations, saturation=res.saturation,
                input_saturation_events=res.input_saturation_events,
                cycles=res.cycles, host_wall_ns=res.timing_ns.get("total_ns"),
                wait_ns=res.timing_ns.get("wait_ns"))
    elapsed = time.perf_counter() - t0
    extra = {"warmup_frames": args.warmup,
             "cold_start_ns_mean": float(np.mean(warmup_ns)) if warmup_ns else None}
    return acc, elapsed, extra


def cmd_throughput(args: argparse.Namespace) -> int:
    output = args.output or Path("results/hardware/throughput.json")
    ebn0 = None if args.noiseless else args.ebn0_point
    with open_backend(args) as (runner, prov):
        meta = _make_meta(args, "throughput", prov,
                          {"frames": args.frames, "warmup": args.warmup,
                           "ebn0_db": ebn0, "seed": args.seed, "llr_scale": args.llr_scale})
        acc, elapsed, extra = _run_steady(runner, args, ebn0)
    summ = acc.summary(elapsed_s=elapsed)
    summ.update(extra)
    experiment.atomic_write_json(output, {"meta": meta, "summary": summ})
    print(f"frames={summ['frames_completed']}  elapsed_s={elapsed:.3f}  "
          f"fps={summ.get('frames_per_second', float('nan')):.2f}  "
          f"info_Mbps={summ.get('info_throughput_mbps', float('nan')):.3f}  "
          f"coded_Mbps={summ.get('coded_throughput_mbps', float('nan')):.3f}")
    if summ.get("core_cycles", {}).get("count"):
        print(f"core_cycles mean={summ['core_cycles']['mean']:.1f} "
              f"p95={summ['core_cycles']['p95']:.0f}  "
              f"core_latency_us_mean={summ.get('core_latency_us_mean', float('nan')):.3f}")
    print(f"host_wall_ns mean={summ['host_wall_ns']['mean']:.0f} "
          f"p95={summ['host_wall_ns']['p95']:.0f}  cold_start_ns={extra['cold_start_ns_mean']}")
    print(f"summary={output}")
    return 0


def cmd_latency(args: argparse.Namespace) -> int:
    # Latency reuses the steady-state loop but writes per-frame latency records.
    output = args.output or Path("results/hardware/latency.jsonl")
    writer = experiment.JsonlWriter(output)
    ebn0 = None if args.noiseless else args.ebn0_point
    acc = metrics.PointAccumulator(label="latency")
    with open_backend(args) as (runner, prov):
        meta = _make_meta(args, "latency", prov,
                          {"frames": args.frames, "warmup": args.warmup,
                           "ebn0_db": ebn0, "seed": args.seed, "llr_scale": args.llr_scale})
        for w in range(args.warmup):
            frame = channel.build_frame(index=-1 - w, seed=args.seed + w, ebn0_db=ebn0,
                                        pattern=args.pattern, llr_scale=args.llr_scale)
            runner.decode_frame(frame)
        for frame_i in range(args.frames):
            frame = channel.build_frame(index=frame_i, seed=args.seed + 10_000 + frame_i,
                                        ebn0_db=ebn0, pattern=args.pattern, llr_scale=args.llr_scale)
            res = runner.decode_frame(frame)
            record = res.to_record(frame)
            record["point"] = "latency"
            writer.write(record)
            if res.ok:
                acc.add(bit_errors=res.bit_errors, frame_error=res.frame_error,
                        decoder_failure=bool(res.failure), undetected_error=res.undetected_error,
                        iterations=res.iterations, saturation=res.saturation,
                        cycles=res.cycles, host_wall_ns=res.timing_ns.get("total_ns"),
                        wait_ns=res.timing_ns.get("wait_ns"))
    writer.close()
    summ = acc.summary()
    experiment.atomic_write_json(Path(str(output) + ".summary.json"), {"meta": meta, "summary": summ})
    print(f"latency frames={summ['frames_completed']}")
    if summ.get("core_cycles", {}).get("count"):
        cc = summ["core_cycles"]
        print(f"core_cycles mean={cc['mean']:.1f} median={cc['median']:.0f} "
              f"p95={cc['p95']:.0f} p99={cc['p99']:.0f}")
    hw = summ["host_wall_ns"]
    print(f"host_wall_ns mean={hw['mean']:.0f} median={hw['median']:.0f} p95={hw['p95']:.0f}")
    print(f"log={output}")
    return 0


# ---------------------------------------------------------------------------
# soak
# ---------------------------------------------------------------------------
def cmd_soak(args: argparse.Namespace) -> int:
    output = args.output or Path("results/hardware/soak.jsonl")
    writer = experiment.JsonlWriter(output)
    checkpoint = Path(str(output) + ".checkpoint.json")
    ebn0 = None if args.noiseless else args.ebn0_point
    acc = metrics.PointAccumulator(label="soak")
    deadline = time.perf_counter() + args.minutes * 60.0 if args.minutes else None
    consecutive_infra = 0
    frame_i = 0
    stop_reason = "frames_exhausted"
    with open_backend(args) as (runner, prov):
        meta = _make_meta(args, "soak", prov,
                          {"minutes": args.minutes, "max_frames": args.frames,
                           "ebn0_db": ebn0, "seed": args.seed, "llr_scale": args.llr_scale,
                           "error_threshold": args.error_threshold})
        start = time.perf_counter()
        while True:
            if args.frames and frame_i >= args.frames:
                break
            if deadline is not None and time.perf_counter() >= deadline:
                stop_reason = "time_elapsed"
                break
            seed = args.seed + frame_i
            frame = channel.build_frame(index=frame_i, seed=seed, ebn0_db=ebn0,
                                        pattern=args.pattern, llr_scale=args.llr_scale)
            res = runner.decode_frame(frame)
            record = res.to_record(frame)
            record["point"] = "soak"
            writer.write(record)
            if not res.ok:
                consecutive_infra += 1
                acc.add_infrastructure_failure(
                    timeout=(res.error or "").startswith("TimeoutError"),
                    dma_error=not (res.error or "").startswith("TimeoutError"))
                # save the exact reproducing frame
                experiment.atomic_write_json(
                    Path(str(output) + f".failure_{frame_i}.json"),
                    {"seed": seed, "ebn0_db": ebn0, "index": frame_i,
                     "llr_scale": args.llr_scale, "pattern": args.pattern,
                     "payload_sha256": frame.payload_sha256, "llr_sha256": frame.llr_sha256,
                     "quantized_llr": frame.quantized_llr.astype(int).tolist(),
                     "error": res.error, "dma_status": res.dma_status})
                if consecutive_infra >= args.error_threshold:
                    stop_reason = "error_threshold"
                    break
            else:
                consecutive_infra = 0
                acc.add(bit_errors=res.bit_errors, frame_error=res.frame_error,
                        decoder_failure=bool(res.failure), undetected_error=res.undetected_error,
                        iterations=res.iterations, saturation=res.saturation,
                        cycles=res.cycles, host_wall_ns=res.timing_ns.get("total_ns"),
                        wait_ns=res.timing_ns.get("wait_ns"))
            frame_i += 1
            if frame_i % args.checkpoint_every == 0:
                elapsed = time.perf_counter() - start
                experiment.atomic_write_json(checkpoint, {
                    "meta": meta, "frames": frame_i, "elapsed_s": elapsed,
                    "last_seed": seed, "summary": acc.summary(elapsed_s=elapsed)})
                print(f"[checkpoint] frames={frame_i} elapsed_s={elapsed:.1f} "
                      f"errors={acc.frame_errors} infra={acc.infrastructure_failures} "
                      f"undetected={acc.undetected_errors}", flush=True)
        elapsed = time.perf_counter() - start
    writer.close()
    summ = acc.summary(elapsed_s=elapsed)
    experiment.atomic_write_json(Path(str(output) + ".summary.json"),
                                 {"meta": meta, "frames": frame_i, "elapsed_s": elapsed,
                                  "stop_reason": stop_reason, "summary": summ})
    print(f"\nsoak stopped ({stop_reason}) after {frame_i} frames in {elapsed:.1f}s; "
          f"frame_errors={acc.frame_errors} undetected={acc.undetected_errors} "
          f"infra_failures={acc.infrastructure_failures}")
    return 0 if stop_reason != "error_threshold" else 2


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------
def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--overlay-dir", type=Path, default=Path.cwd())
    p.add_argument("--bitfile", type=Path)
    p.add_argument("--hwhfile", type=Path)
    p.add_argument("--simulate", action="store_true",
                   help="use the bit-accurate software model instead of hardware")
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--llr-scale", type=float, default=channel.DEFAULT_LLR_SCALE)
    p.add_argument("--pattern", default="random", choices=channel.PAYLOAD_PATTERNS)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--capture-dma-status", action="store_true")
    p.add_argument("--output", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("correctness", help="deterministic correctness campaign")
    _add_common(c)
    c.set_defaults(func=cmd_correctness)

    b = sub.add_parser("ber-fer", help="Eb/N0 BER/FER sweep")
    _add_common(b)
    b.add_argument("--ebn0", nargs="+", type=float, default=[1.0, 1.5, 2.0, 2.5, 3.0])
    b.add_argument("--frames", type=int, default=200)
    b.add_argument("--min-frames", type=int, default=20)
    b.add_argument("--max-frame-errors", type=int, default=0,
                   help="stop a point after this many frame errors (0 = disabled)")
    b.add_argument("--max-seconds", type=float, default=0.0,
                   help="stop a point after this many seconds (0 = disabled)")
    b.add_argument("--resume", action="store_true")
    b.set_defaults(func=cmd_ber_fer)

    t = sub.add_parser("throughput", help="steady-state throughput")
    _add_common(t)
    t.add_argument("--frames", type=int, default=200)
    t.add_argument("--warmup", type=int, default=5)
    t.add_argument("--ebn0-point", type=float, default=3.0)
    t.add_argument("--noiseless", action="store_true")
    t.set_defaults(func=cmd_throughput)

    lat = sub.add_parser("latency", help="latency distributions")
    _add_common(lat)
    lat.add_argument("--frames", type=int, default=200)
    lat.add_argument("--warmup", type=int, default=5)
    lat.add_argument("--ebn0-point", type=float, default=3.0)
    lat.add_argument("--noiseless", action="store_true")
    lat.set_defaults(func=cmd_latency)

    s = sub.add_parser("soak", help="long-duration stability test")
    _add_common(s)
    s.add_argument("--minutes", type=float, default=0.0,
                   help="wall-clock duration (0 = use --frames)")
    s.add_argument("--frames", type=int, default=0, help="max frames (0 = use --minutes)")
    s.add_argument("--ebn0-point", type=float, default=3.0)
    s.add_argument("--noiseless", action="store_true")
    s.add_argument("--checkpoint-every", type=int, default=500)
    s.add_argument("--error-threshold", type=int, default=10,
                   help="stop after this many consecutive infrastructure failures")
    s.set_defaults(func=cmd_soak)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "command", None) == "soak" and not args.minutes and not args.frames:
        print("ERROR: soak requires --minutes or --frames", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
