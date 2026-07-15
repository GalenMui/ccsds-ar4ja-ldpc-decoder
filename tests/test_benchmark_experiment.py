"""Tests for provenance capture, JSONL logging, and resume support."""

import json
from pathlib import Path

from software.pynq_z2 import experiment


def test_atomic_write_json_roundtrip(tmp_path):
    path = tmp_path / "sub" / "out.json"
    experiment.atomic_write_json(path, {"a": 1, "b": [1, 2, 3]})
    assert json.loads(path.read_text()) == {"a": 1, "b": [1, 2, 3]}
    assert not path.with_suffix(".json.tmp").exists()


def test_jsonl_writer_and_counts(tmp_path):
    path = tmp_path / "run.jsonl"
    with experiment.JsonlWriter(path) as writer:
        writer.write({"point": "ebn0_1.0", "index": 0, "ok": True})
        writer.write({"point": "ebn0_1.0", "index": 1, "ok": True})
        writer.write({"point": "ebn0_2.0", "index": 0, "ok": True})
    counts = experiment.completed_counts(path)
    assert counts == {"ebn0_1.0": 2, "ebn0_2.0": 1}


def test_completed_counts_ignores_partial_last_line(tmp_path):
    path = tmp_path / "run.jsonl"
    path.write_text('{"point": "p", "index": 0}\n{"point": "p", "index": 1}\n{"point": "p"')
    assert experiment.completed_counts(path) == {"p": 2}


def test_iter_records_filters_by_label(tmp_path):
    path = tmp_path / "run.jsonl"
    with experiment.JsonlWriter(path) as writer:
        writer.write({"point": "a", "v": 1})
        writer.write({"point": "b", "v": 2})
        writer.write({"point": "a", "v": 3})
    values = [r["v"] for r in experiment.iter_records(path, "a")]
    assert values == [1, 3]
    assert len(list(experiment.iter_records(path))) == 3


def test_completed_counts_missing_file(tmp_path):
    assert experiment.completed_counts(tmp_path / "nope.jsonl") == {}


def test_environment_metadata_has_required_provenance(tmp_path):
    root = Path(__file__).resolve().parents[1]
    meta = experiment.environment_metadata(
        root=root, experiment="ber-fer",
        config={"seed": 1, "frames": 10}, source="software-model")
    for key in ("schema_version", "timestamp_utc", "experiment", "hostname",
                "python_version", "numpy_version", "decoder", "config",
                "git_commit", "git_dirty"):
        assert key in meta
    assert meta["experiment"] == "ber-fer"
    assert meta["decoder"]["lanes"] == 8
    assert meta["decoder"]["max_iterations"] == 8
    assert meta["schema_version"] == experiment.SCHEMA_VERSION


def test_sha256_file(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello")
    import hashlib
    assert experiment.sha256_file(p) == hashlib.sha256(b"hello").hexdigest()
    assert experiment.sha256_file(tmp_path / "missing") is None
