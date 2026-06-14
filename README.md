# ccsds-ar4ja-ldpc-decoder

Fixed-mode LDPC decoder accelerator experiments for the CCSDS AR4JA family.

This repository is for a SystemVerilog/Python implementation of an educational
decoder targeting one CCSDS AR4JA configuration:

- Code family: CCSDS AR4JA LDPC
- Rate: 1/2
- Information block length: k = 1024
- Codeword length: n = 2048

The intent is to keep the algorithm model, verification collateral, and RTL
implementation close enough that design changes can be checked from Python
through simulation without hiding the fixed-mode assumptions.

## Signal Chain

The planned signal chain is:

1. Receive channel observations or soft decisions for one 2048-bit codeword.
2. Convert inputs into fixed-point log-likelihood ratios.
3. Run iterative LDPC message passing for the fixed AR4JA parity-check matrix.
4. Make hard decisions on the decoded information bits.
5. Report decoder status, iteration count, and frame-level checks.

The first implementation target is a fixed rate-1/2 decoder rather than a
parameterized CCSDS modem.

## Repository Structure

```text
docs/        Notes, references, and design documentation
models/      Python reference models and algorithm experiments
rtl/         SystemVerilog RTL
sim/         Simulation harnesses and simulator-specific files
scripts/     Utility scripts for generation, analysis, and automation
tests/       Unit tests and regression entry points
vectors/     Input/output vectors used by models and simulations
results/     Local generated results; keep only intentional artifacts
```

## Current Status

The repository is at the project scaffold stage. The next work should define
the fixed AR4JA parity-check structure, add a Python reference decoder, and
then use that model to drive RTL interface and verification choices.

No decoder implementation or passing verification suite is claimed yet.

## Build and Test

Install the Python dependencies:

```sh
python -m pip install -r requirements.txt
```

Show available Make targets:

```sh
make help
```

Run tests once they exist:

```sh
make test
```

At the moment, `make test` reports that tests are not implemented yet.

## Disclaimer

This is an educational fixed-mode decoder project for CCSDS AR4JA LDPC,
rate 1/2, k = 1024, n = 2048. It is not a full CCSDS modem and does not aim to
cover every coding, synchronization, framing, or waveform requirement.
