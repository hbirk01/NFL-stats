"""
League-wide pages for BetTracker:

  leaders.json  every qualified player's advanced metrics and percentiles, by
                position (the sortable leaderboards)
  teams.json    each team: record, offense/defense EPA per play by week and
                their league ranks, the model's power rating week by week,
                results against the closing spread and total, starters from
                the depth chart, and the injury report

Written by build.py.
"""

from __future__ import annotations

import pandas as pd

from model import PLAYS, Ratings, team_games

# nflverse code -> (team name, ESPN logo code).
TEAMS = {
    "ARI": ("Arizona Cardinals", "ari"), "ATL": ("Atlanta Falcons", "atl"), "BAL": ("Baltimore Ravens", "bal"), "BUF": ("Buffalo Bills", "buf"),
    "CAR": ("Carolina Panthers", "car"), "CHI": ("Chicago Bears", "chi"), "CIN": ("Cincinnati Bengals", "cin"), "CLE": ("Cleveland Browns", "cle"),
    "DAL": ("Dallas Cowboys", "dal"), "DEN": ("Denver Broncos", "den"), "DET": ("Detroit Lions", "det"), "GB": ("Green Bay Packers", "gb"),
    "HOU": ("Houston Texans", "hou"), "IND": ("Indianapolis Colts", "ind"), "JAX": ("Jacksonville Jaguars", "jax"), "KC": ("Kansas City Chiefs", "kc"),
    "LA": ("Los Angeles Rams", "lar"), "LAC": ("Los Angeles Chargers", "lac"), "LV": ("Las Vegas Raiders", "lv"), "MIA": ("Miami Dolphins", "mia"),
    "MIN": ("Minnesota Vikings", "min"), "NE": ("New England Patriots", "ne"), "NO": ("New Orleans Saints", "no"), "NYG": ("New York Giants", "nyg"),
    "NYJ": ("New York Jets", "nyj"), "PHI": ("Philadelphia Eagles", "phi"), "PIT": ("Pittsburgh Steelers", "pit"), "SEA": ("Seattle Seahawks", "sea"),
    "SF": ("San Francisco 49ers", "sf"), "TB": ("Tampa Bay Buccaneers", "tb"), "TEN": ("Tennessee Titans", "ten"), "WAS": ("Washington Commanders", "wsh"),
}
# EPA per play to points per game for the power rating (the game model's fitted margin scale, roughly).
RATING_SCALE = 0.62
OFFENSE = ["QB", "RB", "FB", "WR", "TE", "LT", "LG", "C", "RG", "RT"]
DEFENSE = ["LDE", "LDT", "NT", "RDT", "RDE", "WLB", "MLB", "LILB", "RILB", "SLB", "LCB", "RCB", "NB", "SS", "FS"]


def leaders(adv: dict, index: list[dict]) -> dict:
    """Per position, every qualified player's metric values and percentiles."""
    info = {e["id"]: e for e in index}
    out: dict = {}
    for pid, a in adv.items():
        e = info.get(pid)
        if not e or not a or not a.get("qualified"):
            continue
        out.setdefault(e["pos"], []).append({
            "id": pid, "name": e["name"], "team": e["team"], "headshot": e.get("headshot"),
            "g": (e.get("s") or {}).get("g"),
            "v": {m["k"]: m["v"] for m in a["metrics"]},
            "pct": {m["k"]: m["pct"] for m in a["metrics"] if "pct" in m},
        })
    return out


def _record(sched: pd.DataFrame, team: str) -> dict:
    g = sched[((sched["home_team"] == team) | (sched["away_team"] == team)) & sched["result"].notna()]
    w = l = t = pf = pa = 0
    for _, x in g.iterrows():
        home = x["home_team"] == team
        mine, theirs = (x["home_score"], x["away_score"]) if home else (x["away_score"], x["home_score"])
        pf, pa = pf + mine, pa + theirs
        w, l, t = w + (mine > theirs), l + (mine < theirs), t + (mine == theirs)
    return {"w": int(w), "l": int(l), "t": int(t), "pf": int(pf), "pa": int(pa)}


def _vs_lines(x: pd.Series, team: str) -> dict:
    """A finished game against the closing lines, from the team's side: its spread (- = favored), cover, over/under."""
    if pd.isna(x.get("result")) or pd.isna(x.get("spread_line")):
        return {}
    home = x["home_team"] == team
    # nflverse: spread_line > 0 means the home team was favored by that much; result = home - away.
    line = float(-x["spread_line"] if home else x["spread_line"])
    margin = float(x["result"] if home else -x["result"])
    cover = margin + line
    out = {"line": line, "ats": "W" if cover > 0 else "L" if cover < 0 else "P"}
    if not pd.isna(x.get("total_line")):
        total = float(x["home_score"] + x["away_score"])
        out |= {"total_line": float(x["total_line"]), "ou": "O" if total > x["total_line"] else "U" if total < x["total_line"] else "P"}
    return out


def _trends(weekly: list[dict]) -> dict:
    """Season records against the spread (overall, as favorite, as underdog) and on totals."""
    def rec(rows, key, labels):
        return {lab.lower(): sum(1 for r in rows if r.get(key) == lab) for lab in labels}
    ats = [w for w in weekly if "ats" in w]
    return {
        "ats": rec(ats, "ats", "WLP"),
        "fav": rec([w for w in ats if w["line"] < 0], "ats", "WLP"),
        "dog": rec([w for w in ats if w["line"] > 0], "ats", "WLP"),
        "ou": rec(weekly, "ou", "OUP"),
    }


def teams(pbp: pd.DataFrame, prev_pbp: pd.DataFrame | None, sched: pd.DataFrame, season: int, week: int,
          roster_all: pd.DataFrame, injuries: dict, depth: pd.DataFrame | None) -> dict:
    tg = team_games(pbp)
    prev = team_games(prev_pbp) if prev_pbp is not None else None
    ratings = Ratings(tg, prev)
    lg = float(tg["off_epa"].mean())
    season_sched = sched[(sched["season"] == season) & (sched["game_type"] == "REG")]

    # Season-to-date EPA per play and its rank (offense: higher is better; defense: lower allowed is better).
    means = tg.groupby("team")[["off_epa", "def_epa"]].mean()
    off_rank = means["off_epa"].rank(ascending=False, method="min")
    def_rank = means["def_epa"].rank(ascending=True, method="min")

    # The model's power rating each week (points vs an average team, before that week's games).
    power = {t: [] for t in TEAMS}
    for w in range(1, week + 2):
        for t, (o, d) in ratings.at(w).items():
            if t in power:
                power[t].append({"week": w, "rating": round((o - d) * PLAYS * RATING_SCALE, 1)})
    latest = {t: p[-1]["rating"] for t, p in power.items() if p}
    power_rank = pd.Series(latest).rank(ascending=False, method="min")

    names = roster_all.drop_duplicates("gsis_id").set_index("gsis_id")
    snapshot = depth[depth["dt"] == depth["dt"].max()] if depth is not None and "dt" in depth.columns and len(depth) else None

    out = {}
    for t, (name, logo) in TEAMS.items():
        games = tg[tg["team"] == t].sort_values("week")
        weekly = []
        for _, g in games.iterrows():
            row = season_sched[season_sched["game_id"] == g["game_id"]]
            if not len(row):
                continue
            x = row.iloc[0]
            home = x["home_team"] == t
            weekly.append({
                "week": int(g["week"]), "opp": x["away_team"] if home else x["home_team"], "home": bool(home),
                "pf": None if pd.isna(x["home_score"]) else int(x["home_score"] if home else x["away_score"]),
                "pa": None if pd.isna(x["home_score"]) else int(x["away_score"] if home else x["home_score"]),
                "off_epa": round(float(g["off_epa"]), 3), "def_epa": round(float(g["def_epa"]), 3),
                **_vs_lines(x, t),
            })
        starters = {"offense": [], "defense": []}
        if snapshot is not None:
            d = snapshot[snapshot["team"] == t]
            for side, slots in (("offense", OFFENSE), ("defense", DEFENSE)):
                for pos in slots:
                    rows = d[(d["pos_abb"] == pos) & (d["pos_rank"] <= (3 if pos == "WR" else 1))].sort_values("pos_rank")
                    for _, r in rows.drop_duplicates("gsis_id").iterrows():
                        gsis = r.get("gsis_id")
                        starters[side].append({"pos": pos, "name": r["player_name"], "id": gsis if isinstance(gsis, str) else None,
                                               **({"inj": injuries[gsis]} if isinstance(gsis, str) and gsis in injuries else {})})
        hurt = []
        for gsis, inj in injuries.items():
            if gsis in names.index and names.loc[gsis, "team"] == t:
                hurt.append({"id": gsis, "name": names.loc[gsis, "full_name"], "pos": names.loc[gsis, "position"], **inj})
        hurt.sort(key=lambda h: {"Out": 0, "Doubtful": 1, "Questionable": 2}.get(h["status"], 3))
        out[t] = {
            "name": name, "logo": f"https://a.espncdn.com/i/teamlogos/nfl/500/{logo}.png",
            "record": _record(season_sched, t),
            "off_epa": round(float(means.loc[t, "off_epa"]), 3) if t in means.index else None,
            "def_epa": round(float(means.loc[t, "def_epa"]), 3) if t in means.index else None,
            "off_rank": int(off_rank[t]) if t in off_rank.index else None,
            "def_rank": int(def_rank[t]) if t in def_rank.index else None,
            "power": power[t], "power_rank": int(power_rank[t]) if t in power_rank.index else None,
            "weekly": weekly, "trends": _trends(weekly), "starters": starters, "injuries": hurt,
        }
    return {"season": season, "week": week, "lg_epa": round(lg, 3), "teams": out}
