"""Stdlib test runner.

NOTE: `pytest` cannot run in this repo because the required `code/` package
(entry-point contract: code/main.py) shadows Python's standard-library
`code` module, which pytest's debugging plugin imports. This runner avoids
that by never importing pdb.

Usage:
    python tests/run_tests.py
"""

from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MODULES = [
    "tests.test_phases_1_3",
    "tests.test_phases_4_7",
]


def main() -> int:
    passed = failed = errors = 0
    details: list[str] = []
    for mod_name in MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:  # noqa: BLE001
            errors += 1
            details.append(f"[IMPORT ERROR] {mod_name}\n{traceback.format_exc()}")
            continue
        for name in sorted(dir(mod)):
            if not name.startswith("test_"):
                continue
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            try:
                fn()
            except AssertionError as exc:
                failed += 1
                details.append(
                    f"[FAIL] {mod_name}.{name}\n"
                    f"    {exc}\n"
                    f"{traceback.format_exc(limit=2)}"
                )
            except Exception:  # noqa: BLE001
                errors += 1
                details.append(
                    f"[ERROR] {mod_name}.{name}\n{traceback.format_exc(limit=3)}"
                )
            else:
                passed += 1

    print(f"passed={passed} failed={failed} errors={errors}")
    for d in details:
        print(d)
    return 0 if (failed == 0 and errors == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
