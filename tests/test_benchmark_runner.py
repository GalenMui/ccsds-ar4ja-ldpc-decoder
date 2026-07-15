"""Tests for the frame runners, mocking the PYNQ decoder (no hardware)."""

import numpy as np

from software.pynq_z2 import channel
from software.pynq_z2.ccsds_ldpc_pynq import DecoderResponse, K_BITS
from software.pynq_z2.runner import BoardRunner, SoftwareRunner, modeled_core_cycles


def test_software_runner_decodes_noiseless_frames():
    # All-zero frame decodes in 0 iterations (matches the board's iterations=0
    # zero-noise result); a random frame needs >=1 iteration to solve the
    # punctured parity bits initialised to neutral.
    zero = channel.build_frame(index=0, seed=5, ebn0_db=None, pattern="zeros")
    rand = channel.build_frame(index=1, seed=5, ebn0_db=None, pattern="random")
    with SoftwareRunner(iterations=8, lanes=8) as runner:
        zres = runner.decode_frame(zero)
        rres = runner.decode_frame(rand)
    assert zres.source == "software-model"
    assert zres.success == 1 and zres.syndrome_pass == 1
    assert zres.iterations == 0 and zres.bit_errors == 0
    assert zres.cycles is None  # never fabricates a hardware cycle count
    assert zres.modeled_core_cycles == modeled_core_cycles(0)
    assert rres.success == 1 and rres.bit_errors == 0 and rres.frame_error is False
    assert rres.modeled_core_cycles == modeled_core_cycles(rres.iterations)


class _FakeDecoder:
    """Minimal stand-in exposing the surface BoardRunner uses."""

    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise = raise_exc

    def allocate_io_buffers(self):
        return (np.zeros(512, np.uint32), np.zeros(40, np.uint32))

    def free_io_buffers(self, a, b):
        pass

    def dma_status(self):
        return {"MM2S": 0x1002, "S2MM": 0x1002}

    def run_prepacked(self, words, in_buf, out_buf, *, timeout_s=10.0, capture_status=False):
        if self._raise is not None:
            raise self._raise
        timing = {"copy_ns": 1, "submit_ns": 2, "wait_ns": 3, "parse_ns": 4, "total_ns": 10}
        if capture_status:
            timing["dma_status"] = self.dma_status()
        return self._response, timing


def _zero_response():
    return DecoderResponse(success=1, syndrome_pass=1, iterations=0, cycles=2625,
                           failure=0, saturation=0,
                           decoded_bits=np.zeros(K_BITS, dtype=np.uint8),
                           raw_words=np.zeros(40, dtype=np.uint32))


def test_board_runner_success_path_grades_and_times():
    frame = channel.build_frame(index=3, seed=9, ebn0_db=None, pattern="zeros")
    fake = _FakeDecoder(response=_zero_response())
    with BoardRunner(fake, capture_status=True) as runner:
        res = runner.decode_frame(frame)
    assert res.source == "hardware"
    assert res.ok
    assert res.success == 1
    assert res.cycles == 2625
    assert res.bit_errors == 0  # zero payload vs zeros decoded
    assert "pack_ns" in res.timing_ns and "wait_ns" in res.timing_ns
    assert res.dma_status == {"MM2S": 0x1002, "S2MM": 0x1002}


def test_board_runner_timeout_is_reported_as_infra_failure():
    frame = channel.build_frame(index=1, seed=2, ebn0_db=None, pattern="zeros")
    fake = _FakeDecoder(raise_exc=TimeoutError("S2MM did not become idle"))
    with BoardRunner(fake) as runner:
        res = runner.decode_frame(frame)
    assert res.ok is False
    assert res.error.startswith("TimeoutError")
    assert res.dma_status is not None


def test_board_runner_generic_exception_is_captured():
    frame = channel.build_frame(index=1, seed=2, ebn0_db=None, pattern="zeros")
    fake = _FakeDecoder(raise_exc=RuntimeError("MM2S DMA error"))
    with BoardRunner(fake) as runner:
        res = runner.decode_frame(frame)
    assert res.ok is False
    assert res.error.startswith("RuntimeError")


def test_board_runner_undetected_error_detection():
    # Response claims success but decoded bits differ from the transmitted payload.
    frame = channel.build_frame(index=0, seed=1, ebn0_db=None, pattern="ones")
    wrong = DecoderResponse(success=1, syndrome_pass=1, iterations=0, cycles=2625,
                            failure=0, saturation=0,
                            decoded_bits=np.zeros(K_BITS, dtype=np.uint8),
                            raw_words=np.zeros(40, dtype=np.uint32))
    with BoardRunner(_FakeDecoder(response=wrong)) as runner:
        res = runner.decode_frame(frame)
    assert res.bit_errors == K_BITS  # all ones vs all zeros
    assert res.undetected_error is True
    assert res.frame_error is True
