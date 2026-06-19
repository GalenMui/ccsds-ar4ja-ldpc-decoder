from pathlib import Path

from models import ar4ja_matrix as ar4ja
from scripts.gen_vectors import generate_vectors


def test_vector_generation_is_deterministic(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    generate_vectors(first_dir)
    generate_vectors(second_dir)

    names = [
        "syndrome_vectors.txt",
        "tx.mem",
        "syndrome.mem",
        "pass.mem",
        "syndrome_meta.svh",
    ]
    for name in names:
        assert (first_dir / name).read_text() == (second_dir / name).read_text()


def test_vector_files_have_expected_shapes(tmp_path):
    output = tmp_path / "vectors"
    generate_vectors(output)

    tx_lines = (output / "tx.mem").read_text().strip().splitlines()
    syndrome_lines = (output / "syndrome.mem").read_text().strip().splitlines()
    pass_lines = (output / "pass.mem").read_text().strip().splitlines()
    meta = (output / "syndrome_meta.svh").read_text()

    assert len(tx_lines) == 5
    assert len(syndrome_lines) == 5
    assert len(pass_lines) == 5
    assert f"SYNDROME_VECTOR_COUNT = {len(tx_lines)}" in meta
    assert all(len(line) == ar4ja.TX_N // 4 for line in tx_lines)
    assert all(len(line) == ar4ja.CHECKS // 4 for line in syndrome_lines)
    assert pass_lines == ["1", "1", "0", "0", "1"]

