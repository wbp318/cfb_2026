"""Does open->close line movement predict the cover?

Two questions on every settled FBS-vs-FBS game with an opener:
  A. Steam — when the spread moved >= STEAM_PTS, does the side the market moved
     TOWARD cover more than 52.4%? ("follow the money")
  B. Interaction — when FPI and the move agree ("steam with") vs disagree
     ("steam against"), how often does the FPI side cover? This is the
     evidence behind the ⚠market-moved-against demotion in cfb_edge.py.

Output: analysis/_out/line_move.csv.  Mirrors line_move.R — keep in lockstep.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.load_data import BREAK_EVEN_110, load_games, wilson  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "_out"
STEAM_PTS = 1.5


def line(label: str, k: int, n: int) -> dict:
    p, lo, hi = wilson(k, n)
    v = "PROFITABLE (CI lo > BE)" if lo > BREAK_EVEN_110 else "losing (CI hi < BE)" if hi < BREAK_EVEN_110 else "inconclusive"
    print(f"  {label:<34} n={n:>4}  cover {100*p:5.1f}% [{100*lo:5.1f},{100*hi:5.1f}]  {v}")
    return {"group": label, "n": n, "covers": k, "cover_rate": p, "ci_lo": lo, "ci_hi": hi, "verdict": v}


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    g = load_games()
    g = g[g.spread_move.notna() & (g.ats_margin != 0)].copy()
    if g.empty:
        print("no settled games with an opener yet")
        return
    moved = g[g.spread_move.abs() >= STEAM_PTS].copy()
    print(f"Settled games with opener: {len(g):,}   |   moved ≥{STEAM_PTS} pts: {len(moved):,}   "
          f"|   break-even {100*BREAK_EVEN_110:.1f}%\n")
    rows = []
    print("A. Follow-the-money: did the side the line moved toward cover?")
    moved["toward_covered"] = (np.sign(moved.ats_margin) == np.sign(moved.spread_move)).astype(int)
    rows.append(line("moved-toward side", int(moved.toward_covered.sum()), len(moved)))
    big = moved[moved.spread_move.abs() >= 3.0]
    rows.append(line("moved-toward side (≥3 pts)", int(big.toward_covered.sum()), len(big)))

    print("\nB. FPI side vs steam direction")
    d = moved[moved.fpi_side_covered.notna() & (moved.fpi_delta != 0)].copy()
    d["with"] = np.sign(d.spread_move) == np.sign(d.fpi_delta)
    for flag, label in ((True, "FPI side, steam WITH"), (False, "FPI side, steam AGAINST")):
        sub = d[d["with"] == flag]
        rows.append(line(label, int(sub.fpi_side_covered.sum()), len(sub)))
    still = g[(g.spread_move.abs() < STEAM_PTS) & g.fpi_side_covered.notna()]
    rows.append(line("FPI side, no steam", int(still.fpi_side_covered.sum()), len(still)))
    pd.DataFrame(rows).to_csv(OUT_DIR / "line_move.csv", index=False)
    print(f"\nwrote {OUT_DIR / 'line_move.csv'}")


if __name__ == "__main__":
    main()
