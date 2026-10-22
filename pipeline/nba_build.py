"""
The NBA stats BetTracker reads, published under nba/ on the data branch next to
the NFL files. Box scores come from sportsdataverse's hoopR data (ESPN's, one
parquet per season, refreshed daily; ESPN athlete ids throughout, the same ids
bets and DraftKings' lines use); today's games and lines from ESPN.

  nba/meta.json             season, updated, games today
  nba/index.json            every player this season (or last): per-game averages
  nba/players/<id>.json     game logs (this season and last) and averages
  nba/teams.json            ratings from box scores: offense/defense per 100, pace, ranks, last 10
  nba/games.json            today's and tomorrow's games, with DraftKings' spread and total
  nba/props.json            today's DraftKings lines with each player's hit rates
  nba/props-lines/          the lines archive (nba_lines.archive)

  python pipeline/nba_build.py --out dist [--date 2026-10-22]
"""

from __future__ import annotations

import argparse
import io
import json
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import nba_lines

HOOPR = "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba/player_box/parquet/player_box_{season}.parquet"
ET = ZoneInfo("America/New_York")
# Per-game stats, and the combos DraftKings lists.
BASE = {"pts": "points", "reb": "rebounds", "ast": "assists", "fg3m": "three_point_field_goals_made", "stl": "steals", "blk": "blocks", "tov": "turnovers",
        "fgm": "field_goals_made", "fga": "field_goals_attempted", "fg3a": "three_point_field_goals_attempted", "ftm": "free_throws_made", "fta": "free_throws_attempted",
        "oreb": "offensive_rebounds", "min": "minutes"}
COMBOS = {"pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")}
PROP_STATS = ("pts", "reb", "ast", "fg3m", "pra", "pr", "pa", "ra", "stl", "blk")
# The 30 teams, by ESPN's abbreviations (box scores also hold All-Star Weekend squads).
TEAMS = {"ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GS", "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NO", "NY",
         "OKC", "ORL", "PHI", "PHX", "POR", "SA", "SAC", "TOR", "UTAH", "WSH"}


def season_of(day: date) -> int:
    """hoopR/ESPN label a season by its end year: 2026-27 is 2027 (it starts in October)."""
    return day.year + 1 if day.month >= 9 else day.year


def load_box(season: int, raw: Path | None) -> pd.DataFrame | None:
    """One season's player box scores (regular season and playoffs), players who played."""
    try:
        if raw and (raw / f"player_box_{season}.parquet").exists():
            df = pd.read_parquet(raw / f"player_box_{season}.parquet")
        else:
            with urllib.request.urlopen(urllib.request.Request(HOOPR.format(season=season), headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as r:
                df = pd.read_parquet(io.BytesIO(r.read()))
    except Exception as e:  # noqa: BLE001
        print(f"  nba: no box scores for {season}: {e}")
        return None
    df = df[df["season_type"].isin([2, 3]) & ~df["did_not_play"].fillna(False).astype(bool) & (df["minutes"].fillna(0) > 0)
            & df["team_abbreviation"].isin(TEAMS) & df["opponent_team_abbreviation"].isin(TEAMS)].copy()
    out = pd.DataFrame({
        "game_id": df["game_id"].astype(str), "season": df["season"], "playoffs": df["season_type"] == 3,
        "date": pd.to_datetime(df["game_date"]).dt.strftime("%Y-%m-%d"), "id": df["athlete_id"].astype(int).astype(str),
        "name": df["athlete_display_name"], "pos": df["athlete_position_abbreviation"], "jersey": df["athlete_jersey"],
        "headshot": df["athlete_headshot_href"], "team": df["team_abbreviation"], "opp": df["opponent_team_abbreviation"],
        "home": df["home_away"] == "home", "starter": df["starter"].fillna(False).astype(bool),
        "pm": pd.to_numeric(df["plus_minus"].astype(str).str.replace("+", "", regex=False), errors="coerce"),
        "team_score": df["team_score"], "opp_score": df["opponent_team_score"], "won": df["team_winner"].fillna(False).astype(bool),
        "team_logo": df["team_logo"],
    })
    for k, col in BASE.items():
        out[k] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    for k, parts in COMBOS.items():
        out[k] = sum(out[p] for p in parts)
    return out.sort_values(["date", "game_id"])


def averages(g: pd.DataFrame) -> dict:
    """Per-game averages (and shooting %) over a set of games."""
    n = len(g)
    if not n:
        return {"g": 0}
    a = {"g": n, **{k: round(float(g[k].mean()), 1) for k in ("min", "pts", "reb", "ast", "fg3m", "stl", "blk", "tov", "pra")}}
    a["fg_pct"] = round(float(g["fgm"].sum() / g["fga"].sum()), 3) if g["fga"].sum() else None
    a["fg3_pct"] = round(float(g["fg3m"].sum() / g["fg3a"].sum()), 3) if g["fg3a"].sum() else None
    a["ft_pct"] = round(float(g["ftm"].sum() / g["fta"].sum()), 3) if g["fta"].sum() else None
    return a


LOG_COLS = ["date", "game_id", "opp", "home", "starter", "min", "pts", "reb", "ast", "fg3m", "stl", "blk", "tov", "fgm", "fga", "fg3a", "ftm", "fta", "pm", "won", "team_score", "opp_score"]


def log_rows(g: pd.DataFrame) -> list[dict]:
    rows = []
    for r in g[LOG_COLS].to_dict("records"):
        rows.append({k: (None if isinstance(v, float) and np.isnan(v) else (int(v) if isinstance(v, (float, np.floating)) and float(v).is_integer() else (float(v) if isinstance(v, (np.floating,)) else (bool(v) if isinstance(v, (bool, np.bool_)) else v)))) for k, v in r.items()})
    return rows


def team_ratings(box: pd.DataFrame) -> dict:
    """Per team: possessions-based offense/defense per 100, pace, record and last 10 (this season's games)."""
    t = box.groupby(["game_id", "date", "team", "opp"]).agg(
        pts=("pts", "sum"), fga=("fga", "sum"), fta=("fta", "sum"), oreb=("oreb", "sum"), tov=("tov", "sum"), min=("min", "sum"),
        won=("won", "first"), team_score=("team_score", "first"), opp_score=("opp_score", "first"), logo=("team_logo", "first"),
    ).reset_index()
    t["poss"] = t.fga + 0.44 * t.fta - t.oreb + t.tov
    opp = t[["game_id", "team", "poss", "pts"]].rename(columns={"team": "opp", "poss": "opp_poss", "pts": "opp_pts"})
    t = t.merge(opp, on=["game_id", "opp"])
    t["game_poss"] = (t.poss + t.opp_poss) / 2
    t["minutes"] = (t["min"] / 5).clip(lower=48)
    out = {}
    for team, g in t.sort_values("date").groupby("team"):
        poss = g.game_poss.sum()
        last10 = g.tail(10)
        out[team] = {
            "logo": g["logo"].iloc[-1],
            "w": int(g.won.sum()), "l": int((~g.won).sum()),
            "ortg": round(float(g.team_score.sum() / poss * 100), 1), "drtg": round(float(g.opp_score.sum() / poss * 100), 1),
            "pace": round(float((g.game_poss / g.minutes * 48).mean()), 1),
            "last10": f"{int(last10.won.sum())}-{int((~last10.won).sum())}",
            "ppg": round(float(g.team_score.mean()), 1), "opp_ppg": round(float(g.opp_score.mean()), 1),
        }
        out[team]["net"] = round(out[team]["ortg"] - out[team]["drtg"], 1)
    for key, best_high in (("ortg", True), ("drtg", False), ("net", True), ("pace", True)):
        ranked = sorted(out, key=lambda k: out[k][key], reverse=best_high)
        for i, k in enumerate(ranked):
            out[k][f"{key}_rank"] = i + 1
    return out


def hit_rates(log: pd.DataFrame, stat: str, line: float, before: pd.DataFrame | None = None) -> dict:
    """
    How often the player went over `line` in games he played: his last 5 and 10
    (reaching back into `before`, last season, early in a season) and all of `log`.
    """
    v = log[stat].to_numpy()
    recent = np.concatenate([before[stat].to_numpy(), v]) if before is not None else v
    def rate(x):
        return {"over": int((x > line).sum()), "n": int(len(x))}
    return {"l5": rate(recent[-5:]), "l10": rate(recent[-10:]), "all": rate(v)}


def build(out: Path, day: str, raw: Path | None = None) -> None:
    nba = out / "nba"
    (nba / "players").mkdir(parents=True, exist_ok=True)
    today = date.fromisoformat(day)
    season = season_of(today)
    cur, prev = load_box(season, raw), load_box(season - 1, raw)
    cur = cur if cur is not None else (prev.iloc[0:0] if prev is not None else None)
    if cur is None or prev is None:
        raise SystemExit("nba: box scores unavailable")
    both = pd.concat([prev, cur], ignore_index=True)

    # Players: everyone with a game this season or last; team and bio from their latest game.
    latest = both.sort_values("date").groupby("id").tail(1).set_index("id")
    index = []
    for pid, info in latest.iterrows():
        c, p = cur[cur.id == pid], prev[prev.id == pid]
        entry = {
            "id": pid, "name": info["name"], "team": info["team"], "pos": info["pos"], "jersey": info["jersey"], "headshot": info["headshot"],
            "s": averages(c) if len(c) else None, "last": averages(p[~p.playoffs]) if len(p) else None,
        }
        index.append(entry)
        page = {**entry, "log": log_rows(c), "log_last": log_rows(p[~p.playoffs].tail(40))}
        (nba / "players" / f"{pid}.json").write_text(json.dumps(page, separators=(",", ":")))
    # By scoring: this season's once a player has 5 games, last season's until then.
    def scoring(e):
        s = e["s"] if e["s"] and e["s"]["g"] >= 5 else (e["last"] or e["s"] or {})
        return -(s.get("pts") or 0)
    index.sort(key=scoring)
    (nba / "index.json").write_text(json.dumps(index, separators=(",", ":")))

    # Teams: this season's ratings, or last season's until a team has played 3 games.
    teams_cur, teams_prev = team_ratings(cur) if len(cur) else {}, team_ratings(prev[~prev.playoffs])
    teams = {}
    for t in set(teams_prev) | set(teams_cur):
        c = teams_cur.get(t)
        teams[t] = {**(c if c and c["w"] + c["l"] >= 3 else teams_prev.get(t, {})), "record": f"{c['w']}-{c['l']}" if c else "0-0", "last_season": teams_prev.get(t), "from_last_season": not (c and c["w"] + c["l"] >= 3)}
    (nba / "teams.json").write_text(json.dumps({"season": season, "teams": teams}, separators=(",", ":")))

    # Games: today and tomorrow (US Eastern dates), and their DraftKings lines.
    games = nba_lines.games_on(day) + nba_lines.games_on((today + timedelta(days=1)).isoformat())
    (nba / "games.json").write_text(json.dumps({"date": day, "games": games}, separators=(",", ":")))
    lines = nba_lines.lines_for([g["event"] for g in games if g["state"] == "pre" and g["start"] and g["start"][:10] <= (today + timedelta(days=1)).isoformat()])
    # Archived under each game's own (US Eastern) date.
    date_of = {g["event"]: datetime.fromisoformat(g["start"].replace("Z", "+00:00")).astimezone(ET).date().isoformat() for g in games if g["start"]}
    n_days = 0
    for d in sorted({date_of.get(l["event"], day) for l in lines}) or [day]:
        n_days = nba_lines.archive(nba / "props-lines", d, [l for l in lines if date_of.get(l["event"], day) == d])

    # Props board: each line, with the player's hit rates this season and last.
    by_event = {g["event"]: g for g in games}
    props = []
    for l in lines:
        info = latest.loc[l["athlete"]] if l["athlete"] in latest.index else None
        if info is None or l["stat"] not in PROP_STATS:
            continue
        g = by_event.get(l["event"], {})
        log_c = cur[cur.id == l["athlete"]]
        log_p = prev[(prev.id == l["athlete"]) & ~prev.playoffs]
        props.append({
            **l, "name": info["name"], "team": info["team"], "pos": info["pos"], "headshot": info["headshot"],
            "opp": g.get("home") if g.get("away") == info["team"] else g.get("away"), "start": g.get("start"),
            "avg": round(float(log_c[l["stat"]].mean()), 1) if len(log_c) else None,
            "avg_last": round(float(log_p[l["stat"]].mean()), 1) if len(log_p) else None,
            "hits": hit_rates(log_c, l["stat"], l["line"], before=log_p), "hits_last": hit_rates(log_p, l["stat"], l["line"]),
        })
    (nba / "props.json").write_text(json.dumps({"date": day, "season": season, "props": props}, separators=(",", ":")))
    (nba / "meta.json").write_text(json.dumps({
        "season": season, "season_label": f"{season - 1}-{str(season)[2:]}", "date": day,
        "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "games_played": int(cur.game_id.nunique()),
        "players": len(index), "lines": len(props), "days_archived": n_days,
    }))
    print(f"nba {season}: {len(index)} players, {len(teams)} teams, {len(games)} games, {len(props)} lines ({n_days} days archived)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--date", default=datetime.now(ET).date().isoformat(), help="US Eastern date")
    ap.add_argument("--raw", help="a folder with player_box_<season>.parquet (else downloaded)")
    args = ap.parse_args()
    build(Path(args.out), args.date, Path(args.raw) if args.raw else None)


if __name__ == "__main__":
    main()
