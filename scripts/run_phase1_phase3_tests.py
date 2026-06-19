#!/usr/bin/env python3
"""Run Phase 1/3 Python and RTL checks."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import traceback
from importlib import util
import inspect
from pathlib import Path
from types import ModuleType
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run(command: list[str]) -> int:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=ROOT, check=False)
    return completed.returncode


def _load_module(path: Path) -> ModuleType:
    spec = util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call_test(func: Callable[..., object]) -> None:
    signature = inspect.signature(func)
    if not signature.parameters:
        func()
        return
    if list(signature.parameters) == ["tmp_path"]:
        with tempfile.TemporaryDirectory() as tmp:
            func(Path(tmp))
        return
    raise RuntimeError(f"unsupported fallback test signature: {func.__name__}{signature}")


def run_python_unit_tests() -> int:
    if util.find_spec("pytest") is not None:
        return run([sys.executable, "-m", "pytest", "tests"])

    print(
        "pytest is not importable; running local assert-based fallback for tests/test_*.py",
        flush=True,
    )
    failures = 0
    count = 0
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        module = _load_module(path)
        for name in sorted(dir(module)):
            if not name.startswith("test_"):
                continue
            func = getattr(module, name)
            if not callable(func):
                continue
            count += 1
            try:
                _call_test(func)
                print(f"PASS {path.name}::{name}")
            except Exception:
                failures += 1
                print(f"FAIL {path.name}::{name}")
                traceback.print_exc()
    print(f"fallback unit test summary: {count - failures} passed, {failures} failed")
    return 0 if failures == 0 else 1


def main() -> int:
    results: list[tuple[str, int]] = []

    steps: list[tuple[str, Callable[[], int]]] = [
        ("python unit tests", run_python_unit_tests),
        ("generate vectors", lambda: run([sys.executable, "scripts/gen_vectors.py"])),
        ("generate rtl package", lambda: run([sys.executable, "scripts/gen_syndrome_rom.py"])),
    ]

    build_dir = ROOT / "sim" / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    steps.extend(
        [
            (
                "build syndrome simulation",
                lambda: run(
                    [
                        "iverilog",
                        "-g2012",
                        "-o",
                        str(build_dir / "syndrome_checker.vvp"),
                        "rtl/ar4ja_1024_pkg.sv",
                        "rtl/syndrome_checker.sv",
                        "sim/tb_syndrome_checker.sv",
                    ]
                ),
            ),
            (
                "run syndrome simulation",
                lambda: run(["vvp", str(build_dir / "syndrome_checker.vvp")]),
            ),
        ]
    )

    for name, step in steps:
        code = step()
        results.append((name, code))
        if code != 0:
            break

    print("\nPhase 1/3 summary:")
    for name, code in results:
        status = "PASS" if code == 0 else "FAIL"
        print(f"  {status:4s} {name}")

    return 0 if all(code == 0 for _, code in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
