"""Flat-bet ROI of the paper ledger by signal kind x strength, with bootstrap 95% CIs.

Strategy under test: every play cfb_edge.py flagged (strength >= 1) is bet flat $1
at the logged price. PnL = decimal-1 if W, -1 if L, 0 push. This is the CFB
twin of horses/analysis/01_per_track_roi_ci.

Output: analysis/_out/paper_roi.csv + console table sorted by lower CI.
Mirrors paper_roi.R — keep them in lockstep. Point estimates must match exactly;
bootstrap CIs may differ in the last digit (different RNG streams).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.load_data import load_paper_bets  # noqa: E402

MIN_BETS = 10
BOOT_REPS = 5000
SEED = 20260909
OUT_DIR = Path(__file__).resolve().parents[1] / "_out"
OUT_CSV = OUT_DIR / "paper_roi.csv"


def verdict(lo: float, hi: float) -> str:
    if lo > 0:
        return "PROFITABLE (95% CI > 0)"
    if hi < 0:
        return "losing (95% CI < 0)"
    return "inconclusive"


def boot_ci(x: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    idx = rng.integers(0, len(x), size=(BOOT_REPS, len(x)))
    means = x[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    rng = np.random.default_rng(SEED)
    bets = load_paper_bets()
    if bets.empty:
        print("no settled paper bets yet — run cfb_edge.py --snapshot / --settle (or --backfill)")
        return
    print(f"Settled paper bets: {len(bets):,}   |   backfilled: {int(bets["backfill"].sum()):,}   |   "
          f"Overall flat ROI: {100 * bets.pnl_flat.mean():+.1f}%   |   Bootstrap reps: {BOOT_REPS:,}\n")

    rows = []
    groups = [("ALL", "all", bets)]
    groups += [(k, str(s), g) for (k, s), g in bets.groupby(["kind", "strength"])]
    groups += [(k, "any", g) for k, g in bets.groupby("kind")]
    for kind, strength, g in groups:
        if len(g) < MIN_BETS:
            continue
        lo, hi = boot_ci(g.pnl_flat.to_numpy(), rng)
        rows.append({"kind": kind, "strength": strength, "bets": len(g),
                     "wins": int((g.result == "W").sum()), "hit_rate": (g.result == "W").mean(),
                     "roi_mean": g.pnl_flat.mean(), "roi_ci_lo": lo, "roi_ci_hi": hi,
                     "verdict": verdict(lo, hi)})
    out = pd.DataFrame(rows).sort_values("roi_ci_lo", ascending=False)
    out.to_csv(OUT_CSV, index=False)
    print(f"{'kind':<8}{'str':>5}{'bets':>6}{'wins':>6}{'hit%':>7}{'ROI':>8}{'CI lo':>8}{'CI hi':>8}  verdict")
    for r in out.itertuples():
        print(f"{r.kind:<8}{r.strength:>5}{r.bets:>6}{r.wins:>6}{100*r.hit_rate:>6.1f}%"
              f"{100*r.roi_mean:>+7.1f}%{100*r.roi_ci_lo:>+7.1f}%{100*r.roi_ci_hi:>+7.1f}%  {r.verdict}")
    print(f"\nwrote {OUT_CSV}")


if __name__ == "__main__":
    main()
