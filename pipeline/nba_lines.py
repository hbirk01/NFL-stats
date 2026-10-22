"""
DraftKings NBA player prop lines (over/under totals) via ESPN's free odds API,
for the NBA data job (nba_build.py): today's lines for the props board, and an
archive by date (nba/props-lines/<date>.json on the data branch) to test the
NBA prop model against, the way the NFL one was. ESPN drops a game's lines at
tip-off, so each run merges into the day's file instead of replacing it.

Unlike the NFL feed, NBA lines come with prices: each line is listed twice
(over and under, unlabeled), and both prices are kept in the order ESPN lists
them (`prices`, now and at open).

  python pipeline/nba_lines.py --date 2026-10-22 --out DIR
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"

# DraftKings' full-game over/under markets -> our stat keys (see nba_build.STATS).
MARKETS = {
    "Total Points": "pts",
    "Total Rebounds": "reb",
    "Total Assists": "ast",
    "Total 3-Point Field Goals": "fg3m",
    "Total Points, Rebounds, and Assists": "pra",
    "Total Points and Rebounds": "pr",
    "Total Points and Assists": "pa",
    "Total Assists and Rebounds": "ra",
    "Total Steals": "stl",
    "Total Blocks": "blk",
}


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _american(x) -> int | None:
    try:
        return int(str(x).replace("+", ""))
    except (TypeError, ValueError):
        return None


def games_on(day: str) -> list[dict]:
    """The day's games (YYYY-MM-DD, US date): ESPN event, teams, tip-off, state, DraftKings spread/total."""
    d = _get(f"{SITE}/scoreboard?dates={day.replace('-', '')}")
    out = []
    for e in d.get("events", []):
        c = e["competitions"][0]
        teams = {t["homeAway"]: t for t in c["competitors"]}
        odds = (c.get("odds") or [{}])[0]
        out.append({
            "event": str(e["id"]), "start": c.get("date"), "state": c["status"]["type"]["state"], "detail": c["status"]["type"].get("shortDetail"),
            "home": teams["home"]["team"]["abbreviation"], "away": teams["away"]["team"]["abbreviation"],
            "home_id": teams["home"]["team"]["id"], "away_id": teams["away"]["team"]["id"],
            "home_score": teams["home"].get("score"), "away_score": teams["away"].get("score"),
            "spread": odds.get("details"), "total": odds.get("overUnder"),
        })
    return out


def game_lines(event_id: str) -> list[dict]:
    """One game's player over/under lines: [{event, athlete (ESPN id), stat, line, open, prices, prices_open}]."""
    out, by_key, page = [], {}, 1
    while True:
        try:
            d = _get(f"{CORE}/events/{event_id}/competitions/{event_id}/odds/100/propBets?limit=1000&page={page}")
        except Exception:
            break
        for it in d.get("items", []):
            stat = MARKETS.get((it.get("type") or {}).get("name", ""))
            m = re.search(r"/athletes/(\d+)", (it.get("athlete") or {}).get("$ref", ""))
            line = ((it.get("current") or {}).get("target") or {}).get("value")
            if not (stat and m and isinstance(line, (int, float))):
                continue
            american = (it.get("odds") or {}).get("american") or {}
            key = (m.group(1), stat)
            if key in by_key:  # the second listing of the same line: the other side's price
                row = by_key[key]
                if len(row["prices"]) < 2 and row["line"] == float(line):
                    row["prices"].append(_american(american.get("value")))
                    row["prices_open"].append(_american(american.get("open")))
                continue
            opened = ((it.get("open") or {}).get("target") or {}).get("value")
            row = {
                "event": str(event_id), "athlete": m.group(1), "stat": stat, "line": float(line),
                "open": float(opened) if isinstance(opened, (int, float)) else None,
                "prices": [_american(american.get("value"))], "prices_open": [_american(american.get("open"))],
            }
            by_key[key] = row
            out.append(row)
        if page >= int(d.get("pageCount") or 1):
            break
        page += 1
    return out


def lines_for(events: list[str]) -> list[dict]:
    with ThreadPoolExecutor(8) as ex:
        return [x for rows in ex.map(game_lines, events) for x in rows]


def archive(folder: Path, day: str, lines: list[dict]) -> int:
    """Merges today's lines into nba/props-lines/<day>.json (games already started keep their last numbers). Returns days archived."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.json"
    kept = json.loads(path.read_text()) if path.exists() else []
    key = lambda x: (x["event"], x["athlete"], x["stat"])  # noqa: E731
    fresh = {key(x) for x in lines}
    path.write_text(json.dumps([x for x in kept if key(x) not in fresh] + lines, separators=(",", ":")))
    names = sorted(f.name for f in folder.glob("20*.json"))
    (folder / "index.json").write_text(json.dumps(names))
    return len(names)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", default="dist")
    args = ap.parse_args()
    games = games_on(args.date)
    lines = lines_for([g["event"] for g in games if g["state"] == "pre"])
    n = archive(Path(args.out) / "nba" / "props-lines", args.date, lines)
    print(f"{len(games)} games, {len(lines)} lines; {n} days archived")


if __name__ == "__main__":
    main()
