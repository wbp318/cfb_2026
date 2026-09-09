"""Shared data loader for analysis/ Python scripts.

    from _shared.load_data import load_games, load_paper_bets
    games = load_games()        # one row per completed game w/ closing line + pre-game FPI
    bets  = load_paper_bets()   # one row per settled paper bet

Mirrors analysis/_shared/load_data.R — keep them in lockstep.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Windows console defaults to cp1252 and chokes on Δ / ≥ — same fix as cfb_edge.main().
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data.db"
BREAK_EVEN_110 = 110.0 / 210.0          # 52.38% — cover rate needed at -110

# The LAST snapshot taken for a game is the closest thing we have to the
# closing line. For backfilled games it *is* the closer (ESPN keeps
# 'current' frozen at close); for live-snapshotted games it is whatever the
# last --snapshot before kickoff captured. Pre-game FPI is stored on the same
# row. A game is "settled" when completed=1 and both scores are present —
# no other filter, so losers are never silently dropped.
_GAMES_SQL = """
WITH last AS (
    SELECT s.*, ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY taken_at DESC) AS rn
    FROM snapshots s
    WHERE home_spread IS NOT NULL AND home_fpi_margin IS NOT NULL
)
SELECT g.id AS game_id, g.date, g.name, g.neutral, g.home, g.away,
       g.home_score, g.away_score,
       last.home_spread, last.home_spread_open, last.total, last.total_open,
       last.home_ml, last.away_ml, last.home_fpi_p, last.home_fpi_margin,
       last.home_fpi, last.away_fpi
FROM games g
JOIN last ON last.game_id = g.id AND last.rn = 1
WHERE g.completed = 1 AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
"""

_BETS_SQL = """
SELECT p.id, p.game_id, g.date, p.kind, p.side, p.line, p.price, p.truth_p, p.edge,
       p.strength, p.stake, p.result, p.profit, p.backfill
FROM paper_bets p JOIN games g ON g.id = p.game_id
WHERE p.result IS NOT NULL
"""


def _connect(db_path):
    return sqlite3.connect(str(db_path))


def load_games(db_path: str | Path = DEFAULT_DB, fbs_only: bool = True) -> pd.DataFrame:
    """One row per settled game with derived margin / cover columns."""
    con = _connect(db_path)
    try:
        df = pd.read_sql_query(_GAMES_SQL, con)
    finally:
        con.close()
    if fbs_only:
        # FCS sides carry a generic FPI rating — their "edges" are noise. Same
        # rule as cfb_edge.spread_signal.
        df = df[df.home_fpi.notna() & df.away_fpi.notna()].copy()
    df["home_margin"] = df.home_score - df.away_score
    df["market_margin"] = -df.home_spread
    df["fpi_delta"] = df.home_fpi_margin - df.market_margin      # >0: FPI likes home
    df["ats_margin"] = df.home_margin - df.market_margin         # >0: home covered
    # did the side FPI leaned toward cover? 1 / 0 / NaN(push)
    signed = np.sign(df.ats_margin) * np.sign(df.fpi_delta)
    df["fpi_side_covered"] = np.where(df.ats_margin == 0, np.nan, (signed > 0).astype(float))
    df.loc[df.fpi_delta == 0, "fpi_side_covered"] = np.nan
    df["home_won"] = (df.home_margin > 0).astype(int)
    df["spread_move"] = df.home_spread_open - df.home_spread     # >0: moved toward home
    df["abs_delta"] = df.fpi_delta.abs()
    return df.reset_index(drop=True)


def load_paper_bets(db_path: str | Path = DEFAULT_DB) -> pd.DataFrame:
    con = _connect(db_path)
    try:
        df = pd.read_sql_query(_BETS_SQL, con)
    finally:
        con.close()
    df["pnl_flat"] = np.where(df.result == "W", _dec(df.price) - 1.0,
                              np.where(df.result == "L", -1.0, 0.0))
    return df


def _dec(price: pd.Series) -> pd.Series:
    p = price.astype(float)
    return np.where(p > 0, 1 + p / 100.0, 1 + 100.0 / p.abs())


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float, float]:
    """Wilson score interval (point, lo, hi). Same closed form as binom::binom.wilson."""
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, centre - half, centre + half
