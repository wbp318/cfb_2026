#!/usr/bin/env python3
"""
cfb_gui.py — local browser dashboard for cfb_edge.py.

Standard library only (http.server + one HTML page). It imports cfb_edge and
calls the same functions the CLI does, so the board, ranked outliers, paper
ledger, real-bet ledger, snapshot / settle / report / backfill and --bet all
go through one code path. Nothing here recomputes a signal.

    python cfb_gui.py                 # serves http://127.0.0.1:8765 and opens a browser tab
    python cfb_gui.py --port 9000 --no-browser
    python cfb_gui.py --db other.db

Endpoints (all JSON, all local):
  GET  /api/slate?date=YYYY-MM-DD&bankroll=100&refresh=1   board + ranked plays
  GET  /api/paper                                            paper ledger summary + rows
  GET  /api/bets                                             bets.csv ledger
  POST /api/action  {"action": "snapshot"|"settle"|"report"|"backfill", date, bankroll}
  POST /api/bet     {game_id, kind, side, line, price, stake, note}
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

import cfb_edge as ce

# =====================================================================
# ---- slate cache + serialization ----
# =====================================================================

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[list[ce.Game], dt.datetime, list[str]]] = {}   # date -> (games, fetched_at, log)
DB_PATH = ce.DEFAULT_DB


def load_slate(date: dt.date, refresh: bool = False) -> tuple[list[ce.Game], dt.datetime, list[str]]:
    """Fetch (or reuse) the slate for a date. Mirrors the fetch block of cfb_edge.main."""
    key = date.isoformat()
    with _LOCK:
        if not refresh and key in _CACHE:
            return _CACHE[key]
        log: list[str] = []
        games = ce.fetch_scoreboard(date)
        ce.enrich_games(games)
        try:
            ce.apply_powerindex(games, ce.fetch_powerindex())
        except Exception as e:  # noqa: BLE001
            log.append(f"powerindex unavailable: {e}")
        log.append(f"{len(games)} games · {sum(g.home.spread is not None for g in games)} with DK line · "
                   f"{sum(g.home.fpi_margin is not None for g in games)} with FPI predictor")
        now = dt.datetime.now(ce.LOCAL_TZ)
        _CACHE[key] = (games, now, log)
        return _CACHE[key]


def _tag_text(s: ce.Signal, bankroll: float) -> str:
    """Same wording as render_board's tag cell, minus ANSI color."""
    txt = s.label
    if s.side:
        txt += f" {s.side.abbr}"
        if s.kind == "spread":
            txt += f" {ce.fmt_spread(s.line)}"
        elif s.kind == "spread-move":
            txt += f" {s.key_note}"
        elif s.kind == "ml":
            txt += f" {ce.fmt_ml(s.price)} (+{s.edge:.0f}%)"
    else:
        txt += f" {'▲' if s.edge > 0 else '▼'}{abs(s.edge):g}"
    if s.steam:
        txt += f" [steam {s.steam}]"
    if s.key_note and s.kind != "spread-move":
        txt += f" [{s.key_note}]"
    st = ce.stake_for(s, bankroll)
    if st:
        txt += f" ${st:.0f}"
    return (txt + " " + " ".join(ce.findings_warnings(s))).strip()


def _side_json(t: ce.TeamSide) -> dict:
    return {"id": t.id, "abbr": t.abbr, "name": t.name, "record": t.record, "rank": t.rank,
            "score": t.score, "fpi": t.fpi, "fpi_rank": t.fpi_rank,
            "ml": t.ml, "spread": t.spread, "spread_open": t.spread_open,
            "spread_price": t.spread_price, "fpi_win_p": t.fpi_win_p, "fpi_margin": t.fpi_margin}


def game_json(g: ce.Game, bankroll: float) -> dict:
    sigs = [s for s in (ce.spread_signal(g), ce.ml_signal(g), ce.total_move_signal(g),
                        ce.spread_move_signal(g)) if s and s.strength]
    ss = ce.spread_signal(g)
    return {
        "id": g.id, "short": g.short, "name": g.name, "status": g.status, "completed": g.completed,
        "neutral": g.neutral, "kick_local": g.kick_local.strftime("%a %I:%M%p").replace(":00", "").lower(),
        "kick_iso": g.kick_local.isoformat(timespec="minutes"),
        "home": _side_json(g.home), "away": _side_json(g.away),
        "provider": g.provider, "total": g.total, "total_open": g.total_open,
        "market_margin_home": ce.market_margin_home(g),
        "spread_edge": None if not ss else ss.edge,
        "cover_p": None if not ss else ss.truth_p,
        "spread_move_home": ce.spread_move_home(g),
        "max_strength": max((s.strength for s in sigs), default=0),
        "tags": [{"kind": s.kind, "strength": s.strength, "text": _tag_text(s, bankroll)} for s in sigs],
    }


def signal_json(i: int, s: ce.Signal, bankroll: float) -> dict:
    """One ranked row. Wording mirrors render_top."""
    g = s.game
    if s.kind == "spread":
        play = f"{s.side.name} {ce.fmt_spread(s.line)} ({ce.fmt_ml(s.price)})"
        what = (f"FPI margin {g.home.fpi_margin:+.1f} home vs market {ce.market_margin_home(g):+.1f} "
                f"→ Δ{s.edge:.1f} pts")
        pct = f"cover {s.truth_p*100:.0f}%"
    elif s.kind == "ml":
        fair = ce.devig_pair(g.home.ml, g.away.ml)[0 if s.side is g.home else 1]
        play = f"{s.side.name} ML {ce.fmt_ml(s.price)}"
        what = f"FPI {s.truth_p*100:.0f}% vs fair {fair*100:.0f}% → +{s.edge:.0f}%"
        pct = f"win {s.truth_p*100:.0f}%"
    elif s.kind == "spread-move":
        play = f"{s.side.name} {s.key_note}"
        what = f"line moved {s.edge:g} pts toward them — news, not model; FPI margin {g.home.fpi_margin:+.1f} home"
        pct = "—"
    else:
        play = f"Total {g.total:g} (opened {g.total_open:g})"
        what = f"moved {s.edge:+g} — movement only, no model"
        pct = "—"
    st = ce.stake_for(s, bankroll)
    flags = ce.findings_warnings(s) + ([f"[{s.key_note}]"] if s.key_note and s.kind != "spread-move" else [])
    return {"rank": i, "label": s.label, "kind": s.kind, "strength": s.strength,
            "game_id": g.id, "short": g.short, "kick_local": g.kick_local.strftime("%a %I:%M%p").lower(),
            "play": play, "what": what, "pct": pct, "steam": s.steam,
            "stake": st, "flags": flags, "side_id": s.side.id if s.side else None,
            "line": s.line, "price": s.price}


def slate_json(date: dt.date, bankroll: float, refresh: bool) -> dict:
    games, fetched_at, log = load_slate(date, refresh)
    return {"date": date.isoformat(), "bankroll": bankroll,
            "fetched_at": fetched_at.strftime("%Y-%m-%d %I:%M %p"), "log": log,
            "games": [game_json(g, bankroll) for g in games],
            "top": [signal_json(i, s, bankroll) for i, s in enumerate(ce.ranked_signals(games), 1)],
            "constants": {"SPREAD_OUTLIER_PTS": ce.SPREAD_OUTLIER_PTS, "SPREAD_STRONG_PTS": ce.SPREAD_STRONG_PTS,
                          "ML_EDGE_PCT": ce.ML_EDGE_PCT, "ML_STRONG_PCT": ce.ML_STRONG_PCT,
                          "STEAM_PTS": ce.STEAM_PTS, "KELLY_FRACTION": ce.KELLY_FRACTION,
                          "MAX_TICKET_PCT": ce.MAX_TICKET_PCT, "FINDINGS_AS_OF": ce.FINDINGS_AS_OF}}


# =====================================================================
# ---- ledgers + actions (thin wrappers over cfb_edge) ----
# =====================================================================

def paper_json() -> dict:
    conn = ce.db_connect(DB_PATH)
    rows = conn.execute(
        "SELECT p.id,g.date,g.name,p.kind,p.side,p.line,p.price,p.truth_p,p.edge,p.strength,"
        "p.stake,p.result,p.profit,p.backfill,p.logged_at FROM paper_bets p "
        "LEFT JOIN games g ON g.id=p.game_id ORDER BY p.id DESC LIMIT 500").fetchall()
    cols = ["id", "date", "game", "kind", "side", "line", "price", "truth_p", "edge", "strength",
            "stake", "result", "profit", "backfill", "logged_at"]
    return {"summary": ce.db_paper_summary(conn), "rows": [dict(zip(cols, r)) for r in rows]}


def bets_json() -> dict:
    rows: list[dict] = []
    if os.path.exists(ce.BETS_CSV):
        import csv
        with open(ce.BETS_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    return {"summary": ce.show_bets(ce.BETS_CSV), "rows": rows}


def run_action(action: str, date: dt.date, bankroll: float) -> dict:
    """snapshot / settle / report / backfill — same sequence as cfb_edge.main."""
    out: list[str] = []
    now = dt.datetime.now(ce.LOCAL_TZ)
    games, _, log = load_slate(date, refresh=True)     # actions always refetch (scores, closers)
    out.extend(log)
    conn = ce.db_connect(DB_PATH)
    if action in ("snapshot", "settle", "report"):
        n = ce.db_persist(conn, games, now)
        out.append(f"snapshot: {n} line rows → {DB_PATH}")
    if action == "backfill":
        ce.db_persist(conn, games, now)
        n = ce.db_paper_log(conn, ce.ranked_signals(games, include_done=True), bankroll, now, backfill=True)
        out.append(f"backfill {date}: paper-logged {n} flagged plays")
    elif action == "snapshot":
        n = ce.db_paper_log(conn, ce.ranked_signals(games), bankroll, now)
        out.append(f"paper-logged {n} new flagged plays")
    if action in ("settle", "backfill"):
        n, staked, profit = ce.db_settle_paper(conn)
        out.append(f"settled {n} paper bets: staked {staked:.2f}, profit {profit:+.2f}")
        m = ce.settle_bets(conn, ce.BETS_CSV)
        out.append(f"settled {m} real bets in {ce.BETS_CSV}")
        out.append(ce.db_paper_summary(conn))
    if action == "report":
        path = ce.write_report(games, bankroll, date, now, ce.db_paper_summary(conn))
        out.append(f"report → {path}")
    return {"ok": True, "log": out}


def log_bet_from(payload: dict) -> dict:
    date = dt.date.fromisoformat(payload["date"])
    games, _, _ = load_slate(date)
    g = next((x for x in games if x.id == str(payload.get("game_id"))), None)
    kind = payload.get("kind")
    if not g or kind not in ("spread", "ml", "over", "under") or payload.get("stake") in (None, ""):
        return {"ok": False, "error": "need a game from this slate, a kind, and a stake"}
    side = payload.get("side") or kind
    line = ce._num(payload.get("line")) if payload.get("line") not in (None, "") else None
    price = int(float(payload.get("price") or ce.SPREAD_PRICE))
    stake = float(payload["stake"])
    ce.log_bet(g, kind, side, line, price, stake, payload.get("note") or "", path=ce.BETS_CSV)
    return {"ok": True, "log": [f"logged: {g.short} {kind} {side} {line} @ {price} for ${stake:.2f}"]}


# =====================================================================
# ---- HTTP ----
# =====================================================================

class Handler(BaseHTTPRequestHandler):
    server_version = "cfb_gui/1"

    def log_message(self, fmt, *args):  # quieter console
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif u.path == "/api/slate":
                date = dt.date.fromisoformat(q["date"]) if q.get("date") else ce.next_saturday()
                self._json(slate_json(date, float(q.get("bankroll") or 100), q.get("refresh") == "1"))
            elif u.path == "/api/paper":
                self._json(paper_json())
            elif u.path == "/api/bets":
                self._json(bets_json())
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(n) or b"{}")
        try:
            if u.path == "/api/action":
                date = dt.date.fromisoformat(payload["date"]) if payload.get("date") else ce.next_saturday()
                action = payload.get("action")
                if action not in ("snapshot", "settle", "report", "backfill"):
                    self._json({"ok": False, "error": "unknown action"}, 400)
                    return
                buf = io.StringIO()
                with contextlib.redirect_stderr(buf):
                    res = run_action(action, date, float(payload.get("bankroll") or 100))
                if buf.getvalue().strip():
                    res["log"] = buf.getvalue().strip().splitlines() + res["log"]
                self._json(res)
            elif u.path == "/api/bet":
                self._json(log_bet_from(payload))
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)


# =====================================================================
# ---- page ----
# =====================================================================

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CFB Edge</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--line:#262a33;--fg:#e6e8ee;--dim:#8a91a0;--acc:#4f8cff;
 --strong:#2ecc71;--lean:#f1c40f;--info:#7f8c8d;--warn:#e67e22;--bad:#e74c3c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,Segoe UI,Roboto,sans-serif}
header{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:12px 16px;background:var(--panel);
 border-bottom:1px solid var(--line);position:sticky;top:0;z-index:2}
header h1{font-size:16px;margin:0 12px 0 0;font-weight:600}
header label{color:var(--dim);font-size:12px;display:flex;flex-direction:column;gap:2px}
input,select,button{background:#0f1115;color:var(--fg);border:1px solid var(--line);border-radius:6px;
 padding:6px 8px;font:inherit}
input[type=number]{width:90px}
button{cursor:pointer;background:#1f2430}
button.primary{background:var(--acc);border-color:var(--acc);color:#fff}
button:disabled{opacity:.5;cursor:wait}
nav{display:flex;gap:4px;padding:8px 16px 0;border-bottom:1px solid var(--line);background:var(--panel)}
nav button{border-radius:6px 6px 0 0;border-bottom:none;padding:8px 14px}
nav button.on{background:var(--bg);color:var(--acc);font-weight:600}
main{padding:16px;max-width:1500px;margin:0 auto}
section{display:none}section.on{display:block}
.status{color:var(--dim);font-size:12px;margin:4px 0 12px;white-space:pre-wrap}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;white-space:nowrap}
th{color:var(--dim);font-weight:600;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--bg)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr.s2 td:first-child{border-left:3px solid var(--strong)}
tr.s1 td:first-child{border-left:3px solid var(--lean)}
tr.done{color:var(--dim)}
.tag{display:inline-block;padding:1px 6px;border-radius:4px;margin:1px 4px 1px 0;font-size:12px;white-space:normal}
.tag.s2{background:rgba(46,204,113,.18);color:var(--strong)}
.tag.s1{background:rgba(241,196,15,.15);color:var(--lean)}
.tag.info{background:rgba(127,140,141,.2);color:#b0b8c0}
.warn{color:var(--warn)}
.dim{color:var(--dim)}
.wrap{white-space:normal}
pre{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px;overflow:auto;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px}
.card h3{margin:0 0 6px;font-size:14px}
.card p{margin:0 0 10px;color:var(--dim);font-size:12px}
form.bet{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;align-items:end}
form.bet label{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--dim)}
.callout{border-left:3px solid var(--warn);background:rgba(230,126,34,.08);padding:10px 12px;border-radius:0 6px 6px 0;
 font-size:13px;margin-bottom:14px}
.spin{display:inline-block;width:12px;height:12px;border:2px solid var(--dim);border-top-color:var(--acc);
 border-radius:50%;animation:r .8s linear infinite;vertical-align:-2px;margin-right:6px}
@keyframes r{to{transform:rotate(360deg)}}
.tblwrap{overflow-x:auto}
@media (max-width:700px){td,th{padding:5px 6px}}
</style></head><body>
<header>
  <h1>CFB Edge <span class="dim" style="font-weight:400">FPI vs DraftKings</span></h1>
  <label>Saturday<input type="date" id="date"></label>
  <label>Bankroll $<input type="number" id="bankroll" value="100" min="1" step="1"></label>
  <label>&nbsp;<button class="primary" id="load">Load slate</button></label>
  <label>&nbsp;<button id="refresh" title="re-fetch from ESPN">↻ Refresh</button></label>
  <label><span>Show</span><select id="filter"><option value="all">all games</option>
    <option value="flag">flagged only</option><option value="pre">not kicked</option></select></label>
  <span id="hdr-status" class="dim" style="font-size:12px;margin-left:auto"></span>
</header>
<nav>
  <button data-tab="board" class="on">Board</button>
  <button data-tab="top">Top plays</button>
  <button data-tab="paper">Paper ledger</button>
  <button data-tab="bets">Real bets</button>
  <button data-tab="actions">Actions</button>
</nav>
<main>
<section id="board" class="on">
  <div class="status" id="board-status">Pick a date and press <b>Load slate</b>.</div>
  <div class="tblwrap"><table id="board-tbl"><thead><tr>
    <th data-k="kick_iso">Kick CT</th><th data-k="short">Matchup</th><th>DK spread (open)</th>
    <th class="num" data-k="home.fpi_margin">FPI mrg</th><th class="num" data-k="spread_edge">Δ</th>
    <th class="num" data-k="cover_p">Cov%</th><th>ML H/A</th><th class="num" data-k="home.fpi_win_p">FPI%</th>
    <th>Total (open)</th><th data-k="max_strength">Tag / $Bet</th></tr></thead><tbody></tbody></table></div>
</section>
<section id="top">
  <div class="callout"><b>Honest expectations.</b> FPI vs the closing line has historically run roughly 50–53% ATS;
   at −110 you need 52.4% to break even. $Bet is quarter-Kelly on the model's probability and is a ceiling, not a target.
   Skip anything flagged ⚠market-moved-against unless you know why the line moved and disagree.</div>
  <div class="status" id="top-status"></div>
  <div class="tblwrap"><table id="top-tbl"><thead><tr><th>#</th><th>Tag</th><th>Kick</th><th>Game</th><th>Play</th>
   <th>Model vs market</th><th>Cover/Win</th><th>Steam</th><th class="num">$Bet</th><th>Flags</th><th></th></tr></thead>
   <tbody></tbody></table></div>
</section>
<section id="paper">
  <div class="status" id="paper-status"></div>
  <pre id="paper-summary">loading…</pre>
  <div class="tblwrap"><table id="paper-tbl"><thead><tr><th>id</th><th>date</th><th>game</th><th>kind</th><th>side</th>
   <th class="num">line</th><th class="num">price</th><th class="num">p</th><th class="num">edge</th><th class="num">str</th>
   <th class="num">stake</th><th>res</th><th class="num">profit</th><th>bf</th></tr></thead><tbody></tbody></table></div>
</section>
<section id="bets">
  <div class="card" style="margin-bottom:14px"><h3>Log a placed bet</h3>
   <p>Writes a row to bets.csv exactly like <code>--bet</code>. Settle it Sunday from the Actions tab.</p>
   <form class="bet" id="bet-form">
    <label>Game<select id="b-game"></select></label>
    <label>Kind<select id="b-kind"><option>spread</option><option>ml</option><option>over</option><option>under</option></select></label>
    <label>Side<select id="b-side"></select></label>
    <label>Line<input type="number" step="0.5" id="b-line"></label>
    <label>Price<input type="number" step="1" id="b-price" value="-110"></label>
    <label>Stake $<input type="number" step="0.5" id="b-stake" min="0.5"></label>
    <label>Note<input type="text" id="b-note"></label>
    <label>&nbsp;<button class="primary" type="submit">Log bet</button></label>
   </form><div class="status" id="bet-status"></div></div>
  <pre id="bets-summary">loading…</pre>
</section>
<section id="actions">
  <div class="status" id="act-status"></div>
  <div class="grid">
   <div class="card"><h3>Snapshot</h3><p>Persist current lines + FPI to the DB and paper-log every flagged play
    (<code>--snapshot</code>). Run Friday and again Saturday morning.</p><button data-act="snapshot">Run snapshot</button></div>
   <div class="card"><h3>Settle</h3><p>Refresh scores, grade paper bets and bets.csv (<code>--settle</code>). Sunday.</p>
    <button data-act="settle">Run settle</button></div>
   <div class="card"><h3>Report</h3><p>Snapshot + write <code>reports/saturday-&lt;date&gt;.md</code> (<code>--report</code>).</p>
    <button data-act="report">Write report</button></div>
   <div class="card"><h3>Backfill</h3><p>For a <b>past</b> Saturday: closers + pre-game FPI, paper-log with backfill=1,
    settle (<code>--backfill</code>).</p><button data-act="backfill">Run backfill</button></div>
  </div>
  <pre id="act-log" style="margin-top:14px">—</pre>
</section>
</main>
<script>
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let SLATE=null, sortKey='kick_iso', sortDir=1;
const spread=x=>x==null?'—':x===0?'PK':(x>0?'+':'')+(Number.isInteger(x)?x:x.toFixed(1));
const ml=x=>x==null?'—':(x>0?'+':'')+x;
const num=(x,d=1)=>x==null?'—':x.toFixed(d);
function nextSat(){const d=new Date();d.setDate(d.getDate()+(6-d.getDay()+7)%7);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}
$('#date').value=nextSat();
try{const b=localStorage.getItem('bankroll');if(b)$('#bankroll').value=b}catch(e){}
$('#bankroll').addEventListener('change',()=>{try{localStorage.setItem('bankroll',$('#bankroll').value)}catch(e){}});
$$('nav button').forEach(b=>b.onclick=()=>{$$('nav button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
 $$('section').forEach(s=>s.classList.toggle('on',s.id===b.dataset.tab));
 if(b.dataset.tab==='paper')loadPaper();if(b.dataset.tab==='bets')loadBets();});
const get=k=>o=>k.split('.').reduce((a,c)=>a?.[c],o);
function tagHtml(t){const cls=t.kind==='spread'||t.kind==='ml'?('s'+t.strength):'info';return `<span class="tag ${cls}">${esc(t.text).replace(/⚠[\w-]+/g,m=>`<span class="warn">${m}</span>`)}</span>`}
function renderBoard(){
 if(!SLATE)return;const f=$('#filter').value;const g=get(sortKey);
 let rows=SLATE.games.filter(x=>f==='all'||(f==='flag'&&x.tags.length)||(f==='pre'&&x.status==='pre'));
 rows.sort((a,b)=>{const A=g(a),B=g(b);if(A==null&&B==null)return 0;if(A==null)return 1;if(B==null)return -1;return (A<B?-1:A>B?1:0)*sortDir});
 $('#board-tbl tbody').innerHTML=rows.map(x=>{
  const lab=t=>(t.rank?`#${t.rank} `:'')+t.abbr;
  const sp=`${x.home.abbr} ${spread(x.home.spread)}`+(x.home.spread_open!=null&&x.home.spread_open!==x.home.spread?` (${spread(x.home.spread_open)})`:'');
  const tot=x.total==null?'—':x.total+(x.total_open!=null&&x.total_open!==x.total?` (${x.total_open})`:'');
  const st=x.status!=='pre'?`<span class="dim">[${x.status} ${x.away.score}-${x.home.score}]</span>`:'';
  return `<tr class="s${x.max_strength} ${x.status!=='pre'?'done':''}"><td>${x.kick_local}</td>
   <td title="${esc(x.name)}">${esc(lab(x.away))} @ ${esc(lab(x.home))}${x.neutral?' (N)':''}</td><td>${sp}</td>
   <td class="num">${x.home.fpi_margin==null?'—':(x.home.fpi_margin>0?'+':'')+x.home.fpi_margin.toFixed(1)}</td>
   <td class="num">${num(x.spread_edge)}</td><td class="num">${x.cover_p==null?'—':Math.round(x.cover_p*100)}</td>
   <td>${ml(x.home.ml)}/${ml(x.away.ml)}</td><td class="num">${x.home.fpi_win_p==null?'—':Math.round(x.home.fpi_win_p*100)}</td>
   <td>${tot}</td><td class="wrap">${x.tags.map(tagHtml).join('')} ${st}</td></tr>`}).join('');
 $('#board-status').textContent=`${SLATE.date} · fetched ${SLATE.fetched_at} · ${SLATE.log.join(' · ')} · showing ${rows.length}`;
}
function renderTop(){
 if(!SLATE)return;const t=SLATE.top;
 $('#top-status').textContent=t.length?`${t.length} ranked outliers — bankroll $${SLATE.bankroll}, 1/4 Kelly, cap ${SLATE.constants.MAX_TICKET_PCT*100}% · thresholds as of ${SLATE.constants.FINDINGS_AS_OF}`:'no flagged outliers on this slate';
 $('#top-tbl tbody').innerHTML=t.map(s=>`<tr class="s${s.strength}"><td>${s.rank}</td><td>${tagHtml({kind:s.kind,strength:s.strength,text:s.label})}</td>
  <td>${s.kick_local}</td><td>${esc(s.short)}</td><td>${esc(s.play)}</td><td class="wrap">${esc(s.what)}</td><td>${s.pct}</td>
  <td>${s.steam||'—'}</td><td class="num">${s.stake?'$'+s.stake.toFixed(0):'—'}</td>
  <td class="wrap warn">${esc(s.flags.join(' '))}</td>
  <td>${s.side_id&&(s.kind==='spread'||s.kind==='ml')?`<button data-prefill='${esc(JSON.stringify(s))}'>bet…</button>`:''}</td></tr>`).join('');
 $$('#top-tbl [data-prefill]').forEach(b=>b.onclick=()=>prefill(JSON.parse(b.dataset.prefill)));
}
function fillBetForm(){
 if(!SLATE)return;const sel=$('#b-game');
 sel.innerHTML=SLATE.games.map(x=>`<option value="${x.id}">${esc(x.kick_local)} ${esc(x.short)}</option>`).join('');
 sideOptions();
}
function sideOptions(){
 const x=SLATE?.games.find(g=>g.id===$('#b-game').value);const k=$('#b-kind').value;const s=$('#b-side');
 if(!x||k==='over'||k==='under'){s.innerHTML='<option value="">—</option>';s.disabled=true;return}
 s.disabled=false;s.innerHTML=`<option value="${esc(x.away.name)}">${esc(x.away.name)} (away)</option><option value="${esc(x.home.name)}">${esc(x.home.name)} (home)</option>`;
 if(k==='spread'){const side=s.value===x.home.name?x.home:x.away;$('#b-line').value=side.spread??'';$('#b-price').value=side.spread_price??-110}
 else if(k==='ml'){const side=s.value===x.home.name?x.home:x.away;$('#b-line').value='';$('#b-price').value=side.ml??''}
}
$('#b-game').onchange=sideOptions;$('#b-kind').onchange=sideOptions;
$('#b-side').onchange=()=>{const x=SLATE?.games.find(g=>g.id===$('#b-game').value);if(!x)return;const k=$('#b-kind').value;
 const side=$('#b-side').value===x.home.name?x.home:x.away;
 if(k==='spread'){$('#b-line').value=side.spread??'';$('#b-price').value=side.spread_price??-110}else if(k==='ml'){$('#b-price').value=side.ml??''}};
function prefill(s){
 $$('nav button')[3].click();$('#b-game').value=s.game_id;$('#b-kind').value=s.kind;sideOptions();
 const x=SLATE.games.find(g=>g.id===s.game_id);const side=x.home.id===s.side_id?x.home:x.away;
 $('#b-side').value=side.name;$('#b-line').value=s.line??'';$('#b-price').value=s.price??-110;$('#b-stake').value=s.stake??'';
}
async function api(path,opts){const r=await fetch(path,opts);const j=await r.json();if(j.ok===false)throw new Error(j.error||'error');return j}
async function loadSlate(refresh){
 const btns=[$('#load'),$('#refresh')];btns.forEach(b=>b.disabled=true);
 $('#hdr-status').innerHTML='<span class="spin"></span>fetching from ESPN…';
 try{SLATE=await api(`/api/slate?date=${$('#date').value}&bankroll=${$('#bankroll').value}&refresh=${refresh?1:0}`);
  renderBoard();renderTop();fillBetForm();$('#hdr-status').textContent=`${SLATE.games.length} games · ${SLATE.top.length} flagged`;}
 catch(e){$('#hdr-status').textContent='';$('#board-status').textContent='error: '+e.message}
 btns.forEach(b=>b.disabled=false);
}
$('#load').onclick=()=>loadSlate(false);$('#refresh').onclick=()=>loadSlate(true);
$('#filter').onchange=renderBoard;$('#bankroll').onchange=()=>{if(SLATE)loadSlate(false)};
$$('#board-tbl th[data-k]').forEach(th=>th.onclick=()=>{const k=th.dataset.k;sortDir=(sortKey===k)?-sortDir:(k==='kick_iso'||k==='short'?1:-1);sortKey=k;renderBoard()});
async function loadPaper(){try{const p=await api('/api/paper');$('#paper-summary').textContent=p.summary;
 $('#paper-tbl tbody').innerHTML=p.rows.map(r=>`<tr class="${r.result==='W'?'':r.result==='L'?'done':''}"><td>${r.id}</td><td>${esc(r.date)}</td><td>${esc(r.game)}</td><td>${r.kind}</td><td>${esc(r.side)}</td>
  <td class="num">${r.line??''}</td><td class="num">${ml(r.price)}</td><td class="num">${r.truth_p==null?'':Math.round(r.truth_p*100)+'%'}</td><td class="num">${num(r.edge)}</td>
  <td class="num">${r.strength}</td><td class="num">${num(r.stake,2)}</td><td>${r.result||'·'}</td><td class="num">${r.profit==null?'·':(r.profit>=0?'+':'')+r.profit.toFixed(2)}</td><td>${r.backfill?'bf':''}</td></tr>`).join('');
 $('#paper-status').textContent=`${p.rows.length} most recent paper rows`}catch(e){$('#paper-summary').textContent='error: '+e.message}}
async function loadBets(){try{const b=await api('/api/bets');$('#bets-summary').textContent=b.summary}catch(e){$('#bets-summary').textContent='error: '+e.message}}
$('#bet-form').onsubmit=async ev=>{ev.preventDefault();if(!SLATE){$('#bet-status').textContent='load a slate first';return}
 const body={date:SLATE.date,game_id:$('#b-game').value,kind:$('#b-kind').value,side:$('#b-side').value,line:$('#b-line').value,
  price:$('#b-price').value,stake:$('#b-stake').value,note:$('#b-note').value};
 try{const r=await api('/api/bet',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  $('#bet-status').textContent=r.log.join('\n');$('#b-stake').value='';$('#b-note').value='';loadBets()}catch(e){$('#bet-status').textContent='error: '+e.message}};
$$('[data-act]').forEach(b=>b.onclick=async()=>{
 const act=b.dataset.act;if(!confirm(`Run ${act} for ${$('#date').value}? This writes to the DB${act==='report'?' and reports/':''}.`))return;
 $$('[data-act]').forEach(x=>x.disabled=true);$('#act-status').innerHTML=`<span class="spin"></span>running ${act}…`;
 try{const r=await api('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:act,date:$('#date').value,bankroll:$('#bankroll').value})});
  $('#act-log').textContent=r.log.join('\n');$('#act-status').textContent=`${act} done`;if(SLATE)loadSlate(false)}
 catch(e){$('#act-status').textContent='error: '+e.message}
 $$('[data-act]').forEach(x=>x.disabled=false)});
</script></body></html>
"""


# =====================================================================
# ---- main ----
# =====================================================================

def main(argv: Optional[list[str]] = None) -> int:
    global DB_PATH
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Local browser dashboard for cfb_edge.py")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--db", default=ce.DEFAULT_DB)
    p.add_argument("--no-browser", action="store_true")
    a = p.parse_args(argv)
    DB_PATH = a.db
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{a.host}:{a.port}/"
    print(f"cfb_gui → {url}   (Ctrl+C to stop)", file=sys.stderr)
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
