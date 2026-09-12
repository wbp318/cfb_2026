"""Unit tests for cfb_gui.py. No network — the slate cache is seeded by hand and
the HTTP layer is driven through a real (loopback) ThreadingHTTPServer."""
from __future__ import annotations

import datetime as dt
import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cfb_edge as ce
import cfb_gui as gui
from test_cfb_edge import make_game

DATE = dt.date(2026, 9, 12)


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """Two hand-built games in the slate cache, scratch DB, scratch bets.csv, no ESPN."""
    strong = make_game(home_spread=-3.5, fpi_home_margin=9.0)            # Δ5.5 → STRONG ATS home
    done = make_game(status="post", home_score=31, away_score=10)
    done.id = "g2"
    monkeypatch.setattr(gui, "_CACHE", {DATE.isoformat(): ([strong, done], dt.datetime.now(ce.LOCAL_TZ), ["seeded"])})
    monkeypatch.setattr(gui, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(ce, "BETS_CSV", str(tmp_path / "bets.csv"))
    monkeypatch.setattr(ce, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(ce, "fetch_scoreboard", lambda d: (_ for _ in ()).throw(AssertionError("network")))

    def fake_load(date, refresh=False):           # actions always refetch; keep them off the network
        return gui._CACHE[date.isoformat()]
    monkeypatch.setattr(gui, "load_slate", fake_load)
    return strong, done


def test_slate_json_mirrors_signals(seeded):
    strong, done = seeded
    j = gui.slate_json(DATE, 100.0, refresh=False)
    assert j["date"] == "2026-09-12" and len(j["games"]) == 2
    g = j["games"][0]
    assert g["home"]["spread"] == -3.5 and g["spread_edge"] == pytest.approx(5.5)
    assert g["max_strength"] == 2 and any(t["text"].startswith("STRONG ATS HOM -3.5") for t in g["tags"])
    top = j["top"]
    assert top and top[0]["label"] == "STRONG ATS" and top[0]["game_id"] == "g1"
    # started game is excluded from the ranking, exactly like render_top
    assert all(t["game_id"] != "g2" for t in top)
    assert top[0]["stake"] == ce.stake_for(ce.spread_signal(strong), 100.0)
    json.dumps(j)   # must be plain JSON


def test_tag_text_matches_board_wording(seeded):
    strong, _ = seeded
    s = ce.spread_signal(strong)
    txt = gui._tag_text(s, 100.0)
    assert txt.startswith("STRONG ATS HOM -3.5")
    assert "[crosses" in txt and "$" in txt


def test_actions_and_bet_roundtrip(seeded):
    r = gui.run_action("snapshot", DATE, 100.0)
    assert r["ok"] and any("paper-logged 2 new" in x or "paper-logged" in x for x in r["log"])
    r = gui.log_bet_from({"date": DATE.isoformat(), "game_id": "g1", "kind": "spread",
                          "side": "Home U", "line": -3.5, "price": -110, "stake": 5})
    assert r["ok"]
    assert gui.log_bet_from({"date": DATE.isoformat(), "game_id": "nope", "kind": "ml", "stake": 1})["ok"] is False
    b = gui.bets_json()
    assert len(b["rows"]) == 1 and b["rows"][0]["side"] == "Home U"
    p = gui.paper_json()
    assert p["rows"] and "pending" in p["summary"]
    r = gui.run_action("report", DATE, 100.0)
    assert any("report →" in x for x in r["log"])


def test_http_endpoints(seeded):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), gui.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        html = urllib.request.urlopen(base + "/").read().decode("utf-8")
        assert "<title>CFB Edge</title>" in html
        j = json.load(urllib.request.urlopen(base + f"/api/slate?date={DATE}&bankroll=200"))
        assert j["bankroll"] == 200 and len(j["games"]) == 2
        req = urllib.request.Request(base + "/api/action", data=json.dumps({"action": "nuke"}).encode(),
                                     headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 400
        assert urllib.request.urlopen(base + "/api/paper").status == 200
    finally:
        srv.shutdown()
        srv.server_close()
