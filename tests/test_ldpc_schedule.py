from pathlib import Path

import pytest

from models import ar4ja_matrix as ar4ja
from models.ldpc_schedule import SUPPORTED_LANES, build_schedule, schedule_report
from scripts.gen_parallel_schedule import generate_reports, generate_sv_package


def test_supported_schedules_validate_all_invariants():
    for lanes in SUPPORTED_LANES:
        schedule = build_schedule(lanes)
        assert schedule.group_count == ar4ja.CHECKS // lanes
        assert schedule.active_rows == ar4ja.CHECKS
        assert schedule.bubble_slots == 0
        assert schedule.utilization == 1.0


def test_schedule_is_deterministic():
    first = build_schedule(8)
    second = build_schedule(8)
    assert first == second
    assert schedule_report(first) == schedule_report(second)


def test_unsupported_lane_count_rejected():
    with pytest.raises(ValueError):
        build_schedule(4)


def test_schedule_generation_outputs_reports(tmp_path: Path):
    sv_path = generate_sv_package(tmp_path / "ldpc_schedule_pkg.sv")
    report_paths = generate_reports(tmp_path / "schedule")

    sv_text = sv_path.read_text(encoding="ascii")
    assert "schedule_group_count" in sv_text
    assert "1, 8, 16" in sv_text
    assert len(report_paths) == len(SUPPORTED_LANES)
    for path in report_paths:
        text = path.read_text(encoding="ascii")
        assert "lane utilization: 100.00%" in text
        assert "edge ordering: authoritative row_col order is preserved" in text
