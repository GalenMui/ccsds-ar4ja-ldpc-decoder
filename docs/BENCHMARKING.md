# PYNQ-Z2 LDPC Hardware Benchmark Suite

This document describes the reproducible benchmarking and validation framework
built around the verified `LANES=8`, 100 MHz CCSDS AR4JA rate-1/2 (k=1024,
n=2048) decoder overlay. It covers the communications pipeline, conventions,
experiment configuration, output schema, metric definitions, and the privileged
board workflow.

> **Measurement honesty.** Only results produced by `source: "hardware"` records
> are physical-board measurements. `source: "software-model"` records come from
> the bit-accurate fixed-point reference (`--simulate`) and are used for harness
> validation and hardware equivalence, never presented as board throughput or
> BER. This repository currently contains no committed hardware benchmark
> datasets; the single verified physical result remains the one zero-noise frame
> documented in `docs/PYNQ_Z2_BRINGUP.md`.

## Components

| File | Role |
|------|------|
| `software/pynq_z2/channel.py`   | payload → encode → BPSK → AWGN → LLR → quantize → pack |
| `software/pynq_z2/metrics.py`   | BER/FER, Wilson intervals, percentiles, throughput |
| `software/pynq_z2/vectors.py`   | deterministic correctness-vector set |
| `software/pynq_z2/runner.py`    | `BoardRunner` (hardware) and `SoftwareRunner` (model) |
| `software/pynq_z2/experiment.py`| provenance, atomic JSON, JSONL logging, resume |
| `software/pynq_z2/benchmark.py` | CLI: `correctness`, `ber-fer`, `throughput`, `latency`, `soak` |
| `scripts/plot_benchmark.py`     | aggregate JSONL → CSV and matplotlib plots |

The runners share one `FrameResult`, so the CLI is backend-agnostic. `BoardRunner`
allocates one contiguous input/output buffer pair and reuses it across frames
(`PynqLdpcDecoder.run_prepacked`), separating one-time setup from steady-state
per-frame overhead.

## Communications conventions

* **BPSK:** bit 0 → +1, bit 1 → −1.
* **LLR:** `L = 2·y / σ²`; positive ⇒ bit 0, negative ⇒ bit 1, zero ⇒ bit 0.
* **Quantization:** signed int8 `[−128, 127]`, round half away from zero,
  saturate; a saturation event is counted only when clipping changes the value.
* **Packing:** 2048 int8 LLRs → 512 little-lane uint32 words (`bits[7:0]` is the
  lowest codeword index in each word). One DMA transaction = one codeword.

### Eb/N0, Es/N0, and noise variance

BPSK symbols have unit energy (Es = 1). The transmitted code rate is
R = k/n = 1024/2048 = 1/2 (the 512 punctured parity symbols are never sent).

```
Es/N0 [dB] = Eb/N0 [dB] + 10·log10(R)          # R = 1/2  →  −3.0103 dB
σ²         = 1 / (2 · (Es/N0)_lin)
           = 1 / (2 · R · (Eb/N0)_lin)
```

All CLI SNR arguments are **Eb/N0 in dB**. `channel.ebn0_db_to_esn0_db` performs
the rate correction before the symbol-SNR AWGN model is invoked, so an operating
point is never overstated by the 3.01 dB rate offset.

### LLR quantization scale

`--llr-scale` (default **2.0**) multiplies the floating LLR before int8 rounding.
It is a *host* choice: hardware and the software reference receive the identical
quantized int8 LLRs, so **hardware/software agreement is independent of the
scale**. The scale only shapes the BER/FER curve and the input saturation rate.
A short software-reference sweep (8-iteration model) places the waterfall near
~2 dB Eb/N0 with scale 2.0 and no input saturation; the value should be
characterised on hardware and is not a tuned optimum.

## Hardware/software equivalence

The bit-accurate model `decode_normalized_min_sum_fixed` matches the RTL
quantization, 3/4 normalized min-sum, int8 message clipping, layered schedule,
early termination, and output decision rule. Feeding both hardware and the model
the **same** quantized int8 LLRs must yield identical `success`, `syndrome`,
`failure`, `iterations`, `saturation`, and every decoded bit. The `correctness`
command asserts exactly this, per vector.

Note the punctured parity bits initialise to neutral 0, so only the all-zero
frame decodes in `iterations = 0`; a random noiseless frame needs ≥1 iteration to
resolve the punctured symbols. Both are expected and reproduced by the model.

## Output schema (schema_version 1)

* `<output>.jsonl` — one JSON object per frame (append-only, `fsync`-flushed).
  Key fields: `index`, `source`, `ok`, `seed`, `ebn0_db`, `point`, `success`,
  `syndrome_pass`, `failure`, `iterations`, `saturation`, `cycles`
  (hardware only), `modeled_core_cycles`, `bit_errors`, `frame_error`,
  `undetected_error`, `timing_ns`, `dma_status`, `error`.
* `<output>.summary.json` — environment/provenance + config + per-point
  summaries, written atomically (temp file + `os.replace`).

Provenance captured: timestamp, git commit + dirty flag, hostname, Python/NumPy/
PYNQ versions, bitstream/HWH names + SHA-256, overlay manifest, decoder
parameters, clock, lanes, seed, experiment type, config, and schema version.

## Metric definitions

```
BER = incorrect decoded information bits / transmitted information bits
FER = frames with any incorrect info bit OR decoder-declared failure / frames completed
undetected error = success asserted but decoded payload wrong
```

Host/DMA infrastructure failures (timeout, DMA error, exception) are counted
**separately** and never folded into FER. Core latency uses the decoder cycle
counter (`latency_s = cycles / 100e6`); host wall time is reported separately and
never labelled as core latency. Throughput reports both information (1024
bits/frame) and coded (2048 bits/frame) rates, plus a successfully-decoded
information rate.

### Statistical stopping and confidence

`ber-fer` supports `--min-frames`, `--max-frame-errors`, and `--max-seconds`. A
zero-error point is never reported as a proven zero FER: every point carries a
two-sided **Wilson 95 %** interval, so a zero-error point yields a non-zero upper
bound. A useful target is ~50–100 observed frame errors per waterfall point.

## Board workflow (privileged root Jupyter terminal)

Hardware access requires the board's existing root Jupyter context; the suite
never weakens permissions, adds passwordless sudo, or changes the PYNQ install.

1. **Deploy** (unprivileged SSH), from the host:
   ```sh
   make pynq-z2-package
   ./scripts/board/deploy_pynq.sh
   ```
2. **Run** from the board's root Jupyter terminal (`make pynq-z2-benchmark-cmds`
   prints these):
   ```sh
   cd /home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder
   XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 benchmark.py correctness \
       --output results/hardware/correctness.jsonl
   XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 benchmark.py ber-fer \
       --ebn0 1.0 1.5 2.0 2.5 3.0 --frames 200 --max-frame-errors 60 --resume \
       --output results/hardware/ber_fer.jsonl
   ```
3. **Retrieve** results over unprivileged SSH (e.g. `scp`/`rsync` the
   `results/hardware/` JSONL files back).
4. **Analyse locally:**
   ```sh
   make pynq-z2-analyze BENCH_RESULTS=results/hardware/ber_fer.jsonl
   python3 scripts/plot_benchmark.py ber-fer results/hardware/ber_fer.jsonl
   ```

Every experiment is resumable: rerun the same command with `--resume` and the
already-logged frames (by point label) are replayed into the summary and skipped;
deterministic seeding reproduces the exact remaining frames.

## Offline self-check

`make benchmark-selftest` runs `ber-fer` and `throughput` under `--simulate`
(software model) plus CSV aggregation, exercising the full harness with no
hardware and no fabricated hardware numbers.

## Recommended first hardware campaign

1. `correctness` (≈16 vectors, seconds) — must fully agree with the model.
2. `throughput --noiseless --frames 500` — steady-state fps and buffer reuse.
3. Pilot `ber-fer --ebn0 1.0 1.5 2.0 2.5 3.0 --frames 200 --max-frame-errors 60`.
4. Only if the pilot is clean and monotonic: a denser waterfall sweep (0.25 dB)
   and a short (10–30 min) `soak` before any overnight run.

## Current limitations

* Max iterations (8) and `LANES=8` are compile-time RTL parameters, not runtime
  configurable; iteration/lane tradeoff studies require rebuilding bitstreams.
* One DMA transaction carries exactly one codeword; the suite does not claim
  streaming throughput across overlapping frames.
* `--llr-scale` is a documented default pending hardware characterisation.
* matplotlib is required only for the plotting subcommands (not for `csv` or the
  benchmark runs themselves).
