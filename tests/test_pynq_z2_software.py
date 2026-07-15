import numpy as np
import pytest

from software.pynq_z2.ccsds_ldpc_pynq import (
    INPUT_WORDS,
    K_BITS,
    MAGIC,
    OUTPUT_WORDS,
    TX_N,
    format_dma_status,
    pack_decoded_bits_to_words,
    pack_llrs_to_words,
    unpack_response_words,
)


def test_pack_llrs_to_words_uses_little_byte_lanes():
    llr = np.zeros(TX_N, dtype=np.int16)
    llr[:4] = [-128, -1, 0, 127]

    words = pack_llrs_to_words(llr)

    assert words.dtype == np.dtype("<u4")
    assert words.shape == (INPUT_WORDS,)
    assert int(words[0]) == 0x7F00FF80


def test_pack_llrs_to_words_rejects_out_of_range_values():
    llr = np.zeros(TX_N, dtype=np.int16)
    llr[0] = 128

    with pytest.raises(ValueError, match="signed int8"):
        pack_llrs_to_words(llr)


def test_response_parser_unpacks_status_and_payload_bits():
    bits = np.zeros(K_BITS, dtype=np.uint8)
    bits[[0, 31, 32, 1023]] = 1
    words = np.zeros(OUTPUT_WORDS, dtype="<u4")
    words[0] = MAGIC
    words[1] = 1
    words[2] = 1
    words[3] = 2
    words[4] = 12345
    words[5] = 0
    words[6] = 7
    words[8:] = pack_decoded_bits_to_words(bits)

    parsed = unpack_response_words(words)

    assert parsed.success == 1
    assert parsed.syndrome_pass == 1
    assert parsed.iterations == 2
    assert parsed.cycles == 12345
    assert parsed.failure == 0
    assert parsed.saturation == 7
    assert np.array_equal(parsed.decoded_bits, bits)


def test_response_parser_rejects_bad_magic():
    words = np.zeros(OUTPUT_WORDS, dtype="<u4")

    with pytest.raises(ValueError, match="bad response magic"):
        unpack_response_words(words)


def test_dma_status_formatter_decodes_channel_flags():
    assert format_dma_status(0x00001002) == "0x00001002 (idle, ioc_irq)"
    assert format_dma_status(0x00004041) == (
        "0x00004041 (halted, decode_error, error_irq)"
    )
    assert format_dma_status(None) == "unavailable"
