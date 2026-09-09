"""Is ESPN FPI worth anything against the DraftKings closer?

Three questions, all on EVERY settled FBS-vs-FBS game (not just flagged ones):
  A. Calibration — binned FPI home win prob vs observed home win rate (Wilson CI).
  B. Accuracy — RMSE of actual margin vs FPI margin, vs the closing spread, vs a
     50/50 blend. If the closer's RMSE is lower, the market is the better model.
  C. ATS — when FPI and the closer disagree by |delta| pts, how often does the
     FPI side cover? Compare to the 52.4% break-even at -110.

Output: analysis/_out/fpi_calibration.csv, fpi_ats_by_delta.csv.
Mirrors fpi_calibration.R — keep them in lockstep.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.load_data import BREAK_EVEN_110, load_games, wilson  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "_out"
PROB_BINS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0001]
DELTA_BINS = [0.0, 3.0, 5.0, 8.0, 99.0]
DELTA_LABELS = ["0-3", "3-5", "5-8", "8+"]


def rmse(a: pd.Series, b: pd.Series) -> float:
    return float(np.sqrt(((a - b) ** 2).mean()))


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    g = load_games()
    if g.empty:
        print("no settled games yet — run cfb_edge.py --backfill --date <past saturday>")
        return
    print(f"Settled FBS-vs-FBS games with closer + FPI: {len(g):,}\n")

    # A. calibration
    print("A. FPI home win-prob calibration (Wilson 95% CI)")
    g["pbin"] = pd.cut(g.home_fpi_p, PROB_BINS, right=False)
    rows = []
    for b, grp in g.groupby("pbin", observed=True):
        p, lo, hi = wilson(int(grp.home_won.sum()), len(grp))
        rows.append({"bin": str(b), "n": len(grp), "pred_mean": grp.home_fpi_p.mean(),
                     "obs_rate": p, "obs_lo": lo, "obs_hi": hi})
        print(f"  {str(b):<12} n={len(grp):>4}  pred {100*grp.home_fpi_p.mean():5.1f}%  "
              f"obs {100*p:5.1f}% [{100*lo:5.1f},{100*hi:5.1f}]  Δ{100*(p-grp.home_fpi_p.mean()):+5.1f}pp")
    pd.DataFrame(rows).to_csv(OUT_DIR / "fpi_calibration.csv", index=False)

    # B. accuracy
    blend = 0.5 * g.home_fpi_margin + 0.5 * g.market_margin
    r_fpi, r_mkt, r_blend = rmse(g.home_margin, g.home_fpi_margin), rmse(g.home_margin, g.market_margin), rmse(g.home_margin, blend)
    print("\nB. Margin accuracy (RMSE, lower is better)")
    print(f"  FPI margin   {r_fpi:6.2f}\n  DK closer    {r_mkt:6.2f}\n  50/50 blend  {r_blend:6.2f}")
    print(f"  verdict: {'FPI beats the closer' if r_fpi < r_mkt else 'the closer beats FPI'} "
          f"by {abs(r_fpi - r_mkt):.2f} pts RMSE (MARGIN_SD in cfb_edge.py assumes ~13.5)")

    # C. ATS by |delta|
    print(f"\nC. FPI-side cover rate by |FPI − closer| (break-even at -110 = {100*BREAK_EVEN_110:.1f}%)")
    d = g[g.fpi_side_covered.notna()].copy()
    d["dbin"] = pd.cut(d.abs_delta, DELTA_BINS, labels=DELTA_LABELS, right=False)
    rows = []
    for b, grp in d.groupby("dbin", observed=True):
        p, lo, hi = wilson(int(grp.fpi_side_covered.sum()), len(grp))
        verdict = "PROFITABLE (CI lo > BE)" if lo > BREAK_EVEN_110 else "losing (CI hi < BE)" if hi < BREAK_EVEN_110 else "inconclusive"
        rows.append({"delta_bin": b, "n": len(grp), "covers": int(grp.fpi_side_covered.sum()),
                     "cover_rate": p, "ci_lo": lo, "ci_hi": hi, "verdict": verdict})
        print(f"  Δ{b:<5} n={len(grp):>4}  cover {100*p:5.1f}% [{100*lo:5.1f},{100*hi:5.1f}]  {verdict}")
    p, lo, hi = wilson(int(d.fpi_side_covered.sum()), len(d))
    print(f"  ALL    n={len(d):>4}  cover {100*p:5.1f}% [{100*lo:5.1f},{100*hi:5.1f}]")
    pd.DataFrame(rows).to_csv(OUT_DIR / "fpi_ats_by_delta.csv", index=False)
    print(f"\nwrote {OUT_DIR / 'fpi_calibration.csv'}, {OUT_DIR / 'fpi_ats_by_delta.csv'}")


if __name__ == "__main__":
    main()
