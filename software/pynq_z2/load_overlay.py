#!/usr/bin/env python3
"""Program the PYNQ-Z2 and verify overlay metadata and DMA initialization."""

from __future__ import annotations

import argparse
from pathlib import Path

from pynq import Overlay

OVERLAY_BASENAME = "ccsds_ldpc_pynq_z2"
EXPECTED_DMA = "axi_dma_0"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()

    overlay_dir = args.overlay_dir.expanduser().resolve()
    bitfile = overlay_dir / f"{OVERLAY_BASENAME}.bit"
    hwhfile = overlay_dir / f"{OVERLAY_BASENAME}.hwh"
    if not bitfile.is_file() or not hwhfile.is_file():
        raise FileNotFoundError(f"matching .bit/.hwh not found in {overlay_dir}")

    overlay = Overlay(str(bitfile), download=True)
    ip_names = sorted(overlay.ip_dict)
    print(f"Bitstream loaded: {overlay.is_loaded()}")
    print(f"Available IP: {ip_names}")
    if not overlay.is_loaded():
        raise RuntimeError("PYNQ reports that the bitstream is not loaded")
    if EXPECTED_DMA not in overlay.ip_dict:
        raise RuntimeError(f"expected {EXPECTED_DMA!r} is missing from overlay metadata")

    dma = getattr(overlay, EXPECTED_DMA)
    for channel in ("sendchannel", "recvchannel"):
        if not hasattr(dma, channel):
            raise RuntimeError(f"{EXPECTED_DMA} is missing {channel}")
    print("DMA initialized: MM2S and S2MM channels are available")
    print("LOAD-ONLY PASS (decoder functionality not tested)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
