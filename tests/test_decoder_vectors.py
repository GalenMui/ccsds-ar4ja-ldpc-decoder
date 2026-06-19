from scripts.gen_decoder_vectors import build_vectors, generate_vectors


def test_decoder_vectors_include_success_and_failure_cases():
    vectors = build_vectors()
    assert any(v.decoder_success for v in vectors)
    assert any(v.decoder_fail for v in vectors)
    assert any(v.iterations_used == 0 for v in vectors)
    assert any(v.iterations_used > 1 for v in vectors)


def test_decoder_vector_generation_is_deterministic(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate_vectors(first)
    generate_vectors(second)

    for path in sorted(first.iterdir()):
        assert path.read_text() == (second / path.name).read_text()

