# Betting Guide

Live-play reference for `cfb_edge.py`. Read before firing on any game. Companion docs:
`README.md` (install, diagrams, honest expectations), `CLAUDE.md` (conventions).

## 1. The signals — trust ladder

| # | Signal | Compares | Fires | Trust |
|---|---|---|---|---|
| 1 | **ATS** | FPI predicted margin vs DK spread | Δ ≥ 3 (lean) / ≥ 5 (STRONG) | primary |
| 2 | **ML** | FPI win prob vs de-vigged DK moneyline | +8% (value) / +20% (STRONG) | primary when the spread is tiny or the dog is live |
| 3 | **line move** | DK opener vs current | ≥ 3 pts | information only — the market learned something |
| 4 | **total steam** | DK total opener vs current | ≥ 2.5 pts | information only — no totals model |

FPI is a real model with a public track record. The market is also a model, with money
behind it. When they disagree by a lot, one of them is wrong, and the analysis loop is how
we learn which one more often.

## 2. What to fire on

The textbook play has **three confirmations**:

1. **STRONG ATS** (Δ ≥ 5) on an FBS-vs-FBS game.
2. **[steam with]** — the line has already moved ≥ 1.5 pts toward the FPI side. The market
   is drifting toward the model, not away.
3. **The same game also shows ML value** on the same side, or Δ crosses a key number
   (3 or 7) in your favor.

Saturday 2026-09-12 examples of that shape: Syracuse −3.5 vs Cal (Δ 8.1, steam with,
crosses 7 & 10, plus STRONG ML), Middle Tennessee +13.5 at Marshall (Δ 9.3, steam with,
crosses 7 & 10).

## 3. What to skip

- **⚠market-moved-against** — the line moved ≥ 1.5 pts *away* from FPI. Somebody knows
  something FPI doesn't (QB out, weather, suspension). Skip unless you know the reason and
  disagree with it.
- **FCS opponents** — never ranked, never staked, ATS *or* ML. FPI's FCS rating is generic.
- **⚠blowout-number** — spreads of 28+ are about garbage time, not team strength.
- **⚠long-dog** — ML dogs beyond +250 are capped at "value"; beyond +400 never staked.
  Variance eats small bankrolls.
- **Totals** — we have no model. Steam on a total is a reason to look at the weather, not
  to bet.

## 4. Sizing

- `$Bet` = quarter-Kelly on the model's probability, **capped at 5% of bankroll**, $1 min.
  It is a ceiling, not a target.
- 3–5 tickets per Saturday. More than that and you're betting the noise.
- Default bankroll in the tool is $100; pass `--bankroll` for yours.
- Log every real ticket with `--bet` the moment you place it. Run `--settle` Sunday.

## 5. Discipline — the horses lessons carry over

- **No signal has beaten a market until the backtest says so** with a confidence interval
  that clears zero. Everything today is *inconclusive* on 51 games.
- **The losers count.** The analysis "settled" rule is completed game + both scores.
  Nothing filters on a result column that could hide losses.
- **Re-run the loop weekly**, both runtimes, before changing a threshold.
- Take the closing-line-value view seriously: if the plays we flag Thursday consistently
  close *further* from FPI on Saturday, the market disagrees with us and it is usually right.
