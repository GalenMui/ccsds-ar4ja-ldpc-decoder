"""Experiment provenance, machine-readable logging, and resume support.

Output layout for one experiment run:

* ``<output>.jsonl``   -- one JSON object per frame (append-only, flushed).
* ``<output>.summary.json`` -- environment + config + per-point summaries,
  written atomically (temp file + os.replace) so an interrupted run never
  leaves a half-written summary.

Resume is driven entirely by the per-frame JSONL: on restart the already-logged
``(point_label, index)`` pairs are counted and skipped.  Because every frame is
regenerated from a deterministic seed, resuming produces exactly the frames a
single uninterrupted run would have.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CLOCK_MHZ = 100.0
DECODER_LANES = 8
DECODER_MAX_ITERS = 8
DECODER_LLR_BITS = 8


def _git(root: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, check=True, text=True, capture_output=True
        )
        return result.stdout.strip()
    except Exception:  # noqa: BLE001 - git may be unavailable on the board
        return None


def git_provenance(root: Path) -> dict[str, Any]:
    commit = _git(root, ["rev-parse", "HEAD"])
    status = _git(root, ["status", "--porcelain"])
    return {
        "git_commit": commit,
        "git_dirty": bool(status) if status is not None else None,
    }


def sha256_file(path: Path) -> str | None:
    if not path or not Path(path).exists():
        return None
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pynq_version() -> str | None:
    try:
        import pynq  # type: ignore

        return getattr(pynq, "__version__", None)
    except Exception:  # noqa: BLE001
        return None


def environment_metadata(
    *,
    root: Path,
    experiment: str,
    config: dict[str, Any],
    bitfile: Path | None = None,
    hwhfile: Path | None = None,
    source: str = "hardware",
) -> dict[str, Any]:
    """Assemble the reproducibility metadata block for an experiment."""

    import numpy as np

    manifest: dict[str, Any] | None = None
    if bitfile is not None:
        manifest_path = Path(bitfile).with_name("manifest.json")
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
            except Exception:  # noqa: BLE001
                manifest = None

    meta: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": experiment,
        "source": source,
        "hostname": socket.gethostname(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy_version": np.__version__,
        "pynq_version": _pynq_version(),
        "decoder": {
            "code": "CCSDS AR4JA rate-1/2",
            "k": 1024,
            "n": 2048,
            "lanes": DECODER_LANES,
            "max_iterations": DECODER_MAX_ITERS,
            "llr_bits": DECODER_LLR_BITS,
            "clock_mhz": CLOCK_MHZ,
        },
        "bitstream_file": Path(bitfile).name if bitfile else None,
        "bitstream_sha256": sha256_file(Path(bitfile)) if bitfile else None,
        "hwh_file": Path(hwhfile).name if hwhfile else None,
        "hwh_sha256": sha256_file(Path(hwhfile)) if hwhfile else None,
        "overlay_manifest": manifest,
        "config": config,
    }
    meta.update(git_provenance(root))
    return meta


def atomic_write_json(path: Path, obj: Any) -> None:
    """Write JSON to ``path`` atomically via a temp file and os.replace."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=_json_default) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _json_default(obj: Any) -> Any:
    import numpy as np

    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"not JSON serialisable: {type(obj)!r}")


class JsonlWriter:
    """Append-only JSON Lines writer that flushes each record."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")

    def write(self, record: dict[str, Any]) -> None:
        self._handle.write(json.dumps(record, default=_json_default) + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "JsonlWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def iter_records(path: Path, label: str | None = None):
    """Yield JSONL records, optionally filtered to one point label."""

    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if label is None or str(record.get("point", record.get("label", ""))) == label:
                yield record


def completed_counts(path: Path) -> dict[str, int]:
    """Return {point_label: frames_already_logged} from an existing JSONL.

    Malformed trailing lines (from an interrupted write) are ignored so a
    partially flushed file is still a valid resume source.
    """

    counts: dict[str, int] = {}
    p = Path(path)
    if not p.exists():
        return counts
    with p.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            label = str(record.get("point", record.get("label", "")))
            counts[label] = counts.get(label, 0) + 1
    return counts
