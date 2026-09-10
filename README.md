# cfb_2026

> College football outlier finder. One file (`cfb_edge.py`), no API keys. Compares the
> **DraftKings** line (via ESPN) against **ESPN FPI's** game projection for every game on the
> Saturday slate, flags where the model and the market disagree, tracks open→current line
> movement, sizes quarter-Kelly tickets, and writes everything to SQLite so the edge (if
> any) can be **backtested honestly** in Python *and* R.
>
> Sister project of [`horses_worldwide`](../horses_worldwide). Same philosophy: it reads
> public data and produces recommendations. **It does not place bets** — you place them
> yourself, and you log them here so the ledger tells you the truth.

---

## Before you bet — honest expectations (read this first)

**Nothing in this tool is proven +EV yet.** As of 2026‑09‑09 the backfilled sample is
51 FBS‑vs‑FBS games (weeks 0–1). Every verdict is *inconclusive*:

| Question (analysis/ script) | Answer so far (n=51 games / 34 paper bets) |
|---|---|
| Does the paper ledger make money? (`01`) | Flat ROI **−2.1%**, 95% CI [−40%, +41%] — inconclusive |
| Is FPI more accurate than the closer? (`02`) | RMSE **16.41 (FPI) vs 16.68 (DK)** — FPI ahead by 0.27 pts, well inside noise |
| Does the FPI side cover? (`02`) | **53.1%** [39, 66] vs 52.4% break‑even — inconclusive |
| Does following steam work? (`03`) | Moved‑toward side covers **43.5%** [26, 63] — inconclusive |

FPI is a real model and public lines are efficient. The realistic prior for "public power
rating vs closing line" is 50–53% ATS, which at −110 is a coin flip. Treat the first
month as **data collection**: small flat‑ish tickets, log everything, let the analysis
loop decide whether any bucket earns a bigger stake.

---

## Quick start

```powershell
pip install -r requirements.txt

python cfb_edge.py                       # full Saturday board + top-10 outliers
python cfb_edge.py --top 15              # ranked outliers only
python cfb_edge.py --flagged             # board rows that carry a tag
python cfb_edge.py --bankroll 250        # resize the $Bet column
python cfb_edge.py --snapshot --report   # persist lines + FPI, paper-log plays, write reports/saturday-<date>.md
python cfb_edge.py --date 2026-09-19     # any date (default: next Saturday)
```

Sunday morning:

```powershell
python cfb_edge.py --settle              # pull finals, grade paper bets + bets.csv
python cfb_edge.py --paper-show          # paper ledger by signal kind × strength
python cfb_edge.py --bets-show           # your real-money ledger with running ROI
```

Log a real ticket the moment you place it (game id is in the `--report` table or `data.db`):

```powershell
python cfb_edge.py --bet 401856782 --kind spread --side "Oklahoma State" --line 22.5 --price -110 --stake 5
python cfb_edge.py --bet 401856782 --kind ml --side Oregon --price -1800 --stake 10
python cfb_edge.py --bet 401856782 --kind under --line 57.5 --price -108 --stake 5
```

Seed the database with past weeks (ESPN keeps the opener, the closer and the pre‑game FPI
for finished games):

```powershell
python cfb_edge.py --date 2026-09-05 --backfill
```

### Setting up a fresh Windows machine

Everything is PowerShell. Verify each step before the next.

```powershell
winget install Python.Python.3.13          # then close + reopen PowerShell
python --version                           # expect 3.12 or newer (CI tests 3.12 and 3.13)

winget install RProject.R                  # optional: only needed for the R half of the analysis loop
# then put C:\Program Files\R\R-4.4.2\bin on the PATH — see "Getting Rscript on the PATH" below

winget install Git.Git GitHub.cli          # optional: gh is only for CI/branch-protection admin
git clone https://github.com/wbp318/cfb_2026.git
cd cfb_2026
pip install -r requirements.txt            # runtime: just `requests`
pip install -r analysis/requirements-py.txt -r requirements-dev.txt   # pandas/numpy + ruff/pytest
python cfb_edge.py --top 10                # first live run — should print next Saturday's outliers
python -m pytest -q tests                  # 35 passed
```

No API keys, no `.env`, nothing to sign up for. If the first live run prints a 403, read
the User‑Agent note under *Data sources and gotchas*.

### Every flag

| Flag | Does | Touches network? | Writes? |
|---|---|---|---|
| *(none)* | full board for next Saturday + top‑10 ranker | yes | no |
| `--date YYYY-MM-DD` | any date instead of next Saturday (weeknight games work too) | yes | no |
| `--top N` | ranked outliers only, N rows | yes | no |
| `--flagged` | board rows that carry at least one tag | yes | no |
| `--bankroll X` | bankroll for the `$Bet` column (default 100) | — | no |
| `--no-color` | plain text (auto when piped) | — | no |
| `--snapshot` | persist games + lines + FPI to `data.db`; paper‑log every strength ≥ 1 play | yes | `data.db` |
| `--report` | also write `reports/saturday-<date>.md` (implies a snapshot of lines) | yes | `data.db`, `reports/` |
| `--backfill` | with a **past** `--date`: snapshot closers + pre‑game FPI, paper‑log with `backfill=1`, then settle | yes | `data.db` |
| `--settle` | refresh scores, grade `paper_bets` and `bets.csv`, print the paper summary | yes | `data.db`, `bets.csv` |
| `--paper-show` | paper ledger by kind × strength | no | no |
| `--bets-show` | real‑money ledger with running P&L and ROI | no | no |
| `--bet ID --kind K --side S --line L --price P --stake $ [--note …]` | append one real ticket to `bets.csv` | yes (to find the game) | `bets.csv` |
| `--db PATH` | use another SQLite file (CI uses a scratch one) | — | — |

`--bet` rules: `--kind` is `spread`, `ml`, `over` or `under`. `--side` must be the team's
display name (`"Oklahoma State"`), its ESPN abbreviation is **not** enough for settlement, and
for `over`/`under` it is ignored. `--line` is the number *you got* from the side's point of view
(`+22.5` for the dog, `-22.5` for the favorite, `57.5` for a total); `--price` defaults to −110.

---

## The full picture

Six moving parts. One of them talks to the internet (`cfb_edge.py`), one holds the truth
(`data.db`), and everything else exists to check that the first one is not fooling you.

```mermaid
flowchart TB
    subgraph LIVE["1 · Saturday tool — cfb_edge.py (the only thing that touches the internet)"]
        direction LR
        ESPN(("ESPN\nscoreboard · odds\npredictor · powerindex")) --> FETCH["fetch + enrich\n→ list[Game]"]
        FETCH --> SIG["signals\nATS · ML · line move · total move"]
        SIG --> OUT["terminal board\n--top ranker\nreports/saturday-DATE.md"]
    end

    subgraph STORE["2 · Storage (local only, gitignored)"]
        DB[("data.db\ngames · snapshots · paper_bets")]
        CSV[("bets.csv\nreal tickets you placed")]
    end

    subgraph CHECK["3 · Analysis loop — analysis/ (offline, read-only, Python AND R)"]
        direction LR
        L["_shared/load_data\n.py ⇄ .R"] --> A1["01 paper ROI\nbootstrap CI"]
        L --> A2["02 FPI calibration\nRMSE vs closer · cover % by Δ"]
        L --> A3["03 line move\nfollow-the-money"]
        A1 & A2 & A3 --> AGREE{"Python == R?"}
    end

    subgraph GUARD["4 · Guard rails (no internet, no real data)"]
        direction LR
        T["tests/\npytest · 35 cases\nodds math · signals · grading · SQLite"]
        CI["GitHub Actions\npy 3.12 + 3.13 · R 4.4\nlint · tests · empty-DB runs"]
    end

    subgraph SCHED["5 · Unattended"]
        BAT["snapshot.bat\nTask Scheduler, Fri/Sat every 2–4 h"]
    end

    subgraph DOCS["6 · Docs + constants"]
        K["constants block in cfb_edge.py\nSPREAD_OUTLIER_PTS · MARGIN_SD · STEAM_PTS …\nFINDINGS_AS_OF"]
        R["README 'Before you bet' table\nbetting_guide.md"]
    end

    SIG -->|"--snapshot / --backfill\nlines + FPI + flagged plays"| DB
    OUT -->|"--bet (you type it)"| CSV
    ESPN -->|"--settle: final scores"| DB
    DB -->|"--settle grades"| CSV
    BAT -->|runs --snapshot| LIVE
    DB --> L
    AGREE -- yes --> K
    AGREE -- no --> BUG["fix the wrong runtime"]
    K -.->|thresholds| SIG
    K --> R
    T -.->|"imports and exercises"| LIVE
    CI -.->|"runs on every push"| T
    CI -.->|"runs on every push"| CHECK
```

**How to read it.** Saturday morning the tool pulls ESPN, scores every game with the four
signals, prints the board, and (with `--snapshot`) writes the lines, the FPI numbers and
every flagged play into `data.db`. You place tickets by hand and log them with `--bet`.
Sunday `--settle` pulls finals and grades both the paper plays and your real tickets. The
analysis scripts then read `data.db` in two languages; when they agree, their verdicts are
the only thing allowed to change the thresholds at the top of `cfb_edge.py`. Tests and CI
sit outside the loop and make sure a code change did not silently change what a "STRONG
ATS" means.

### Inside `cfb_edge.py` — what each flag does

```mermaid
flowchart TD
    START["python cfb_edge.py [flags]"] --> ARGS{"which flag?"}

    ARGS -->|"--bets-show"| BS["read bets.csv\nprint ledger + running ROI"] --> END
    ARGS -->|"--paper-show"| PS["open data.db\nprint paper_bets by kind × strength"] --> END

    ARGS -->|"anything else"| F1["fetch_scoreboard(date)\nscoreboard → 80 Game objects\nteams · records · kickoff · status · DK line"]
    F1 --> F2["enrich_games()\n8 threads: per game\n· core odds → open + current spread/total/ML\n· predictor → FPI win % + predicted margin"]
    F2 --> F3["fetch_powerindex() + apply\nFPI rating/rank per team\n(missing = FCS)"]
    F3 --> BRANCH{"flag?"}

    BRANCH -->|"--bet ID …"| B1["find game, append row to bets.csv"] --> END

    BRANCH -->|"--snapshot"| S1["db_persist: games + snapshots rows"] --> S2["db_paper_log: every strength≥1 play\nwith truth_p, price, stake"] --> RENDER
    BRANCH -->|"--backfill (past date)"| BF["same as --snapshot but games are final:\n'current' = closer · FPI = game-morning run\npaper_bets.backfill = 1"] --> ST
    BRANCH -->|"--settle"| ST["db_persist (scores) →\ndb_settle_paper: grade W/L/P + profit\nsettle_bets: grade bets.csv"] --> END
    BRANCH -->|"default / --top / --flagged"| RENDER

    RENDER["for each game:\nspread_signal · ml_signal\nspread_move_signal · total_move_signal"] --> R1["render_board (all games)\nor render_top (ranked, strength → steam → edge)"]
    R1 --> REP{"--report?"}
    REP -->|yes| W["write_report → reports/saturday-DATE.md"] --> END
    REP -->|no| END((done))
```

### Inside `analysis/` — what each script asks

```mermaid
flowchart LR
    DB[("data.db")] --> LG["load_games()\none row per settled FBS-vs-FBS game\nlast snapshot = closer\nderived: home_margin · market_margin\nfpi_delta · ats_margin · fpi_side_covered"]
    DB --> LB["load_paper_bets()\none row per graded paper play\npnl_flat = flat $1 result"]

    LB --> S1["01 paper_roi\nQ: does betting what the tool flags make money?\nflat ROI by kind × strength\n5,000-rep bootstrap 95% CI\nverdict: PROFITABLE / losing / inconclusive"]
    LG --> S2["02 fpi_calibration\nQ-A: when FPI says 70%, do they win 70%? (Wilson bins)\nQ-B: whose margin is closer to the truth — FPI or DK? (RMSE)\nQ-C: does the FPI side cover, by |Δ| bucket? (vs 52.4%)"]
    LG --> S3["03 line_move\nQ-A: does the side the line moved toward cover?\nQ-B: FPI side cover % when steam is WITH vs AGAINST it"]

    S1 & S2 & S3 --> OUTC["analysis/_out/*.csv\n(gitignored)"]
    S1 & S2 & S3 --> STD["stdout tables\nsame numbers in .py and .R"]
```

The R and Python versions of each script share the same SQL string, the same bins, and the
same closed-form Wilson interval, so their point estimates must be identical. Only the
bootstrap CIs in `01` are allowed to differ in the last digit.

---

## How it works

```mermaid
flowchart LR
    subgraph ESPN["ESPN public endpoints (no key)"]
        SB["scoreboard\n80 games / Saturday\nteams, records, kickoff, scores"]
        OD["core odds\nDraftKings open + current\nspread · total · moneyline"]
        PR["predictor\nFPI win prob\nFPI predicted margin"]
        PI["powerindex\nFPI rating + rank\noff / def efficiency"]
    end

    SB --> G["list[Game]\n(Game / TeamSide dataclasses)"]
    OD --> G
    PR --> G
    PI --> G

    G --> SIG["signals\nspread_signal · ml_signal\nspread_move_signal · total_move_signal"]
    SIG --> BOARD["render_board / render_top\nterminal"]
    SIG --> REP["write_report\nreports/saturday-DATE.md"]
    G --> DB[("data.db\ngames · snapshots · paper_bets")]
    SIG --> DB
    DB --> AN["analysis/ (Python + R)\n01 paper ROI CI\n02 FPI calibration\n03 line move"]
    AN -. constants .-> SIG
    BETS[("bets.csv\nreal-money ledger")] --> SET["--settle\ngrades from final scores"]
    DB --> SET
```

### The signals, in trust order

```mermaid
flowchart TD
    A["Game with DK line + FPI projection"] --> B{"Both sides FBS?\n(has an FPI rating)"}
    B -- no --> Z["strength 0\nFCS opponent → FPI uses a generic rating,\nthe 'edge' is noise. Shown on board, never ranked."]
    B -- yes --> C["Δ = |FPI margin − market margin|"]
    C --> D{"Δ ≥ 5?"}
    D -- yes --> E["STRONG ATS"]
    D -- no --> F{"Δ ≥ 3?"}
    F -- yes --> G["ATS lean"]
    F -- no --> H["no spread tag"]
    E & G --> I{"Demotions"}
    I --> I1["|spread| ≥ 28 → cap at lean\n(cover model unreliable in blowouts)"]
    I --> I2["line moved ≥1.5 pts AGAINST FPI → −1 tier\n⚠market-moved-against"]
    I --> I3["ML dog > +250 → cap at 'ML value'\n⚠long-dog"]
    I1 & I2 & I3 --> K["Kelly stake = ¼ · Kelly(cover %, price)\ncapped at 5% of bankroll, $1 min"]
```

| Signal | What it compares | Fires | Stake? |
|---|---|---|---|
| **ATS** (`spread_signal`) | FPI predicted margin vs DK spread | Δ ≥ 3 pts (lean), ≥ 5 (STRONG) | yes — cover % = Φ(Δ / 13.5) |
| **ML** (`ml_signal`) | FPI win prob vs de‑vigged DK moneyline | edge ≥ +8% (value), ≥ +20% (STRONG) | yes — truth p = FPI win prob |
| **line move** (`spread_move_signal`) | DK opener vs current | ≥ 3 pts | no — it's news (QB, injury, weather), not a model |
| **total steam** (`total_move_signal`) | DK total opener vs current | ≥ 2.5 pts | no — there is no totals model here |

The board also prints `[steam with]` / `[steam against]` whenever the spread moved ≥1.5 pts
since open, and `[crosses 3,7]` when the FPI number and the market number sit on opposite
sides of a key number.

### The arithmetic, with one worked game

Take Cal at Syracuse from the 2026‑09‑12 board: DK has Syracuse −3.5 (−102), moneyline
SYR −166 / CAL +140, and FPI projects Syracuse to win by 11.6 with an 80% win probability.

```mermaid
flowchart LR
    subgraph IN["inputs"]
        MK["market margin (home)
= −(home spread) = +3.5"]
        FM["FPI margin (home) = +11.6"]
        ML["moneyline −166 / +140"]
        FP["FPI win % = 80"]
    end
    MK & FM --> D["Δ = 11.6 − 3.5 = 8.1 pts
→ STRONG (≥ 5), side = home"]
    D --> CP["cover % = Φ(8.1 / 13.5) = Φ(0.60) ≈ 73%"]
    ML --> DV["implied 62.4% / 41.7% → sum 104.1%
de‑vig: 60.0% / 40.0%"]
    DV & FP --> E["ML edge = (80 − 60) / 60 = +33% → STRONG ML"]
    CP --> K1["Kelly at −102: b = 0.98
f = (0.73·0.98 − 0.27)/0.98 = 45%
¼ Kelly = 11% → capped at 5% → $5 on $100"]
    E --> K2["Kelly at −166: b = 0.60
f = (0.80·0.60 − 0.20)/0.60 = 47%
¼ Kelly = 12% → capped → $5"]
```

- **Market margin** is just the spread with the sign flipped, from the home team's point of view.
- **Δ** is the disagreement in points. Sign tells you which side FPI likes; size sets the tier.
- **Cover %** assumes the true margin is normal around FPI's number with SD 13.5 (`MARGIN_SD`).
  Historically the closer's error in FBS is 13–14 pts; the `02` script reports the live RMSE so
  the constant can be re‑tuned. This is the biggest modelling assumption in the tool.
- **De‑vig** divides each implied probability by their sum so the pair adds to 100%. The
  multiplicative method is used; it slightly favours the dog compared with the "power" method.
- **Kelly** uses the model probability as the truth, which is exactly the thing the analysis loop
  is testing. That is why stakes are quarter‑Kelly *and* capped at 5% of bankroll: if FPI is
  only 53% right instead of 73%, quarter‑Kelly on the wrong number still bleeds slowly instead
  of fast.
- **Key numbers** (3, 7, 10, 14) are where FBS margins bunch up. `[crosses 7,10]` means FPI's
  number and the market's sit on opposite sides of 7 and 10, so a half‑point either way matters
  more than usual.

### The weekly loop

```mermaid
sequenceDiagram
    participant You
    participant Tool as cfb_edge.py
    participant DB as data.db / bets.csv
    participant An as analysis/ (py + R)

    Note over You,An: Tue–Thu
    You->>Tool: python cfb_edge.py --top 15
    Tool-->>You: ranked outliers, line moves
    Note over You,An: Sat morning
    You->>Tool: --snapshot --report
    Tool->>DB: closing-ish lines + FPI, paper_bets, report .md
    You->>Tool: --bet ... (each real ticket)
    Tool->>DB: bets.csv
    Note over You,An: Sun morning
    You->>Tool: --settle
    Tool->>DB: finals → grade paper_bets + bets.csv
    You->>An: python analysis/…/*.py  and  Rscript analysis/…/*.R
    An-->>You: same numbers twice, or a bug
    You->>Tool: update constants (thresholds, MARGIN_SD), bump FINDINGS_AS_OF
```

`snapshot.bat` is the Task‑Scheduler wrapper: run it every 2–4 h Friday/Saturday so the DB
holds a near‑opener and a near‑closer for every game (closing‑line‑value tracking).

**Setting up the unattended snapshot** (one‑time, PowerShell as your normal user):

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\Users\wbp31\cfb_2026\snapshot.bat"
$trigger = New-ScheduledTaskTrigger -Once -At "06:00" -RepetitionInterval (New-TimeSpan -Hours 3) -RepetitionDuration (New-TimeSpan -Hours 18)
Register-ScheduledTask -TaskName "cfb_snapshot" -Action $action -Trigger $trigger -Description "cfb_edge --snapshot every 3h"
```

That fires 6 AM → midnight every day at three‑hour spacing; the tool is cheap enough (about
170 small HTTP calls) that running it on weekdays too is fine and gives you Tuesday openers.
`snapshot.log` in the repo folder collects the output; it is gitignored. Delete the task with
`Unregister-ScheduledTask -TaskName cfb_snapshot`.

---

## Reading the board

```
Kick CT     Matchup                 DK spread (open)      FPI mrg     Δ  Cov%  ML home/away    FPI%  Total (open)   Tag / $Bet
sat 02:30pm CAL @ SYR               SYR -3.5 (+1.5)         +11.6   8.1    73  -166/+140         80  56.5 (52.5)    STRONG ATS SYR -3.5 [steam with] [crosses 7,10] $5 · STRONG ML SYR -166 (+33%) $5
```

- **DK spread (open)** — home team's number now, opener in parentheses. Syracuse opened +1.5, now −3.5: five points of steam toward the home side.
- **FPI mrg** — FPI's predicted *home* margin. +11.6 means FPI has Syracuse by nearly 12.
- **Δ / Cov%** — |FPI − market| in points and the implied cover probability of the FPI side.
- **FPI%** — FPI home win probability, to compare with the moneyline.
- **Tag / $Bet** — green STRONG, cyan lean/value, red when the market moved against the model. Dollar figure is the quarter‑Kelly ceiling for the `--bankroll` given.
- **Total (open)** — DK total now, opener in parentheses. `total steam ▲4` means it moved four points since open. There is no totals model; the number is context only.
- A trailing `[in 14-7]` or `[post 31-24]` means the game has started or finished (away‑home score) and the row is display only — it is never ranked or paper‑logged.

### What the ledgers look like

`--paper-show` after the week 0–1 backfill:

```
paper bets — settled by kind/strength (pending: 0)
kind        str    n   W   L   P   staked   profit     ROI
ml            2    4   2   2   0    17.00     9.10  +53.5%
ml            1   14   5   9   0    33.00   -18.53  -56.2%
spread        2    3   1   2   0    15.00    -5.76  -38.4%
spread        1   13   7   5   1    62.00     7.89  +12.7%
```

`str` is the strength tier (2 STRONG, 1 lean/value). Stakes are what quarter‑Kelly would have
put down on a $100 bankroll at the time. Small n, wide swings — exactly why `01` bootstraps a CI
before anyone reads a per‑row ROI as a signal.

`--bets-show` prints one line per real ticket with `res` (W/L/P, or `·` while pending) and a
running net, then the settled stake, net and ROI at the bottom.

### What is stored

```mermaid
erDiagram
    games ||--o{ snapshots : "many per game (one per --snapshot run)"
    games ||--o{ paper_bets : "0..n flagged plays"
    games {
        text id PK "ESPN event id"
        text date "kickoff date, America/Chicago"
        text kickoff_utc
        int neutral
        text home_id
        text home
        text away_id
        text away
        int home_score
        int away_score
        int completed "1 once ESPN says final"
    }
    snapshots {
        int id PK
        text game_id FK
        text taken_at "ISO, local tz"
        text provider "DraftKings"
        real home_spread "negative = home favored"
        real home_spread_open
        real total
        real total_open
        int home_ml
        int away_ml
        real home_fpi_p "0..1"
        real home_fpi_margin "predicted home margin"
        real home_fpi "FPI rating, NULL = FCS"
        real away_fpi
    }
    paper_bets {
        int id PK
        text game_id FK
        text logged_at
        text kind "spread | ml"
        text side_id
        text side
        real line
        int price "american"
        real truth_p "model probability used for Kelly"
        real edge "pts (spread) or % (ml)"
        int strength "2 strong, 1 lean"
        real stake "quarter-Kelly at log time"
        text result "W L P, NULL = pending"
        real profit
        int backfill "1 = logged after the fact"
    }
```

`bets.csv` (your real tickets) has: `logged_at, date, game_id, matchup, kind, side, line,
price, stake, result, profit, settled_at, note`. It is a plain CSV so you can open it in
Excel, but let `--settle` fill `result`/`profit` rather than typing them.

Every `--snapshot` adds a **new** row to `snapshots` rather than updating, so the table is a
time series of the line. `analysis/_shared/load_data` takes the last row per game as "the
closer"; the first row is your best proxy for "where you could have bet". The gap between the
two is closing‑line value, the most reliable early indicator of whether a bettor has an edge.

---

## The analysis loop (Python and R, side by side)

Every script exists twice and must print the **same point estimates**. Bootstrap confidence
intervals may differ in the last digit (different RNG streams) — everything else must match,
and a disagreement means a bug.

```mermaid
flowchart LR
    DB[("data.db")] --> L1["_shared/load_data.py"]
    DB --> L2["_shared/load_data.R"]
    L1 & L2 --> S1["01 paper ROI + bootstrap CI\nby kind × strength"]
    L1 & L2 --> S2["02 FPI calibration\nWilson bins · RMSE vs closer · cover % by Δ"]
    L1 & L2 --> S3["03 line move\nfollow-the-money · steam with/against FPI"]
    S1 & S2 & S3 --> V{"Py == R ?"}
    V -- yes --> C["update constants in cfb_edge.py\nSPREAD_OUTLIER_PTS · MARGIN_SD · STEAM_PTS …\nbump FINDINGS_AS_OF"]
    V -- no --> BUG["fix the runtime that's wrong"]
```

### Getting `Rscript` on the PATH (one-time)

**Why bother.** The analysis loop only works as a *check* if you run every script twice,
once in Python and once in R, and compare the numbers. `Rscript` is the command-line R
runner that makes the R half a one-liner (`Rscript analysis/…/paper_roi.R`) instead of
opening RStudio, setting the working directory, and clicking Source. PATH is the list of
folders PowerShell searches when you type a command; R's installer does **not** add its
`bin` folder to it, so `Rscript` is "not recognized" in a fresh window even though R is
installed. Putting `C:\Program Files\R\R-4.4.2\bin` on the PATH once means `Rscript` works
from any folder, in any window, and inside `snapshot.bat` / Task Scheduler / Claude Code
without hard-coding the full path everywhere. It is the same reason `python` works: the
Python installer offered the "Add to PATH" checkbox and R's did not.

```mermaid
flowchart TD
    A["PowerShell: Rscript --version"] --> B{"found?"}
    B -- yes --> OK["✅ run the .R scripts from any folder"]
    B -- "not recognized" --> C["Get-ChildItem 'C:/Program Files/R'\nconfirm the version folder (R-4.4.2 here)"]
    C --> D{"this session only,\nor permanently?"}
    D -- "this session" --> E["$env:PATH += ';C:/Program Files/R/R-4.4.2/bin'"]
    D -- permanent --> F["[Environment]::SetEnvironmentVariable('Path',\n  user Path + ';C:/Program Files/R/R-4.4.2/bin', 'User')"]
    F --> G["close + reopen PowerShell"]
    E --> H["Rscript --version"]
    G --> H
    H --> B2{"prints R version 4.4.2?"}
    B2 -- yes --> OK
    B2 -- no --> C
```

*(Forward slashes in the diagram only, because Mermaid eats backslashes. Windows accepts either.)*

**What "permanently" actually does.** Windows keeps two PATH lists in the registry: a
*machine* list (all users, needs admin) and a *user* list (just you, no admin). Every
program builds its own PATH **once, at start-up**, by reading `machine ; user` from the
registry. That is why a window that was already open never sees the change, and why
"close + reopen" is a real step, not superstition. On this machine the R folder was added
to the **user** list on 2026‑09‑09.

```mermaid
flowchart LR
    subgraph REG["Registry (persistent)"]
        M["Machine Path\nHKLM\\...\\Environment\nC:/Windows/system32 · Git · nodejs · …\n(admin to edit)"]
        U["User Path\nHKCU\\Environment\nPython · VS Code · npm · **R-4.4.2/bin**\n(no admin, just you)"]
    end
    SET["[Environment]::SetEnvironmentVariable('Path', …, 'User')\nor System Properties → Environment Variables"] -->|writes| U

    subgraph OLD["Windows already open"]
        O1["PowerShell opened *before* the change\n$env:PATH = old machine + old user\nRscript → not recognized"]
    end
    subgraph NEW["Anything opened *after* the change"]
        N1["new PowerShell / Task Scheduler / Claude Code\n$env:PATH = machine ; user (fresh read)\nRscript → C:/Program Files/R/R-4.4.2/bin/Rscript.exe"]
    end
    M -->|read once at start-up| N1
    U -->|read once at start-up| N1
    U -. "never re-read" .-> O1
    O1 -->|"close + reopen"| N1

    TMP["$env:PATH += '…'\n(session only)"] -.->|"changes this window only,\nvanishes when it closes"| O1
```

Three ways to reach the same result, and where each one lives:

| Method | Scope | Survives reboot? | Admin? |
|---|---|---|---|
| `$env:PATH += ';C:\Program Files\R\R-4.4.2\bin'` | this window only | no | no |
| `[Environment]::SetEnvironmentVariable('Path', …, 'User')` | your account, every new window | **yes** | no |
| System Properties → Environment Variables → *System variables* → Path | every account | yes | yes |

To **undo**: System Properties → Environment Variables → *User variables* → Path → remove
the R entry. When you **upgrade R** the folder name changes (`R-4.5.0`), so swap the entry.

```powershell
# permanent, current user — run once, then reopen PowerShell
[Environment]::SetEnvironmentVariable('Path',
  [Environment]::GetEnvironmentVariable('Path','User') + ';C:\Program Files\R\R-4.4.2\bin', 'User')

# or just for this window
$env:PATH += ';C:\Program Files\R\R-4.4.2\bin'
Rscript --version
```

```powershell
pip install -r analysis/requirements-py.txt
python analysis/01_paper_roi_ci/paper_roi.py
python analysis/02_fpi_calibration/fpi_calibration.py
python analysis/03_line_move/line_move.py

# R (install packages once; see the PATH diagram above)
Rscript -e 'install.packages(readLines("analysis/requirements-r.txt"), repos="https://cloud.r-project.org")'
Rscript analysis/01_paper_roi_ci/paper_roi.R
Rscript analysis/02_fpi_calibration/fpi_calibration.R
Rscript analysis/03_line_move/line_move.R
```

Outputs land in `analysis/_out/` (gitignored). See [`analysis/README.md`](analysis/README.md).

---

## CI

Every push to `main` and every pull request runs `.github/workflows/ci.yml`. Nothing in
CI touches ESPN — the point is to catch syntax, lint, schema and runtime-drift bugs before
they reach the laptop on a Saturday morning.

```mermaid
flowchart LR
    PUSH["git push / PR"] --> PY["python job\n(3.12 and 3.13 matrix)"]
    PUSH --> RJ["R job\n(r-lib/actions, R 4.4)"]
    PY --> P1["py_compile\ncfb_edge.py + analysis/*.py"]
    P1 --> P2["ruff check\n(rule set pinned in ruff.toml)"]
    P2 --> PT["pytest tests/\n35 cases · no network"]
    PT --> P3["cfb_edge.py --help\n(argparse still parses)"]
    P3 --> P4["--paper-show --db scratch.db\n(SCHEMA + MIGRATIONS bootstrap)"]
    P4 --> P5["run all 3 analysis .py\nagainst the empty scratch DB\nCFB_DB env var"]
    RJ --> R1["install DBI · RSQLite · dplyr · boot"]
    R1 --> R2["bootstrap the same scratch DB\nwith the Python tool"]
    R2 --> R3["run all 3 analysis .R\nagainst it"]
    P5 & R3 --> OK{"green?"}
    OK -- yes --> M["merge / it's safe to run Saturday"]
    OK -- no --> FIX["fix the code, not the check"]
    DEP["dependabot (weekly)\nGitHub Actions + pip"] -.-> PUSH
```

The `CFB_DB` environment variable points both loaders at a scratch database; without it
they read `data.db` in the repo root. Locally you can reproduce the CI checks with:

```powershell
pip install -r requirements-dev.txt
ruff check cfb_edge.py analysis tests
python -m pytest -q tests
python cfb_edge.py --paper-show --db $env:TEMP\ci.db
$env:CFB_DB = "$env:TEMP\ci.db"; python analysis/01_paper_roi_ci/paper_roi.py; Rscript analysis/01_paper_roi_ci/paper_roi.R
Remove-Item Env:CFB_DB
```

---

## Data sources and gotchas

- **ESPN scoreboard** `site.api.espn.com/.../scoreboard?dates=YYYYMMDD&groups=80&limit=300` — the whole FBS slate incl. FCS visitors. Only one book is exposed (DraftKings).
- **ESPN core odds** `sports.core.api.espn.com/.../events/{id}/competitions/{id}/odds` — has `open` **and** `current` for spread, total and moneyline. For finished games `current` is frozen at the closer, which is what makes `--backfill` possible.
- **ESPN predictor** `.../competitions/{id}/predictor` — FPI `gameProjection` (win %) and `teamPredPtDiff` (margin). `lastModified` is the game‑morning run, so backfilled FPI is genuinely pre‑game.
- **ESPN powerindex** `site.web.api.espn.com/apis/fitt/v3/.../powerindex` — 138 FBS teams. A team missing here is FCS; the tool uses that as the "don't trust the edge" flag.
- **User‑Agent**: a full Chrome UA string gets a **403** from ESPN's Akamai edge; a plain `Mozilla/5.0` passes. Don't "improve" it.
- **Not used**: CollegeFootballData (needs a key), The Odds API (needs a key), Massey (403 to scripts). Multi‑book line shopping would need one of the keyed APIs — the hook is `_apply_core_odds`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `403 Client Error: Forbidden` on the first fetch | ESPN's Akamai edge rejects browser‑looking User‑Agent strings from non‑browsers | leave `UA = {"User-Agent": "Mozilla/5.0"}` alone; if ESPN changes again, try the bare `requests` default |
| `UnicodeEncodeError: 'charmap' codec` | Windows console is cp1252; output has Δ, ≥, → | already handled in `main()` and the analysis loader; if you see it, you are on a very old Python — upgrade |
| `0 games · 0 with DK line` | wrong date, or ESPN has not published the slate | check `--date`; weeknight dates only have a few games; FCS‑only days show nothing under `groups=80` |
| board has FPI but `—` for the spread | DK has not posted that game yet (common Sunday–Tuesday for small conferences) | re‑run later; `--snapshot` records whatever exists |
| a huge Δ on a game you have never heard of | FCS opponent; FPI's rating for them is a placeholder | expected — it is shown but never ranked or staked (`⚠non-FBS side`) |
| `--settle` grades nothing | games not final yet, or `data.db` has no `games` rows for that date | run after Sunday morning; make sure a `--snapshot` (or `--backfill`) captured the date first |
| `Rscript` not recognized | not on PATH | see the PATH section |
| `package 'RSQLite' is not available` | not installed in this R | `Rscript -e 'install.packages(readLines("analysis/requirements-r.txt"), repos="https://cloud.r-project.org")'` |
| Python and R print different numbers | a real bug in one of them | the SQL, bins and Wilson formula must be identical; diff the two files, fix the wrong one, add a test |

## Glossary

- **ATS** — against the spread. A −3.5 favorite "covers" by winning by 4+.
- **ML** — moneyline, a bet on who wins. `−166` risks 166 to win 100; `+140` risks 100 to win 140.
- **Opener / closer** — the first line a book posts and the last one before kickoff. The closer
  is the sharpest public estimate of the game; beating it consistently (**CLV**, closing line
  value) is the standard test of a real edge.
- **Steam** — a fast line move from sharp money or news. `[steam with]` means it moved toward
  FPI's side; `[steam against]` means away.
- **Key numbers** — margins FBS games land on most: 3, 7, 10, 14. Crossing one is worth more
  than the half‑point suggests.
- **De‑vig** — remove the bookmaker's margin so the two moneylines sum to 100%.
- **Kelly** — the stake fraction that maximises long‑run growth if your probability is right;
  quarter‑Kelly is the usual hedge against it being wrong.
- **FPI** — ESPN's Football Power Index: a rating per team plus a per‑game win probability and
  predicted margin. Public, keyless, updated overnight.
- **Δ (delta)** — |FPI margin − market margin| in points. Our single biggest input.
- **Paper bet** — a play the tool would have made, recorded and graded with no money on it.
- **Wilson interval** — a confidence interval for a proportion that behaves on small n; used
  for every cover‑rate and calibration bin in `analysis/`.
- **Bootstrap** — resample the bets with replacement 5,000× to get a CI on ROI without assuming
  a distribution.

## Roadmap (only if the numbers earn it)

- **Multi‑book line shopping.** ESPN exposes only DraftKings. A keyed API (CollegeFootballData
  or The Odds API, both free tiers) would add FanDuel/Caesars/BetMGM and turn "FPI vs DK" into
  "FPI vs the best available number". The adapter hook is `_apply_core_odds`.
- **CLV report.** `snapshots` already holds the time series; a `04_clv/` twin that compares the
  line at paper‑log time with the closer would answer "are we beating the close?" before the
  win/loss sample is large enough to say anything.
- **Totals model.** None today; `total steam` is context only. Off/def efficiency from the
  powerindex is captured but unused.
- **Blend.** `02` reports a 50/50 FPI+closer RMSE. If the blend beats both, `MARGIN_SD` and the
  side selection should use it. Only after both runtimes agree on more than a month of data.

## Files

| File | What |
|---|---|
| `cfb_edge.py` | the tool — everything lives here, section headers navigate it |
| `betting_guide.md` | live‑play reference: thresholds, what to fire on, discipline |
| `CLAUDE.md` | conventions for Claude Code |
| `analysis/` | Python + R twins, offline, read‑only |
| `tests/` | pytest unit tests, no network — run `python -m pytest -q tests` |
| `.github/` | CI workflow + dependabot |
| `ruff.toml`, `requirements-dev.txt` | lint config and dev deps (ruff, pytest) |
| `reports/` | `saturday-<date>.md` — what the tool said before kickoff |
| `snapshot.bat` | Task Scheduler wrapper |
| `data.db`, `bets.csv` | local only, gitignored |
