"""
DraftKings player prop lines (over/under totals), via ESPN's free odds API.
ESPN keeps them for this season's finished games but not past seasons, so the
data job archives each week's lines (props/<season>-w<week>.json on the data
branch) to build a history to test the prop model against.

  python pipeline/proplines.py --season 2026 --weeks 1-4 --out DIR
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"

# DraftKings' over/under markets -> our stat columns (see build.game_lines).
MARKETS = {
    "Total Receiving Yards": "rec_yds",
    "Total Receptions": "rec",
    "Total Rushing Yards": "rush_yds",
    "Total Carries": "car",
    "Total Passing Yards": "pass_yds",
    "Total Passing Attempts": "att",
    "Total Pass Completions": "cmp",
    "Total Passing Touchdowns": "pass_td",
    "Total Passing Interceptions": "ints",
}


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def market_of(name: str) -> str | None:
    base = re.sub(r"\s*\(incl\. overtime\)\s*$", "", name or "").strip()
    return MARKETS.get(base)


def game_lines(event_id: str) -> list[dict]:
    """One game's over/under prop lines: [{event, athlete (ESPN id), stat, line, open}]."""
    out, seen, page = [], set(), 1
    while True:
        try:
            d = _get(f"{CORE}/events/{event_id}/competitions/{event_id}/odds/100/propBets?limit=1000&page={page}")
        except Exception:
            break
        for it in d.get("items", []):
            stat = market_of(it.get("type", {}).get("name", ""))
            m = re.search(r"/athletes/(\d+)", (it.get("athlete") or {}).get("$ref", ""))
            line = ((it.get("current") or {}).get("target") or {}).get("value")
            if not (stat and m and isinstance(line, (int, float))):
                continue
            key = (m.group(1), stat)
            if key in seen:  # over and under are listed separately with the same line
                continue
            seen.add(key)
            opened = ((it.get("open") or {}).get("target") or {}).get("value")
            out.append({"event": str(event_id), "athlete": m.group(1), "stat": stat, "line": float(line), "open": float(opened) if isinstance(opened, (int, float)) else None})
        if page >= int(d.get("pageCount") or 1):
            break
        page += 1
    return out


def week_lines(event_ids: list[str]) -> list[dict]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        return [row for rows in pool.map(game_lines, event_ids) for row in rows]


def main():
    import pandas as pd

    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--weeks", required=True, help="e.g. 1-4")
    ap.add_argument("--games", default="https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    games = pd.read_csv(args.games, low_memory=False)
    first, _, last = args.weeks.partition("-")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for week in range(int(first), int(last or first) + 1):
        ids = [str(int(e)) for e in games[(games["season"] == args.season) & (games["week"] == week) & games["espn"].notna()]["espn"]]
        rows = week_lines(ids)
        (out / f"{args.season}-w{week}.json").write_text(json.dumps(rows, separators=(",", ":")))
        print(f"week {week}: {len(rows)} lines from {len(ids)} games")


if __name__ == "__main__":
    main()
