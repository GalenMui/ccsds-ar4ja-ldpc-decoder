#!/usr/bin/env python3
"""Generate SystemVerilog adjacency constants for the syndrome checker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import ar4ja_matrix as ar4ja

DEFAULT_OUTPUT = Path("rtl/ar4ja_1024_pkg.sv")


def _sv_int_array(values: list[int] | tuple[int, ...]) -> str:
    return "'{" + ", ".join(str(int(value)) for value in values) + "}"


def _padded_rows(rows: tuple[tuple[int, ...], ...], width: int) -> list[list[int]]:
    padded = []
    for row in rows:
        padded.append(list(row) + [0] * (width - len(row)))
    return padded


def _row_array(rows: list[list[int]]) -> str:
    return "'{\n" + ",\n".join("        " + _sv_int_array(row) for row in rows) + "\n    }"


def _case_function(name: str, values: Sequence[int], default: int = 0) -> str:
    lines = [f"    function automatic int unsigned {name}(input int unsigned index);", "        case (index)"]
    for index, value in enumerate(values):
        lines.append(f"            {index}: {name} = {int(value)};")
    lines.extend(
        [
            f"            default: {name} = {int(default)};",
            "        endcase",
            "    endfunction",
        ]
    )
    return "\n".join(lines)


def _flat_case_function(
    name: str,
    rows: list[list[int]],
    row_width_name: str,
    default: int = 0,
) -> str:
    lines = [
        f"    function automatic int unsigned {name}(input int unsigned row_idx, input int unsigned edge_idx);",
        f"        case ((row_idx * {row_width_name}) + edge_idx)",
    ]
    flat_index = 0
    for row in rows:
        for value in row:
            lines.append(f"            {flat_index}: {name} = {int(value)};")
            flat_index += 1
    lines.extend(
        [
            f"            default: {name} = {int(default)};",
            "        endcase",
            "    endfunction",
        ]
    )
    return "\n".join(lines)


def _fast_row_weight_function() -> str:
    return """    function automatic int unsigned row_weight(input int unsigned index);
        if (index < M) begin
            row_weight = 3;
        end else begin
            row_weight = 6;
        end
    endfunction"""


def _fast_row_col_function() -> str:
    phi_lines: list[str] = []
    for pi_index in range(1, 9):
        for quarter_index in range(4):
            key = (pi_index - 1) * 4 + quarter_index
            phi_lines.append(
                f"            {key}: phi512 = {ar4ja.phi(pi_index, quarter_index)};"
            )
    theta_lines = [
        f"            {pi_index}: theta_value = {ar4ja.theta(pi_index)};"
        for pi_index in range(1, 9)
    ]
    phi_body = "\n".join(phi_lines)
    theta_body = "\n".join(theta_lines)
    return f"""    function automatic int unsigned theta_value(input int unsigned pi_index);
        case (pi_index)
{theta_body}
            default: theta_value = 0;
        endcase
    endfunction

    function automatic int unsigned phi512(input int unsigned pi_index, input int unsigned quarter_index);
        case (((pi_index - 1) * 4) + quarter_index)
{phi_body}
            default: phi512 = 0;
        endcase
    endfunction

    function automatic int unsigned perm_col(input int unsigned pi_index, input int unsigned i);
        int unsigned quarter_index;
        quarter_index = (4 * i) / M;
        perm_col = (M / 4) * ((theta_value(pi_index) + quarter_index) % 4);
        perm_col = perm_col + ((phi512(pi_index, quarter_index) + i) % (M / 4));
    endfunction

    function automatic int unsigned min2(input int unsigned a, input int unsigned b);
        min2 = (a < b) ? a : b;
    endfunction

    function automatic int unsigned max2(input int unsigned a, input int unsigned b);
        max2 = (a > b) ? a : b;
    endfunction

    function automatic int unsigned min3(input int unsigned a, input int unsigned b, input int unsigned c);
        min3 = min2(min2(a, b), c);
    endfunction

    function automatic int unsigned max3(input int unsigned a, input int unsigned b, input int unsigned c);
        max3 = max2(max2(a, b), c);
    endfunction

    function automatic int unsigned mid3(input int unsigned a, input int unsigned b, input int unsigned c);
        mid3 = a ^ b ^ c ^ min3(a, b, c) ^ max3(a, b, c);
    endfunction

    function automatic int unsigned row_col(input int unsigned row_idx, input int unsigned edge_idx);
        int unsigned i;
        int unsigned a;
        int unsigned b;
        int unsigned c;
        int unsigned d;
        int unsigned e;
        int unsigned f;

        if (row_idx < M) begin
            i = row_idx;
            a = 2 * M + i;
            b = 4 * M + i;
            c = 4 * M + perm_col(1, i);
            case (edge_idx)
                0: row_col = a;
                1: row_col = min2(b, c);
                2: row_col = max2(b, c);
                default: row_col = 0;
            endcase
        end else if (row_idx < 2 * M) begin
            i = row_idx - M;
            a = i;
            b = M + i;
            c = 3 * M + i;
            d = 4 * M + perm_col(2, i);
            e = 4 * M + perm_col(3, i);
            f = 4 * M + perm_col(4, i);
            case (edge_idx)
                0: row_col = a;
                1: row_col = b;
                2: row_col = c;
                3: row_col = min3(d, e, f);
                4: row_col = mid3(d, e, f);
                5: row_col = max3(d, e, f);
                default: row_col = 0;
            endcase
        end else begin
            i = row_idx - 2 * M;
            a = i;
            b = M + perm_col(5, i);
            c = M + perm_col(6, i);
            d = 3 * M + perm_col(7, i);
            e = 3 * M + perm_col(8, i);
            f = 4 * M + i;
            case (edge_idx)
                0: row_col = a;
                1: row_col = min2(b, c);
                2: row_col = max2(b, c);
                3: row_col = min2(d, e);
                4: row_col = max2(d, e);
                5: row_col = f;
                default: row_col = 0;
            endcase
        end
    endfunction"""


def _puncture_rows() -> tuple[tuple[int, ...], ...]:
    h = ar4ja.build_h_full_sparse()
    rows = []
    for i in range(ar4ja.M):
        row = 2 * ar4ja.M + i
        rows.append(tuple(col for col in h.row_to_cols[row] if col < ar4ja.TX_N))
    return tuple(rows)


def generate_package(output: Path = DEFAULT_OUTPUT) -> Path:
    h = ar4ja.build_h_full_sparse()
    row_weights = tuple(len(row) for row in h.row_to_cols)
    max_row_weight = max(row_weights)
    row_cols = _padded_rows(h.row_to_cols, max_row_weight)
    col_rows_raw = h.col_to_rows
    col_weights = tuple(len(col_rows) for col_rows in col_rows_raw)
    max_col_weight = max(col_weights)

    row_edge_index: dict[tuple[int, int], int] = {}
    for row_idx, cols in enumerate(h.row_to_cols):
        for edge_idx, col_idx in enumerate(cols):
            row_edge_index[(row_idx, col_idx)] = edge_idx

    col_rows = _padded_rows(col_rows_raw, max_col_weight)
    col_row_edges = _padded_rows(
        tuple(
            tuple(row_edge_index[(row_idx, col_idx)] for row_idx in col_rows_for_col)
            for col_idx, col_rows_for_col in enumerate(col_rows_raw)
        ),
        max_col_weight,
    )

    puncture_rows = _puncture_rows()
    puncture_weights = tuple(len(row) for row in puncture_rows)
    max_puncture_weight = max(puncture_weights)
    puncture_cols = _padded_rows(puncture_rows, max_puncture_weight)

    output.parent.mkdir(parents=True, exist_ok=True)
    row_weight_fn = _fast_row_weight_function()
    row_col_fn = _fast_row_col_function()
    col_weight_fn = _case_function("col_weight", col_weights)
    col_row_fn = _flat_case_function("col_row", col_rows, "MAX_COL_WEIGHT")
    col_row_edge_fn = _flat_case_function(
        "col_row_edge", col_row_edges, "MAX_COL_WEIGHT"
    )
    puncture_weight_fn = _case_function("puncture_weight", puncture_weights)
    puncture_col_fn = _flat_case_function(
        "puncture_col", puncture_cols, "MAX_PUNCTURE_WEIGHT"
    )

    text = f"""// Generated by scripts/gen_syndrome_rom.py. Do not edit by hand.
package ar4ja_1024_pkg;
    localparam int K = {ar4ja.K};
    localparam int M = {ar4ja.M};
    localparam int INFO_N = {ar4ja.INFO_N};
    localparam int TX_N = {ar4ja.TX_N};
    localparam int FULL_N = {ar4ja.FULL_N};
    localparam int CHECKS = {ar4ja.CHECKS};
    localparam int PUNCTURED_N = {ar4ja.PUNCTURED_N};
    localparam int MAX_ROW_WEIGHT = {max_row_weight};
    localparam int MAX_COL_WEIGHT = {max_col_weight};
    localparam int MAX_PUNCTURE_WEIGHT = {max_puncture_weight};

{row_weight_fn}

{row_col_fn}

{col_weight_fn}

{col_row_fn}

{col_row_edge_fn}

{puncture_weight_fn}

{puncture_col_fn}
endpackage
"""
    output.write_text(text, encoding="ascii")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    path = generate_package(args.output)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
