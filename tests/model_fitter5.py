"""Round-5 ratio probe: scalar-multiplier models on total outflow.

Models (all GENERAL):
  A  safe = naive - m * E           E in {meanTot, medTot, recent3, meanVar, medVar, out30}
     solve per-sample m* = (naive - exp) / E; look for clustering.
  B  safe = p * naive               p* = exp / naive; clustering?
  C  safe = naive - m * E - s * S   S = monthly salary; 2-D grid.

If m* (or p*) clusters tightly across the 21 uncapped samples, that is a
general law. If it scatters, the scalar-ratio class is falsified too.

Run:  python tests/model_fitter5.py
"""
from __future__ import annotations

import statistics
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from model_fitter4 import build_context, FIXED_CATS

GX = 1e-9  # tolerance when comparing ratios


def outflow_30d(ctx) -> float:
    """Signed scheduled+pending outflow within next 30 days (positive = out)."""
    end = ctx["start"] + timedelta(days=30)
    tot = 0.0
    for d, a in ctx["sched"]:
        if d <= end and a < 0:
            tot += -a
    return tot


def main() -> None:
    ctxs = build_context()
    rows = []
    for ctx in ctxs:
        naive = ctx["bal"] - ctx["keep"]
        exp = ctx["exp"]
        fixed_tot = [c["mean"] for c in ctx["cats"].values() if c["strength"] == "fixed"]
        var_tot = [c["mean"] for c in ctx["cats"].values() if c["strength"] != "fixed"]
        all_mean = sum(c["mean"] for c in ctx["cats"].values())
        all_med = sum(c["med"] for c in ctx["cats"].values())
        rec3 = sum(c["recent3"] for c in ctx["cats"].values())
        sal = ctx["sal"]["monthly_amount"] if ctx["sal"] else 0.0
        E = {
            "meanTot": all_mean,
            "medTot": all_med,
            "recent3": rec3,
            "meanFixed": sum(fixed_tot),
            "meanVar": sum(var_tot),
            "out30": outflow_30d(ctx),
        }
        row = {"rid": ctx["rid"], "naive": naive, "exp": exp, "sal": sal, "E": E}
        rows.append(row)

    print("A) solved multiplier m* = (naive - exp) / E  per sample:")
    for name in ("meanTot", "medTot", "recent3", "meanFixed", "meanVar", "out30"):
        ms = []
        for r in rows:
            e = r["E"][name]
            if e > GX:
                ms.append((r["rid"], (r["naive"] - r["exp"]) / e))
        vals = [m for _, m in ms]
        spread = (max(vals) - min(vals)) if vals else 0.0
        print(f"  {name:10s} m* range=[{min(vals):8.3f},{max(vals):8.3f}] "
              f"spread={spread:9.3f} med={statistics.median(vals):8.3f}")
        for rid, m in ms[:25]:
            print(f"      {rid}: m*={m:9.4f}")

    print("\nB) p* = exp / naive:")
    ps = [(r["rid"], r["exp"] / r["naive"]) for r in rows if r["naive"] > GX]
    vals = [p for _, p in ps]
    print(f"  p* range=[{min(vals):.4f},{max(vals):.4f}] spread={max(vals)-min(vals):.4f} "
          f"med={statistics.median(vals):.4f}")

    print("\nC) 2-D grid best (m, s) for safe = naive - m*E - s*salary "
          "(meanTot / medTot / recent3):")
    for name in ("meanTot", "medTot", "recent3"):
        best = None
        for mi in range(0, 41):
            m = mi * 0.1
            for si in range(0, 21):
                s = si * 0.1
                err = sum(abs((r["naive"] - m * r["E"][name] - s * r["sal"]) - r["exp"])
                          for r in rows)
                if best is None or err < best[0]:
                    best = (err, m, s)
        print(f"  {name:10s} best SAE={best[0]:14.2f} at m={best[1]:.1f} s={best[2]:.1f}")

    with open(Path(__file__).parent / "model_fitter5_out.txt", "w") as f:
        for name in ("meanTot", "medTot", "recent3", "meanFixed", "meanVar", "out30"):
            for r in rows:
                e = r["E"][name]
                if e > GX:
                    f.write(f"{name} {r['rid']} m*={(r['naive']-r['exp'])/e:.6f}\n")


if __name__ == "__main__":
    main()
