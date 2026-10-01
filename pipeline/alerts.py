"""
Injury notifications for BetTracker, made on the server so they reach phones
(BetTracker's database sends each new notification as a push).

  - A player on someone's open NFL bet (props, prop legs) is doubtful or out.
  - A team in an open spread/total/moneyline bet is without its starting QB.
  - A starter in someone's Sleeper lineup is doubtful or out (for people who
    linked Sleeper in the app; their username is on their profile).

Only this week's injury report counts, for games that haven't started. Each
alert has a key (bet or league, player, status, week), so it's sent once; a
downgrade from doubtful to out is a new alert. Run from picks.py.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta

import pandas as pd

SERIOUS = ("Out", "Doubtful")
SLEEPER = "https://api.sleeper.app/v1"


def _when(s) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _why(inj: dict) -> str:
    return f" ({inj['injury'].lower()})" if inj.get("injury") else ""


def bet_alerts(bets: list[dict], injuries: dict, espn_to_gsis: dict, names: dict, event_week: dict, event_teams: dict, main_qb: dict, now: datetime) -> list[dict]:
    """Notification rows for open bets. event_week/event_teams: ESPN event id -> week / (home, away)."""
    out = []
    for b in bets:
        legs = [{"player_id": b.get("player_id"), "player": b.get("subject"), "event_id": b.get("event_id"), "event_start": b.get("event_start")}] if b.get("bet_type") == "prop" else []
        legs += [
            {**leg, "event_id": leg.get("event_id") or b.get("event_id"), "event_start": leg.get("event_start") or b.get("event_start")}
            for leg in (b.get("legs") or [])
            if leg.get("kind") == "prop" and not leg.get("result") and (leg.get("sport_path") or b.get("sport_path")) == "football/nfl"
        ]
        seen = set()
        for leg in legs:
            start = _when(leg.get("event_start"))
            gsis = espn_to_gsis.get(str(leg.get("player_id") or ""))
            week = event_week.get(str(leg.get("event_id") or ""))
            inj = injuries.get(gsis) if gsis else None
            if not (start and start > now and inj and inj["status"] in SERIOUS and inj["week"] == week) or gsis in seen:
                continue
            seen.add(gsis)
            out.append(_row(b, f"bet:{b['id']}:{gsis}:{inj['status']}", f"{inj['status']}: {names.get(gsis, leg.get('player') or 'A player')}{_why(inj)} · on your bet {b['selection']}"))
        # Straight bets on a game: a missing starting QB.
        if b.get("bet_type") in ("spread", "total", "moneyline") and b.get("sport_path") == "football/nfl":
            start, eid = _when(b.get("event_start")), str(b.get("event_id") or "")
            if not (start and start > now) or eid not in event_teams:
                continue
            for team in event_teams[eid]:
                qb = main_qb.get(team)
                inj = injuries.get(qb) if qb else None
                if inj and inj["status"] in SERIOUS and inj["week"] == event_week.get(eid):
                    out.append(_row(b, f"qb:{b['id']}:{qb}:{inj['status']}", f"{inj['status']}: {team} QB {names.get(qb, '')}{_why(inj)} · on your bet {b['selection']}".replace("QB  (", "QB (")))
    return out


def lineup_alerts(user_id: str, lineups: list[dict], injuries: dict, sleeper_to_gsis: dict, names: dict, week: int) -> list[dict]:
    """Notification rows for one person's Sleeper starters. lineups: [{league_id, name, starters}]."""
    out = []
    for lg in lineups:
        for sid in lg["starters"]:
            gsis = sleeper_to_gsis.get(str(sid))
            inj = injuries.get(gsis) if gsis else None
            if not (inj and inj["status"] in SERIOUS and inj["week"] == week):
                continue
            out.append({
                "user_id": user_id, "actor_id": user_id, "type": "injury", "bet_id": None,
                "dedupe_key": f"lineup:{lg['league_id']}:{sid}:{inj['status']}:w{week}",
                "body": f"{inj['status']}: {names.get(gsis, 'A starter')}{_why(inj)} · starting in {lg['name']}",
            })
    return out


def _row(bet: dict, key: str, body: str) -> dict:
    return {"user_id": bet["user_id"], "actor_id": bet["user_id"], "type": "injury", "bet_id": bet["id"], "dedupe_key": key, "body": body}


def sleeper_lineups(username: str, season: int, get_json) -> list[dict]:
    """Someone's starters in each of their Sleeper leagues this season (public API, no key)."""
    user = get_json(f"{SLEEPER}/user/{urllib.parse.quote(username)}")
    if not user:
        return []
    out = []
    for lg in get_json(f"{SLEEPER}/user/{user['user_id']}/leagues/nfl/{season}") or []:
        rosters = get_json(f"{SLEEPER}/league/{lg['league_id']}/rosters") or []
        mine = next((r for r in rosters if r.get("owner_id") == user["user_id"]), None)
        if mine:
            out.append({"league_id": lg["league_id"], "name": lg["name"], "starters": [s for s in (mine.get("starters") or []) if s and s != "0"]})
    return out


def run(db, games: pd.DataFrame, roster: pd.DataFrame, injuries: dict, main_qb: dict, season: int, week: int, now: datetime, get_json) -> int:
    """Finds and inserts new injury notifications; returns how many were new candidates."""
    espn_to_gsis = {str(int(r["espn_id"])): r["gsis_id"] for _, r in roster.iterrows() if pd.notna(r.get("espn_id"))}
    sleeper_to_gsis = {str(int(r["sleeper_id"])): r["gsis_id"] for _, r in roster.iterrows() if pd.notna(r.get("sleeper_id"))}
    names = dict(zip(roster["gsis_id"], roster["full_name"]))
    cur = games[(games["season"] == season) & games["espn"].notna()]
    event_week = {str(int(g["espn"])): int(g["week"]) for _, g in cur.iterrows()}
    event_teams = {str(int(g["espn"])): (g["home_team"], g["away_team"]) for _, g in cur.iterrows()}

    since = urllib.parse.quote((now - timedelta(days=14)).isoformat())
    bets = db.select(
        "bets",
        "select=id,user_id,selection,bet_type,sport_path,player_id,subject,legs,event_id,event_start,pick_team_id"
        f"&status=eq.pending&placed_at=gte.{since}&or=(sport_path.eq.football/nfl,bet_type.eq.parlay)",
    )
    rows = bet_alerts(bets, injuries, espn_to_gsis, names, event_week, event_teams, main_qb, now)
    for p in db.select("profiles", "select=id,sleeper_username&sleeper_username=not.is.null"):
        try:
            rows += lineup_alerts(p["id"], sleeper_lineups(p["sleeper_username"], season, get_json), injuries, sleeper_to_gsis, names, week)
        except Exception as e:  # one bad username shouldn't stop the rest
            print(f"  sleeper lineup skipped: {e}")
    if rows:
        # Already-sent alerts (same key) are skipped by the database.
        db.insert("notifications", rows, on_conflict="user_id,dedupe_key")
    return len(rows)
