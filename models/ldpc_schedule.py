"""Deterministic parallel row schedules for the fixed AR4JA decoder."""

from __future__ import annotations

from dataclasses import dataclass

from . import ar4ja_matrix as ar4ja

SUPPORTED_LANES = (1, 8, 16)
MAX_ROW_WEIGHT = 6


@dataclass(frozen=True)
class EdgeAssignment:
    valid: bool
    variable: int
    posterior_bank: int
    posterior_addr: int


@dataclass(frozen=True)
class RowAssignment:
    valid: bool
    row: int
    degree: int
    lane: int
    message_bank: int
    message_addr: int
    edges: tuple[EdgeAssignment, ...]


@dataclass(frozen=True)
class Schedule:
    lanes: int
    groups: tuple[tuple[RowAssignment, ...], ...]

    @property
    def group_count(self) -> int:
        return len(self.groups)

    @property
    def active_rows(self) -> int:
        return sum(1 for group in self.groups for row in group if row.valid)

    @property
    def bubble_slots(self) -> int:
        return self.group_count * self.lanes - self.active_rows

    @property
    def utilization(self) -> float:
        total_slots = self.group_count * self.lanes
        return self.active_rows / total_slots if total_slots else 0.0


def check_lanes(lanes: int) -> None:
    if lanes not in SUPPORTED_LANES:
        raise ValueError(f"unsupported lane count {lanes}; expected one of {SUPPORTED_LANES}")


def posterior_bank(variable: int, lanes: int) -> int:
    check_lanes(lanes)
    if variable < 0 or variable >= ar4ja.FULL_N:
        raise ValueError(f"variable index out of range: {variable}")
    return variable % lanes


def posterior_addr(variable: int, lanes: int) -> int:
    check_lanes(lanes)
    if variable < 0 or variable >= ar4ja.FULL_N:
        raise ValueError(f"variable index out of range: {variable}")
    return variable // lanes


def build_schedule(lanes: int) -> Schedule:
    """Build the deterministic conflict-free schedule.

    The CCSDS AR4JA graph for this fixed mode has a useful quasi-cyclic layout:
    consecutive row groups of size 1, 8, or 16 are variable-disjoint, and under
    the simple modulo posterior bank map they also have one access per bank for
    every active edge phase. This keeps the schedule reproducible without a
    dynamic coloring step.
    """

    check_lanes(lanes)
    if ar4ja.CHECKS % lanes:
        raise ValueError(f"CHECKS={ar4ja.CHECKS} is not divisible by lanes={lanes}")

    row_to_cols = ar4ja.row_to_cols()
    groups: list[tuple[RowAssignment, ...]] = []
    for group_idx in range(ar4ja.CHECKS // lanes):
        assignments: list[RowAssignment] = []
        for lane in range(lanes):
            row_idx = group_idx * lanes + lane
            cols = row_to_cols[row_idx]
            edges: list[EdgeAssignment] = []
            for edge_idx in range(MAX_ROW_WEIGHT):
                if edge_idx < len(cols):
                    variable = cols[edge_idx]
                    edges.append(
                        EdgeAssignment(
                            valid=True,
                            variable=variable,
                            posterior_bank=posterior_bank(variable, lanes),
                            posterior_addr=posterior_addr(variable, lanes),
                        )
                    )
                else:
                    edges.append(
                        EdgeAssignment(
                            valid=False,
                            variable=0,
                            posterior_bank=0,
                            posterior_addr=0,
                        )
                    )
            assignments.append(
                RowAssignment(
                    valid=True,
                    row=row_idx,
                    degree=len(cols),
                    lane=lane,
                    message_bank=lane,
                    message_addr=group_idx,
                    edges=tuple(edges),
                )
            )
        groups.append(tuple(assignments))

    schedule = Schedule(lanes=lanes, groups=tuple(groups))
    validate_schedule(schedule)
    return schedule


def validate_schedule(schedule: Schedule) -> None:
    check_lanes(schedule.lanes)
    lanes = schedule.lanes
    row_to_cols = ar4ja.row_to_cols()
    expected_bank_depth = ar4ja.FULL_N // lanes

    seen_rows: list[int] = []
    variable_map: dict[tuple[int, int], int] = {}
    for variable in range(ar4ja.FULL_N):
        key = (posterior_bank(variable, lanes), posterior_addr(variable, lanes))
        if key in variable_map:
            raise AssertionError(
                f"posterior bank/address collision: {key} maps to "
                f"{variable_map[key]} and {variable}"
            )
        variable_map[key] = variable
    if len(variable_map) != ar4ja.FULL_N:
        raise AssertionError("posterior bank map is not bijective")

    for group_idx, group in enumerate(schedule.groups):
        if len(group) != lanes:
            raise AssertionError(f"group {group_idx} has {len(group)} lanes, expected {lanes}")

        group_variables: set[int] = set()
        read_phase_banks: list[set[int]] = [set() for _ in range(MAX_ROW_WEIGHT)]
        write_phase_banks: list[set[int]] = [set() for _ in range(MAX_ROW_WEIGHT)]
        message_banks: set[int] = set()

        for lane, row in enumerate(group):
            if row.lane != lane:
                raise AssertionError(f"group {group_idx} lane {lane} stored as lane {row.lane}")
            if not row.valid:
                continue
            if row.row < 0 or row.row >= ar4ja.CHECKS:
                raise AssertionError(f"invalid row index {row.row}")
            if row.row in seen_rows:
                raise AssertionError(f"duplicate row {row.row}")
            seen_rows.append(row.row)
            if row.degree != len(row_to_cols[row.row]):
                raise AssertionError(f"row {row.row} degree mismatch")
            if row.degree not in (3, 6):
                raise AssertionError(f"row {row.row} has unsupported degree {row.degree}")
            if row.message_bank != lane:
                raise AssertionError(f"row {row.row} message bank {row.message_bank} != lane {lane}")
            if row.message_bank in message_banks:
                raise AssertionError(f"group {group_idx} message bank conflict {row.message_bank}")
            message_banks.add(row.message_bank)
            if row.message_addr != group_idx:
                raise AssertionError(f"row {row.row} message address mismatch")

            row_variables: set[int] = set()
            for edge_idx, edge in enumerate(row.edges):
                if edge_idx < row.degree:
                    if not edge.valid:
                        raise AssertionError(f"row {row.row} edge {edge_idx} marked inactive")
                    expected_variable = row_to_cols[row.row][edge_idx]
                    if edge.variable != expected_variable:
                        raise AssertionError(
                            f"row {row.row} edge {edge_idx} variable {edge.variable} "
                            f"!= {expected_variable}"
                        )
                    if edge.variable in row_variables:
                        raise AssertionError(f"row {row.row} duplicates variable {edge.variable}")
                    row_variables.add(edge.variable)
                    if edge.variable in group_variables:
                        raise AssertionError(
                            f"group {group_idx} variable conflict on {edge.variable}"
                        )
                    group_variables.add(edge.variable)
                    if edge.posterior_bank != posterior_bank(edge.variable, lanes):
                        raise AssertionError(f"row {row.row} edge {edge_idx} bank mismatch")
                    if edge.posterior_addr != posterior_addr(edge.variable, lanes):
                        raise AssertionError(f"row {row.row} edge {edge_idx} address mismatch")
                    if edge.posterior_addr < 0 or edge.posterior_addr >= expected_bank_depth:
                        raise AssertionError(f"row {row.row} edge {edge_idx} address out of range")
                    if edge.posterior_bank in read_phase_banks[edge_idx]:
                        raise AssertionError(
                            f"group {group_idx} edge {edge_idx} read bank conflict "
                            f"on bank {edge.posterior_bank}"
                        )
                    if edge.posterior_bank in write_phase_banks[edge_idx]:
                        raise AssertionError(
                            f"group {group_idx} edge {edge_idx} write bank conflict "
                            f"on bank {edge.posterior_bank}"
                        )
                    read_phase_banks[edge_idx].add(edge.posterior_bank)
                    write_phase_banks[edge_idx].add(edge.posterior_bank)
                else:
                    if edge.valid:
                        raise AssertionError(f"row {row.row} inactive edge {edge_idx} marked active")
                    if edge.variable != 0 or edge.posterior_bank != 0 or edge.posterior_addr != 0:
                        raise AssertionError(f"row {row.row} inactive edge {edge_idx} is not zeroed")

    expected_rows = list(range(ar4ja.CHECKS))
    if sorted(seen_rows) != expected_rows:
        missing = sorted(set(expected_rows) - set(seen_rows))
        extra = sorted(set(seen_rows) - set(expected_rows))
        raise AssertionError(f"schedule row coverage mismatch missing={missing[:8]} extra={extra[:8]}")


def schedule_report(schedule: Schedule) -> str:
    degree3 = sum(
        1
        for group in schedule.groups
        for row in group
        if row.valid and row.degree == 3
    )
    degree6 = sum(
        1
        for group in schedule.groups
        for row in group
        if row.valid and row.degree == 6
    )
    return "\n".join(
        [
            f"lanes: {schedule.lanes}",
            f"groups: {schedule.group_count}",
            f"active rows: {schedule.active_rows}",
            f"average active lanes: {schedule.active_rows / schedule.group_count:.3f}",
            f"lane utilization: {schedule.utilization * 100.0:.2f}%",
            f"bubble lane slots: {schedule.bubble_slots}",
            f"degree-3 rows: {degree3}",
            f"degree-6 rows: {degree6}",
            "groups limited by variable conflicts: 0",
            "groups limited by bank conflicts: 0",
            "row order: consecutive ascending rows, row = group * LANES + lane",
            "posterior bank map: bank = variable % LANES, address = variable / LANES",
            "check-message map: bank = lane, address = group",
            "edge ordering: authoritative row_col order is preserved",
        ]
    )
