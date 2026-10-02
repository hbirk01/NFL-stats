"""
The BetTracker model's live picks, posted as the Model account so they show
up in the feed and are graded like anyone's bets.

Each run (see .github/workflows/model.yml):
  1. Games starting within the next 36 hours that the model hasn't bet yet.
  2. Ratings and predictions from pipeline/model.py, calibrated on last season.
  3. Weather at kickoff (Open-Meteo, free) for outdoor games; the starting QB
     counted out if the latest injury report has him out or doubtful.
  4. Game lines: spreads and totals 4+ points off DraftKings' current line
     (via ESPN), bet only if that market's measured record clears
     MIN_CONFIDENCE (55%; game_confidence.json, from walk-forward runs).
     Otherwise they're printed as leans. No moneylines.
  5. Props: DraftKings' player lines and the props friends logged, against
     the prop model (pipeline/props.py). Unders only, where it gives the over
     a 25-42% chance, in a range whose unders have won 55%+ this season; most
     confident first, one per player, by slot: one each for Thursday, Sunday
     and Monday night, three each for Sunday early and late (one per game).
Flat 1-unit ($10) stakes; the reasoning goes in each bet's notes.

  python pipeline/picks.py --dry-run          # print, don't post
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... MODEL_USER_ID=... python pipeline/picks.py
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import alerts  # noqa: E402
import props  # noqa: E402
from build import injury_map, read  # noqa: E402
from model import GAME_CONFIDENCE_FILE, GAMES_CSV, MIN_CONFIDENCE, Params, Ratings, build_qb_ratings, fit, live_offset, live_starters, load, pbp_for, predict, run, team_games  # noqa: E402

STAKE = 10.0
WINDOW = timedelta(hours=36)
SPREAD_EDGE = 4.0
TOTAL_EDGE = 4.0
# Prop picks per slot of the week: one for each prime-time game, three each for
# Sunday's early and late windows (one per game there), one for any other day
# (late-season Saturdays, holidays). Times in US Eastern.
SLOTS = {"tnf": 1, "early": 3, "late": 3, "snf": 1, "mnf": 1, "other": 1}
SLOT_NAME = {"tnf": "Thursday night", "early": "Sunday early", "late": "Sunday late", "snf": "Sunday night", "mnf": "Monday night", "other": "the extra games"}
ONE_PER_GAME = {"early", "late"}


def slot_of(start: datetime) -> str:
    """Which slot of the NFL week a kickoff falls in."""
    et = start.astimezone(ZoneInfo("America/New_York"))
    day = et.weekday()  # Monday = 0
    if day == 3:
        return "tnf"
    if day == 0:
        return "mnf"
    if day == 6:
        return "snf" if et.hour >= 19 else "late" if et.hour >= 15 else "early"
    return "other"
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

    def insert(self, table: str, rows: list[dict], on_conflict: str | None = None) -> None:
        """Inserts rows; with on_conflict, rows matching an existing one on those columns are skipped."""
        query = f"?on_conflict={on_conflict}" if on_conflict else ""
        prefer = "return=minimal" + (",resolution=ignore-duplicates" if on_conflict else "")
        req = urllib.request.Request(
            f"{self.url}/rest/v1/{table}{query}", data=json.dumps(rows).encode(), method="POST", headers={**self.headers, "Prefer": prefer}
        )
        with urllib.request.urlopen(req, timeout=20):
            pass


# ── Bets ─────────────────────────────────────────────────────────────────────

def payout(stake: float, odds: float) -> float:
    return round(stake + (stake * odds / 100 if odds > 0 else stake * 100 / -odds), 2)


def confidence(edge: float, step: float) -> int:
    """1-5 stars from how far past the threshold the edge is."""
    return max(1, min(5, 2 + int(edge // step)))


def game_picks(week: int, games: pd.DataFrame, espn: dict, ratings: Ratings, p: Params, now: datetime, injuries: dict, offset: float = 0.0) -> list[dict]:
    """Spread and total picks; `offset` centers the model's totals on the market's (see model.total_offset)."""
    rows = []
    at = ratings.at(week, live_starters(games, ratings.main_qb, injuries))
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
        total += offset
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


PROPS_JSON = "https://raw.githubusercontent.com/hbirk01/NFL-stats/data/props.json"


def prop_picks(up: dict, espn: dict, open_bets: list, posted: list[str], now: datetime, table: list | None = None) -> list[dict]:
    """
    Player prop unders from the prop model (pipeline/props.py): DraftKings'
    lines, plus lines friends logged. Only where the model gives the over
    between UNDER_FLOOR and UNDER_AT (its overs didn't win in testing, and a
    far-off line usually means news it doesn't have), games within the window,
    one per player. The most confident first (the range whose unders have won
    most so far: props.confidence_table, published with props.json), filling
    each slot of the week (SLOTS) up to its quota; `posted` is the event ids of
    this week's prop picks already made, which count toward their slots.
    """
    stat_id = {v: k for k, v in PROP_COLS.items()}
    proj = up.get("_proj", {})
    cands = []
    for x in up["props"]:
        cands.append({"espn": x["espn"], "stat": x["stat"], "line": x["line"], "event": x["event"], "source": "DraftKings"})
    for b in open_bets:
        legs = [b] if b.get("bet_type") == "prop" else [leg for leg in (b.get("legs") or []) if leg.get("kind") == "prop"]
        for leg in legs:
            col = PROP_COLS.get(leg.get("prop_stat") or "")
            if col and leg.get("player_id") and leg.get("line") is not None and (leg.get("event_id") or b.get("event_id")):
                cands.append({"espn": str(leg["player_id"]), "stat": col, "line": float(leg["line"]), "event": str(leg.get("event_id") or b.get("event_id")), "source": "a friend's bet"})
    spread = json.loads(props.SPREAD_FILE.read_text())
    rows, seen = [], set()
    for c in cands:
        p = proj.get(c["espn"])
        e = espn.get(c["event"])
        if not p or not e or e["state"] != "pre" or not (now < e["start"] <= now + WINDOW) or c["stat"] not in stat_id:
            continue
        po = props.p_over(spread, c["stat"], p[c["stat"]], c["line"])
        if po is None or not (props.UNDER_FLOOR < po <= props.UNDER_AT):
            continue
        cands_key = c["espn"]
        conf = props.confidence_of(table, po)
        c.update(p_over=po, median=props.median(spread, c["stat"], p[c["stat"]]), name=p["name"], inputs=p["inputs"], game=e, conf=conf["rate"] if conf else props.BREAK_EVEN)
        if cands_key not in seen:
            rows.append(c)
            seen.add(cands_key)
    # Only what has won enough, most confident first, filling each slot of the week.
    rows = [c for c in rows if c["conf"] >= MIN_CONFIDENCE]
    rows.sort(key=lambda c: (-c["conf"], c["p_over"]))
    per_slot, per_game = Counter(), Counter(posted)
    for event in posted:
        if event in espn:
            per_slot[slot_of(espn[event]["start"])] += 1
    chosen = []
    for c in rows:
        slot = slot_of(c["game"]["start"])
        if per_slot[slot] >= SLOTS[slot] or (slot in ONE_PER_GAME and per_game[c["event"]] >= 1):
            continue
        per_slot[slot] += 1
        per_game[c["event"]] += 1
        chosen.append({**c, "slot": slot})
    rows = chosen
    out = []
    for c in rows:
        label = PROP_LABELS[stat_id[c["stat"]]]
        i = c["inputs"]
        why = (
            f"{i['tgt']:.1f} targets ({i['tgt_share']:.0%} of {i['team_att']:.0f} team passes)" if c["stat"] in ("rec", "rec_yds")
            else f"{i['car']:.1f} carries ({i['car_share']:.0%} of {i['team_car']:.0f} team rushes)" if c["stat"] in ("rush_yds", "car")
            else f"{i['att']:.0f} attempts"
        )
        out.append({
            "sportsbook": "draftkings", "sport": "NFL", "event_description": f"{c['game']['away']['abbr']} @ {c['game']['home']['abbr']}", "stake": STAKE, "is_public": True,
            "bet_type": "prop", "selection": f"{c['name']} {label} Under {c['line']:g}", "subject": c["name"],
            "player_id": c["espn"], "prop_stat": stat_id[c["stat"]], "line": c["line"], "side": "under", "odds": -115, "potential_payout": payout(STAKE, -115),
            "event_id": c["event"], "sport_path": "football/nfl", "event_start": c["game"]["start"].isoformat(), "confidence": max(1, min(5, round((c["conf"] - props.BREAK_EVEN) / 0.015) + 2)),
            "notes": f"{SLOT_NAME[c['slot']]} pick. Model median {c['median']:.1f} vs {c['line']:g} ({c['p_over']:.0%} to go over), from {why}. Unders like this have won {c['conf']:.0%} so far. Line from {c['source']}; odds assumed -115.",
        })
    return out


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
    qbr = build_qb_ratings([pbp_prev2, pbp_prev, pbp_cur])
    p = fit(run(games, tg_prev, tg_prev2, season - 1, Params(), qbr=qbr), Params())
    p = Params(**{**p.__dict__, "spread_edge": SPREAD_EDGE, "total_edge": TOTAL_EDGE})
    ratings = Ratings(tg_cur, tg_prev, qbr)

    upcoming = games[(games["season"] == season) & (games["game_type"] == "REG") & games["result"].isna()]
    injuries = injury_map(read(raw, f"injuries/injuries_{season}.parquet"))
    week = int(upcoming["week"].min()) if len(upcoming) else None
    if week is None:
        print("No games left")
        return
    espn = espn_week(season, week)
    wk_games = upcoming[upcoming["week"] == week]
    offset = live_offset(games, tg_cur, tg_prev, tg_prev2, season, p, week, qbr)
    picks = game_picks(week, wk_games, espn, ratings, p, now, injuries, offset)
    # Game lines are bet only in a market whose measured record clears the bar.
    conf = json.loads(GAME_CONFIDENCE_FILE.read_text()) if GAME_CONFIDENCE_FILE.exists() else {}
    held = [x for x in picks if conf.get(x["bet_type"], {}).get("rate", 0) < MIN_CONFIDENCE]
    if held:
        rates = ", ".join(f"{m}s {conf[m]['rate']:.1%} ({conf[m]['won']}-{conf[m]['lost']})" for m in ("spread", "total") if m in conf)
        print(f"Game leans not bet ({len(held)}): below {MIN_CONFIDENCE:.0%} confidence ({rates})")
        for x in held:
            print(f"  lean  {x['event_description']:<12} {x['selection']:<30} {x['notes']}")
    picks = [x for x in picks if x not in held]

    db = None
    model_user = os.environ.get("MODEL_USER_ID")
    if not args.dry_run:
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not (url and key and model_user):
            raise SystemExit("Set SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and MODEL_USER_ID (or use --dry-run)")
        db = Supabase(url, key)

    # Props: DraftKings' lines and friends' logged lines (those need the database).
    open_bets, posted = [], []
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
        # Prop picks already posted for this week's games count toward the weekly cap.
        week_events = {str(int(e)) for e in games[(games["season"] == season) & (games["week"] == week) & games["espn"].notna()]["espn"]}
        posted = [b["event_id"] for b in db.select("bets", f"select=event_id&user_id=eq.{model_user}&bet_type=eq.prop&placed_at=gte.{urllib.parse.quote((now - timedelta(days=8)).isoformat())}") if b["event_id"] in week_events]
    try:
        up = props.upcoming(raw, season, games)
        if up and up["week"] == week:
            try:
                table = get_json(PROPS_JSON).get("confidence")
            except Exception:
                table = None
            picks += prop_picks(up, espn, open_bets, posted, now, table)
    except Exception as e:  # the game picks still go out
        print(f"Prop picks skipped: {e}")

    if db:
        # Never bet the same thing twice.
        mine = db.select("bets", f"select=event_id,bet_type,player_id,prop_stat&user_id=eq.{model_user}&placed_at=gte.{urllib.parse.quote((now - timedelta(days=10)).isoformat())}")
        have = {(b["event_id"], b["bet_type"], b.get("player_id"), b.get("prop_stat")) for b in mine}
        picks = [x for x in picks if (x["event_id"], x["bet_type"], x.get("player_id"), x.get("prop_stat")) not in have]
        if picks:
            db.insert("bets", [{**x, "user_id": model_user} for x in picks])
    print(f"Week {week}: {len(picks)} new pick(s)")
    if db:
        # Injury notifications (pushed to phones). Never let them stop the picks.
        try:
            roster_now = read(raw, f"rosters/roster_{season}.parquet").sort_values("week").drop_duplicates("gsis_id", keep="last")
            n = alerts.run(db, games, roster_now, injuries, ratings.main_qb, season, week, now, get_json)
            print(f"Injury alerts: {n} checked")
        except Exception as e:
            print(f"Injury alerts skipped: {e}")
    for x in picks:
        print(f"  {x['event_description']:<12} {x['selection']:<40} {x['odds']:+g}  {'*' * x['confidence']}  {x['notes']}")


if __name__ == "__main__":
    main()
