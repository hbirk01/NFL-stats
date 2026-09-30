"""
The BetTracker model's live picks, posted as the Model account so they show
up in the feed and are graded like anyone's bets.

Each run (see .github/workflows/model.yml):
  1. Games starting within the next 36 hours that the model hasn't bet yet.
  2. Ratings and predictions from pipeline/model.py, calibrated on last season.
  3. Weather at kickoff (Open-Meteo, free) for outdoor games; the starting QB
     counted out if the latest injury report has him out or doubtful.
  4. Bets at DraftKings' current line (via ESPN): totals at a 4+ point edge,
     spreads at 4+ points. No moneylines (unreliable in backtests).
  5. Props: the open NFL props your friends logged, handicapped from each
     player's games this season and last against the opponent's defense;
     bets the side the projection favors by 15%+.
Flat 1-unit ($10) stakes; the reasoning goes in each bet's notes.

  python pipeline/picks.py --dry-run          # print, don't post
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... MODEL_USER_ID=... python pipeline/picks.py
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from build import defense_outlook, defense_vs_position, game_lines, injury_map, read, real_plays  # noqa: E402
from model import GAMES_CSV, Params, Ratings, fit, load, pbp_for, predict, run, team_games  # noqa: E402

STAKE = 10.0
WINDOW = timedelta(hours=36)
SPREAD_EDGE = 4.0
TOTAL_EDGE = 4.0
PROP_EDGE = 0.15
MAX_PROPS = 8
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"

# Prop stat id -> per-game column from build.game_lines.
PROP_COLS = {
    "nfl_pass_yds": "pass_yds", "nfl_pass_td": "pass_td", "nfl_pass_cmp": "cmp", "nfl_pass_att": "att", "nfl_pass_int": "ints",
    "nfl_rush_yds": "rush_yds", "nfl_rush_att": "car", "nfl_rec": "rec", "nfl_rec_yds": "rec_yds", "nfl_targets": "tgt",
}
PROP_LABELS = {
    "nfl_pass_yds": "Passing Yards", "nfl_pass_td": "Passing TDs", "nfl_pass_cmp": "Pass Completions", "nfl_pass_att": "Passing Attempts",
    "nfl_pass_int": "Interceptions Thrown", "nfl_rush_yds": "Rushing Yards", "nfl_rush_att": "Rushing Attempts", "nfl_rec": "Receptions",
    "nfl_rec_yds": "Receiving Yards", "nfl_targets": "Targets", "nfl_rush_rec_yds": "Rush + Rec Yards",
}


# ── Outside data ─────────────────────────────────────────────────────────────

def get_json(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def espn_week(season: int, week: int) -> dict:
    """ESPN event id -> start, team ids/names, DraftKings odds, indoor and city."""
    data = get_json(f"{ESPN}/scoreboard?dates={season}&seasontype=2&week={week}&limit=40")
    out = {}
    for e in data.get("events", []):
        c = e["competitions"][0]
        teams = {t["homeAway"]: t for t in c["competitors"]}
        o = (c.get("odds") or [{}])[0]

        def odds_at(*path):
            cur = o
            for k in path:
                cur = cur.get(k) if isinstance(cur, dict) else None
            try:
                return float(str(cur).replace("+", "")) if cur not in (None, "", "OFF") else None
            except ValueError:
                return None

        addr = c.get("venue", {}).get("address", {})
        out[e["id"]] = {
            "start": datetime.fromisoformat(e["date"].replace("Z", "+00:00")),
            "state": e["status"]["type"]["state"],
            "home": {"id": teams["home"]["team"]["id"], "name": teams["home"]["team"]["displayName"], "abbr": teams["home"]["team"]["abbreviation"]},
            "away": {"id": teams["away"]["team"]["id"], "name": teams["away"]["team"]["displayName"], "abbr": teams["away"]["team"]["abbreviation"]},
            # ESPN's spread is the home team's line (+2.5 = home getting 2.5).
            "home_line": o.get("spread"),
            "total": o.get("overUnder"),
            "home_spread_odds": odds_at("pointSpread", "home", "close", "odds"),
            "away_spread_odds": odds_at("pointSpread", "away", "close", "odds"),
            "over_odds": odds_at("total", "over", "close", "odds"),
            "under_odds": odds_at("total", "under", "close", "odds"),
            "indoor": bool(c.get("venue", {}).get("indoor")),
            "city": ", ".join(x for x in (addr.get("city"), addr.get("state")) if x),
        }
    return out


def kickoff_weather(city: str, when: datetime) -> tuple[float | None, float | None]:
    """(wind mph, temp F) at kickoff from Open-Meteo's free forecast; (None, None) if unavailable."""
    try:
        name = city.split(",")[0]
        geo = get_json(f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(name)}&count=1&country=US")
        if not geo.get("results"):
            return None, None
        lat, lon = geo["results"][0]["latitude"], geo["results"][0]["longitude"]
        f = get_json(
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=wind_speed_10m,temperature_2m"
            f"&wind_speed_unit=mph&temperature_unit=fahrenheit&timezone=UTC&forecast_days=3"
        )
        hour = when.strftime("%Y-%m-%dT%H:00")
        times = f["hourly"]["time"]
        if hour not in times:
            return None, None
        i = times.index(hour)
        return float(f["hourly"]["wind_speed_10m"][i]), float(f["hourly"]["temperature_2m"][i])
    except Exception:
        return None, None


class Supabase:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def select(self, table: str, query: str) -> list:
        return get_json(f"{self.url}/rest/v1/{table}?{query}", self.headers)

    def insert(self, table: str, rows: list[dict]) -> None:
        req = urllib.request.Request(
            f"{self.url}/rest/v1/{table}", data=json.dumps(rows).encode(), method="POST", headers={**self.headers, "Prefer": "return=minimal"}
        )
        with urllib.request.urlopen(req, timeout=20):
            pass


# ── Bets ─────────────────────────────────────────────────────────────────────

def payout(stake: float, odds: float) -> float:
    return round(stake + (stake * odds / 100 if odds > 0 else stake * 100 / -odds), 2)


def confidence(edge: float, step: float) -> int:
    """1-5 stars from how far past the threshold the edge is."""
    return max(1, min(5, 2 + int(edge // step)))


def game_picks(week: int, games: pd.DataFrame, espn: dict, ratings: Ratings, p: Params, now: datetime, injuries: dict) -> list[dict]:
    rows = []
    at = ratings.at(week)
    for _, g in games.iterrows():
        e = espn.get(str(int(g["espn"]))) if pd.notna(g.get("espn")) else None
        if not e or e["state"] != "pre" or not (now < e["start"] <= now + WINDOW):
            continue
        if e["home_line"] is None or e["total"] is None:
            continue
        game = g.copy()
        # nflverse's spread is "home favored by"; ESPN's is the home team's line.
        game["spread_line"] = -float(e["home_line"])
        game["total_line"] = float(e["total"])
        for side in ("home", "away"):
            usual = ratings.main_qb.get(g[f"{side}_team"])
            out = usual and injuries.get(usual, {}).get("status") in ("Out", "Doubtful")
            game[f"{side}_qb_id"] = "backup" if out else usual
        wind, temp = (None, None) if e["indoor"] else kickoff_weather(e["city"], e["start"])
        game["wind"], game["temp"] = wind, temp
        game["roof"] = "dome" if e["indoor"] else "outdoors"
        margin, total = predict(game, at, ratings.lg, ratings.main_qb, p)
        matchup = f"{e['away']['abbr']} @ {e['home']['abbr']}"
        weather = f" Kickoff: {round(wind)} mph wind, {round(temp)}°F." if wind is not None and temp is not None else " Indoors." if e["indoor"] else ""
        qb_note = "".join(f" {g[f'{s}_team']} without its starting QB." for s in ("home", "away") if game[f"{s}_qb_id"] == "backup")
        base = {
            "sportsbook": "draftkings", "sport": "NFL", "event_description": matchup, "stake": STAKE, "is_public": True,
            "event_id": e and str(int(g["espn"])), "sport_path": "football/nfl", "event_start": e["start"].isoformat(),
        }
        # Total
        tedge = total - game["total_line"]
        if abs(tedge) >= TOTAL_EDGE:
            side = "over" if tedge > 0 else "under"
            odds = e[f"{side}_odds"] or -110
            rows.append({
                **base, "bet_type": "total", "selection": f"{'Over' if side == 'over' else 'Under'} {game['total_line']}", "odds": odds,
                "potential_payout": payout(STAKE, odds), "line": game["total_line"], "side": side, "confidence": confidence(abs(tedge) - TOTAL_EDGE, 2),
                "notes": f"Model total {total:.1f} vs line {game['total_line']} ({tedge:+.1f}).{weather}{qb_note}",
            })
        # Spread (the model's home margin vs the market's)
        sedge = margin - game["spread_line"]
        if abs(sedge) >= SPREAD_EDGE:
            side = "home" if sedge > 0 else "away"
            team = e[side]
            line = -game["spread_line"] if side == "home" else game["spread_line"]
            odds = e[f"{side}_spread_odds"] or -110
            fav = e["home"]["abbr"] if margin > 0 else e["away"]["abbr"]
            rows.append({
                **base, "bet_type": "spread", "selection": f"{team['name']} {line:+g}", "subject": team["name"], "pick_team_id": team["id"], "line": line,
                "odds": odds, "potential_payout": payout(STAKE, odds), "confidence": confidence(abs(sedge) - SPREAD_EDGE, 2),
                "notes": f"Model has {fav} by {abs(margin):.1f}; line {e['home']['abbr']} {-game['spread_line']:+g} ({abs(sedge):.1f} pt edge).{weather}{qb_note}",
            })
    return rows


def prop_picks(open_bets: list, roster: pd.DataFrame, lines_cur: pd.DataFrame, lines_prev: pd.DataFrame | None, defense: dict, now: datetime) -> list[dict]:
    """The model's side of the props friends logged, where its projection disagrees with the line by 15%+."""
    espn_to = {str(int(r["espn_id"])): r for _, r in roster.iterrows() if pd.notna(r.get("espn_id"))}
    avg_allowed = {pos: sum(r["ppg_ros"] or 0 for r in rows) / max(1, len(rows)) for pos, rows in defense.items()}
    seen, rows = set(), []
    props = []
    for b in open_bets:
        if b["bet_type"] == "prop":
            props.append(b)
        for leg in b.get("legs") or []:
            if leg.get("kind") == "prop" and not leg.get("result"):
                props.append({**leg, "subject": leg.get("player"), "event_id": leg.get("event_id") or b.get("event_id"), "event_start": leg.get("event_start") or b.get("event_start"), "odds": leg.get("odds")})
    for b in props:
        pid, stat, line = b.get("player_id"), b.get("prop_stat"), b.get("line")
        if not (pid and stat and line is not None and b.get("event_id") and b.get("event_start")) or stat not in PROP_LABELS:
            continue
        start = datetime.fromisoformat(str(b["event_start"]).replace("Z", "+00:00"))
        if not (now < start <= now + WINDOW):
            continue
        key = (pid, stat, float(line))
        if key in seen or pid not in espn_to:
            continue
        seen.add(key)
        r = espn_to[pid]
        gsis, pos, team = r["gsis_id"], r["position"], r["team"]

        def values(lines):
            if lines is None:
                return []
            mine = lines[lines["id"] == gsis]
            if stat == "nfl_rush_rec_yds":
                return list(mine["rush_yds"] + mine["rec_yds"])
            return list(mine[PROP_COLS[stat]])

        cur, prev = values(lines_cur), values(lines_prev)
        if len(cur) + len(prev) < 3:
            continue
        n = len(cur)
        mean_cur = sum(cur) / n if n else 0
        mean_prev = sum(prev) / len(prev) if prev else mean_cur
        proj = (mean_cur * n + mean_prev * 3) / (n + 3)
        # The opponent: how much it allows to the position vs average (capped at +/-10%).
        opp = None
        g = lines_cur[lines_cur["id"] == gsis].sort_values("week").tail(1)
        if len(g):
            opp_row = next((x for x in defense.get(pos, []) if x["team"] == g.iloc[0]["opp"]), None)
            opp = opp_row
        factor = 1.0
        if opp and avg_allowed.get(pos):
            factor = max(0.9, min(1.1, (opp["ppg_ros"] or avg_allowed[pos]) / avg_allowed[pos]))
        proj *= factor
        line = float(line)
        if line < 1.5:
            continue
        rel = (proj - line) / line
        if abs(rel) < PROP_EDGE:
            continue
        side = "over" if rel > 0 else "under"
        name = b.get("subject") or r["full_name"]
        rows.append({
            "sportsbook": "draftkings", "sport": "NFL", "event_description": b.get("event_description") or f"{team} game", "stake": STAKE, "is_public": True,
            "bet_type": "prop", "selection": f"{name} {PROP_LABELS[stat]} {'Over' if side == 'over' else 'Under'} {line:g}", "subject": name,
            "player_id": pid, "prop_stat": stat, "line": line, "side": side, "odds": -115, "potential_payout": payout(STAKE, -115),
            "event_id": b["event_id"], "sport_path": "football/nfl", "event_start": b["event_start"], "confidence": confidence(abs(rel) - PROP_EDGE, 0.1),
            "notes": f"Model projects {proj:.1f} (this season {mean_cur:.1f} in {n}, last {mean_prev:.1f}) vs {line:g}. Odds assumed -115.",
        })
    rows.sort(key=lambda x: -x["confidence"])
    return rows[:MAX_PROPS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--window-hours", type=float, default=36, help="bet games starting within this many hours")
    args = ap.parse_args()
    raw = Path(args.raw)
    raw.mkdir(parents=True, exist_ok=True)
    global WINDOW
    WINDOW = timedelta(hours=args.window_hours)
    now = datetime.now(timezone.utc)
    season = now.year if now.month >= 9 else now.year - 1

    games = load(raw, "games.csv", GAMES_CSV)
    pbp_cur, pbp_prev, pbp_prev2 = pbp_for(raw, season), pbp_for(raw, season - 1), pbp_for(raw, season - 2)
    tg_cur, tg_prev, tg_prev2 = team_games(pbp_cur), team_games(pbp_prev), team_games(pbp_prev2)
    # Calibrate on last season (as in the backtest), then rate this season.
    p = fit(run(games, tg_prev, tg_prev2, season - 1, Params()), Params())
    p = Params(**{**p.__dict__, "spread_edge": SPREAD_EDGE, "total_edge": TOTAL_EDGE})
    ratings = Ratings(tg_cur, tg_prev)

    upcoming = games[(games["season"] == season) & (games["game_type"] == "REG") & games["result"].isna()]
    injuries = injury_map(read(raw, f"injuries/injuries_{season}.parquet"))
    week = int(upcoming["week"].min()) if len(upcoming) else None
    if week is None:
        print("No games left")
        return
    espn = espn_week(season, week)
    wk_games = upcoming[upcoming["week"] == week]
    picks = game_picks(week, wk_games, espn, ratings, p, now, injuries)

    db = None
    model_user = os.environ.get("MODEL_USER_ID")
    if not args.dry_run:
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not (url and key and model_user):
            raise SystemExit("Set SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and MODEL_USER_ID (or use --dry-run)")
        db = Supabase(url, key)

    # Props on friends' open lines (needs the database).
    if db:
        since = (now - timedelta(days=7)).isoformat()
        open_bets = db.select(
            "bets",
            "select=bet_type,player_id,subject,prop_stat,line,side,event_id,event_start,event_description,odds,legs"
            f"&status=eq.pending&sport_path=eq.football/nfl&user_id=neq.{model_user}&club_id=is.null&placed_at=gte.{urllib.parse.quote(since)}",
        )
        open_bets += db.select(
            "bets",
            f"select=bet_type,event_id,event_start,event_description,legs&status=eq.pending&bet_type=eq.parlay&user_id=neq.{model_user}&club_id=is.null&placed_at=gte.{urllib.parse.quote(since)}",
        )
        roster = read(raw, f"rosters/roster_{season}.parquet")
        roster = roster.sort_values("week").drop_duplicates("gsis_id", keep="last")
        lines_cur = game_lines(real_plays(pbp_cur), pbp_cur)
        lines_prev = game_lines(real_plays(pbp_prev), pbp_prev)
        pos_of = dict(zip(roster["gsis_id"], roster["position"]))
        prev_roster = read(raw, f"rosters/roster_{season - 1}.parquet")
        prev_pos = dict(zip(prev_roster["gsis_id"], prev_roster["position"])) if prev_roster is not None else {}
        defense = defense_outlook(defense_vs_position(lines_cur, pos_of), defense_vs_position(lines_prev, prev_pos), int(pbp_cur["week"].max()))
        picks += prop_picks(open_bets, roster, lines_cur, lines_prev, defense, now)

    if db:
        # Never bet the same thing twice.
        mine = db.select("bets", f"select=event_id,bet_type,player_id,prop_stat&user_id=eq.{model_user}&placed_at=gte.{urllib.parse.quote((now - timedelta(days=10)).isoformat())}")
        have = {(b["event_id"], b["bet_type"], b.get("player_id"), b.get("prop_stat")) for b in mine}
        picks = [x for x in picks if (x["event_id"], x["bet_type"], x.get("player_id"), x.get("prop_stat")) not in have]
        if picks:
            db.insert("bets", [{**x, "user_id": model_user} for x in picks])
    print(f"Week {week}: {len(picks)} new pick(s)")
    for x in picks:
        print(f"  {x['event_description']:<12} {x['selection']:<40} {x['odds']:+g}  {'*' * x['confidence']}  {x['notes']}")


if __name__ == "__main__":
    main()
