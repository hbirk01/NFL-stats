"""
The model's number on every upcoming game (not just the ones it bets), for
BetTracker's game cards, "model agrees / disagrees" tags and game previews.
Written by build.py as model.json.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd

from build import injury_map, read
from model import GAMES_CSV, Params, Ratings, build_qb_ratings, fit, live_offset, live_params, live_starters, load, pbp_for, predict, run, summarize, team_games, win_prob
from picks import espn_week, kickoff_weather

WEATHER_WITHIN = timedelta(hours=72)  # Open-Meteo's forecast reach, roughly


def predictions(raw, season: int, now: datetime, weeks_ahead: int = 2) -> dict | None:
    games = load(raw, "games.csv", GAMES_CSV)
    pbp_cur, pbp_prev, pbp_prev2 = pbp_for(raw, season), pbp_for(raw, season - 1), pbp_for(raw, season - 2)
    if games is None or pbp_cur is None or pbp_prev is None or pbp_prev2 is None:
        return None
    tg_cur, tg_prev, tg_prev2 = team_games(pbp_cur), team_games(pbp_prev), team_games(pbp_prev2)
    qbr = build_qb_ratings([pbp_prev2, pbp_prev, pbp_cur])
    p = fit(run(games, tg_prev, tg_prev2, season - 1, Params(), qbr=qbr), Params())
    ratings = Ratings(tg_cur, tg_prev, qbr)
    injuries = injury_map(read(raw, f"injuries/injuries_{season}.parquet"))

    upcoming = games[(games["season"] == season) & (games["game_type"] == "REG") & games["result"].isna()]
    out = []
    for week in sorted(upcoming["week"].unique())[:weeks_ahead]:
        week = int(week)
        try:
            espn = espn_week(season, week)
        except Exception:
            espn = {}
        at = ratings.at(week, live_starters(upcoming[upcoming["week"] == week], ratings.main_qb, injuries))
        offset = live_offset(games, tg_cur, tg_prev, tg_prev2, season, p, week, qbr)
        for _, g in upcoming[upcoming["week"] == week].iterrows():
            eid = str(int(g["espn"])) if pd.notna(g.get("espn")) else None
            e = espn.get(eid) if eid else None
            game = g.copy()
            qb_out = []
            for side in ("home", "away"):
                usual = ratings.main_qb.get(g[f"{side}_team"])
                out_now = bool(usual) and injuries.get(usual, {}).get("status") in ("Out", "Doubtful")
                game[f"{side}_qb_id"] = "backup" if out_now else usual
                if out_now:
                    qb_out.append(g[f"{side}_team"])
            wind = temp = None
            indoor = bool(e and e["indoor"]) or str(g.get("roof")) in ("dome", "closed")
            if e and not indoor and e["start"] - now <= WEATHER_WITHIN:
                wind, temp = kickoff_weather(e["city"], e["start"])
            game["wind"], game["temp"] = wind, temp
            game["roof"] = "dome" if indoor else "outdoors"
            margin, total = predict(game, at, ratings.lg, ratings.main_qb, p)
            total += offset
            market_home_line = e["home_line"] if e and e["home_line"] is not None else (-g["spread_line"] if pd.notna(g.get("spread_line")) else None)
            market_total = e["total"] if e and e["total"] is not None else (g["total_line"] if pd.notna(g.get("total_line")) else None)
            out.append({
                "espn": eid,
                "week": week,
                "start": e["start"].isoformat() if e else None,
                "home": g["home_team"],
                "away": g["away_team"],
                "home_id": e["home"]["id"] if e else None,
                "away_id": e["away"]["id"] if e else None,
                # The model: home margin (+ = home wins by), total, home win chance.
                "margin": round(float(margin), 1),
                "total": round(float(total), 1),
                "home_win": round(win_prob(margin), 3),
                # The market at build time: the home team's spread line and the total.
                "market": {"home_line": market_home_line, "total": market_total},
                "wind": None if wind is None else round(wind),
                "temp": None if temp is None else round(temp),
                "indoor": indoor,
                "qb_out": qb_out,
            })
    return {
        "generated": now.isoformat(timespec="seconds"),
        "season": season,
        # The Model account's profile, so the app can find its picks (set in the workflow).
        "model_user": os.environ.get("MODEL_USER_ID") or None,
        "replay": replay(games, tg_cur, tg_prev, tg_prev2, season, p, qbr),
        "games": out,
    }


def replay(games, tg_cur, tg_prev, tg_prev2, season: int, p: Params, qbr=None) -> dict:
    """
    What the live rules (4+ point edges, spreads and totals, no moneylines) would
    have done at the closing lines: this season so far, which the model hadn't
    seen when it was calibrated, and last season, which it was calibrated on.
    """
    live = live_params(p)

    def record(df, label):
        s = summarize(df, label)
        return {k: s[k] for k in ("label", "games", "spread", "total", "all") if k in s}

    last = run(games, tg_prev, tg_prev2, season - 1, live, qbr=qbr)
    out = {"last": record(last, f"{season - 1} season")}
    cur = run(games, tg_cur, tg_prev, season, live, anchor=last, qbr=qbr)
    if len(cur):
        out["this"] = record(cur, f"{season} so far")
    return out
