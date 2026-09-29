"""
Builds the NFL stats data BetTracker reads: small JSON files from nflverse's
free daily releases. Run by .github/workflows/data.yml, which publishes
dist/ to the `data` branch.

  python pipeline/build.py [--season 2026] [--raw DIR] [--out dist]

Outputs (dist/):
  meta.json            when it was built, the season/week, which seasons feed routes & pressure
  index.json           every QB/RB/WR/TE: ids (gsis/espn/sleeper), team, headline stats
  defense.json         fantasy points each defense allows per position, ranked
  players/<gsis>.json  one player's page: season line, advanced metrics with
                       percentiles, game log, route tree, pressure/blitz splits,
                       rushing detail, schedule difficulty

Route trees and pressure come from nflverse's participation data, which is only
published after a season ends; until the current season's arrives, they use the
last season that has it (meta.json says which).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

RELEASES = "https://github.com/nflverse/nflverse-data/releases/download"
GAMES_CSV = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
SKILL = ["QB", "RB", "WR", "TE"]


# ── Loading ──────────────────────────────────────────────────────────────────

def fetch(raw: Path, rel: str) -> Path | None:
    """Downloads one release file into raw/ (reusing it if already there). None if it doesn't exist."""
    dest = raw / os.path.basename(rel)
    if dest.exists():
        return dest
    url = rel if rel.startswith("http") else f"{RELEASES}/{rel}"
    try:
        urllib.request.urlretrieve(url, dest)
        return dest
    except Exception as e:  # 404: not published (yet)
        print(f"  skip {url}: {e}")
        return None


def read(raw: Path, rel: str) -> pd.DataFrame | None:
    path = fetch(raw, rel)
    if path is None:
        return None
    return pd.read_csv(path, low_memory=False) if path.suffix == ".csv" else pd.read_parquet(path)


def real_plays(pbp: pd.DataFrame) -> pd.DataFrame:
    """Regular-season scrimmage plays that count: no penalties-nullified plays, no two-point tries."""
    return pbp[
        (pbp["season_type"] == "REG")
        & pbp["play_type"].isin(["pass", "run", "qb_kneel", "qb_spike"])
        & (pbp["two_point_attempt"].fillna(0) == 0)
    ].copy()


# ── Helpers ──────────────────────────────────────────────────────────────────

def num(x, nd=1):
    """JSON-safe rounded number (None for NaN/inf)."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, nd) if nd else int(round(f))


def ratio(a, b, scale=1.0, nd=1):
    return num(a / b * scale, nd) if b else None


def write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))


# ── Per-game stat lines ──────────────────────────────────────────────────────

def game_lines(plays: pd.DataFrame, pbp_all: pd.DataFrame) -> pd.DataFrame:
    """One row per player per game: passing, rushing and receiving lines plus fantasy points."""
    p = plays
    pass_rows = p[p["passer_player_id"].notna() & ((p["pass_attempt"] == 1) | (p["sack"] == 1))].copy()
    # Sacks are dropbacks, not attempts.
    pass_rows["is_att"] = ((pass_rows["pass_attempt"] == 1) & (pass_rows["sack"] != 1)).astype(int)
    passing = pass_rows.groupby(["passer_player_id", "game_id"]).agg(
        att=("is_att", "sum"),
        cmp=("complete_pass", "sum"),
        pass_yds=("passing_yards", "sum"),
        pass_td=("pass_touchdown", "sum"),
        ints=("interception", "sum"),
        sacks=("sack", "sum"),
        pass_epa=("epa", "sum"),
    ).reset_index().rename(columns={"passer_player_id": "id"})

    rush_rows = p[p["rusher_player_id"].notna() & (p["rush_attempt"] == 1)]
    rushing = rush_rows.groupby(["rusher_player_id", "game_id"]).agg(
        car=("rush_attempt", "sum"),
        rush_yds=("rushing_yards", "sum"),
        rush_td=("rush_touchdown", "sum"),
        long_rush=("rushing_yards", "max"),
        rush_epa=("epa", "sum"),
    ).reset_index().rename(columns={"rusher_player_id": "id"})

    tgt_rows = p[p["receiver_player_id"].notna() & (p["pass_attempt"] == 1)]
    receiving = tgt_rows.groupby(["receiver_player_id", "game_id"]).agg(
        tgt=("pass_attempt", "sum"),
        rec=("complete_pass", "sum"),
        rec_yds=("receiving_yards", "sum"),
        rec_td=("pass_touchdown", "sum"),
        long_rec=("receiving_yards", "max"),
        air=("air_yards", "sum"),
        yac=("yards_after_catch", "sum"),
        rec_epa=("epa", "sum"),
    ).reset_index().rename(columns={"receiver_player_id": "id"})

    lines = passing.merge(rushing, on=["id", "game_id"], how="outer").merge(receiving, on=["id", "game_id"], how="outer")

    # Fumbles lost and two-point conversions, from every play (two-point tries included).
    reg = pbp_all[pbp_all["season_type"] == "REG"]
    fum = reg[reg["fumble_lost"] == 1].groupby(["fumbled_1_player_id", "game_id"]).size().rename("fum_lost").reset_index().rename(columns={"fumbled_1_player_id": "id"})
    good2 = reg[reg["two_point_conv_result"] == "success"]
    two = pd.concat([
        good2[["passer_player_id", "game_id"]].rename(columns={"passer_player_id": "id"}),
        good2[["rusher_player_id", "game_id"]].rename(columns={"rusher_player_id": "id"}),
        good2[["receiver_player_id", "game_id"]].rename(columns={"receiver_player_id": "id"}),
    ]).dropna().groupby(["id", "game_id"]).size().rename("two_pt").reset_index()
    lines = lines.merge(fum, on=["id", "game_id"], how="left").merge(two, on=["id", "game_id"], how="left")
    lines = lines.fillna({c: 0 for c in lines.columns if c not in ("id", "game_id")})

    base = (
        lines["pass_yds"] * 0.04 + lines["pass_td"] * 4 - lines["ints"] * 1
        + lines["rush_yds"] * 0.1 + lines["rush_td"] * 6
        + lines["rec_yds"] * 0.1 + lines["rec_td"] * 6
        - lines["fum_lost"] * 2 + lines["two_pt"] * 2
    )
    lines["fp_std"] = base
    lines["fp_half"] = base + lines["rec"] * 0.5
    lines["fp_ppr"] = base + lines["rec"]

    # Which team, opponent and week each game was for the player.
    games = p.groupby("game_id").agg(week=("week", "first"), home=("home_team", "first"), away=("away_team", "first")).reset_index()
    team_rows = pd.concat([
        p[["passer_player_id", "game_id", "posteam"]].rename(columns={"passer_player_id": "id"}),
        p[["rusher_player_id", "game_id", "posteam"]].rename(columns={"rusher_player_id": "id"}),
        p[["receiver_player_id", "game_id", "posteam"]].rename(columns={"receiver_player_id": "id"}),
    ]).dropna().drop_duplicates(["id", "game_id"])
    lines = lines.merge(team_rows, on=["id", "game_id"], how="left").merge(games, on="game_id", how="left")
    lines["opp"] = np.where(lines["posteam"] == lines["home"], lines["away"], lines["home"])
    lines["at_home"] = lines["posteam"] == lines["home"]
    return lines


# ── Defense vs position (fantasy points allowed) ─────────────────────────────

def defense_vs_position(lines: pd.DataFrame, pos_of: dict) -> dict:
    df = lines.copy()
    df["pos"] = df["id"].map(pos_of)
    df = df[df["pos"].isin(SKILL)]
    out = {}
    games = df.groupby("opp")["game_id"].nunique()
    for pos in SKILL:
        g = df[df["pos"] == pos].groupby("opp")["fp_ppr"].sum()
        rows = [{"team": t, "ppg": num(g.get(t, 0) / games[t], 1)} for t in games.index]
        rows.sort(key=lambda r: -(r["ppg"] or 0))
        for i, r in enumerate(rows):
            # 1 = gives up the most = easiest matchup.
            r["rank"] = i + 1
        out[pos] = rows
    return out


# ── Advanced metrics ─────────────────────────────────────────────────────────

def advanced_tables(plays: pd.DataFrame, ftn: pd.DataFrame | None, ngs: dict, season: int) -> dict:
    """Position-specific advanced metrics, keyed by player id."""
    p = plays
    team_tgts = p[p["receiver_player_id"].notna() & (p["pass_attempt"] == 1)].groupby("posteam").agg(t=("pass_attempt", "sum"), a=("air_yards", "sum"))
    fp = None
    if ftn is not None and len(ftn):
        fp = p.merge(
            ftn.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"})[
                ["game_id", "play_id", "is_play_action", "is_drop", "is_contested_ball", "is_catchable_ball", "n_blitzers", "is_qb_out_of_pocket"]
            ],
            on=["game_id", "play_id"],
            how="inner",
        )

    out: dict[str, dict] = {}

    # QB
    drop = p[(p["qb_dropback"] == 1) & p["passer_player_id"].notna()]
    for pid, g in drop.groupby("passer_player_id"):
        att = g[(g["pass_attempt"] == 1) & (g["sack"] != 1)]
        m = {
            "dropbacks": len(g),
            "epa_db": ratio(g["epa"].sum(), len(g), nd=3),
            "success": ratio(g["success"].sum(), len(g), 100),
            "cpoe": num(att["cpoe"].mean(), 1),
            "adot": num(att["air_yards"].mean(), 1),
            "deep_rate": ratio((att["air_yards"] >= 20).sum(), len(att), 100),
            "sack_rate": ratio(g["sack"].sum(), len(g), 100),
            "scramble_rate": ratio(g["qb_scramble"].sum(), len(g), 100),
            "td_rate": ratio(att["pass_touchdown"].sum(), len(att), 100),
            "int_rate": ratio(att["interception"].sum(), len(att), 100),
            "ypa": ratio(att["passing_yards"].sum(), len(att), nd=1),
        }
        out.setdefault(pid, {}).update(m)
    if fp is not None:
        qb = fp[(fp["qb_dropback"] == 1) & fp["passer_player_id"].notna()]
        for pid, g in qb.groupby("passer_player_id"):
            out.setdefault(pid, {})["pa_rate"] = ratio(g["is_play_action"].sum(), len(g), 100)

    # Rushers
    rush = p[p["rusher_player_id"].notna() & (p["rush_attempt"] == 1) & (p["play_type"] == "run")]
    for pid, g in rush.groupby("rusher_player_id"):
        out.setdefault(pid, {}).update({
            "carries": len(g),
            "ypc": ratio(g["rushing_yards"].sum(), len(g), nd=2),
            "rush_epa": ratio(g["epa"].sum(), len(g), nd=3),
            "rush_success": ratio(g["success"].sum(), len(g), 100),
            "explosive_run": ratio((g["rushing_yards"] >= 10).sum(), len(g), 100),
            "stuffed": ratio((g["rushing_yards"] <= 0).sum(), len(g), 100),
            "rz_carries": int((g["yardline_100"] <= 20).sum()),
        })

    # Receivers
    tg = p[p["receiver_player_id"].notna() & (p["pass_attempt"] == 1)]
    for pid, g in tg.groupby("receiver_player_id"):
        teams = g.groupby("posteam").agg(t=("pass_attempt", "sum"), a=("air_yards", "sum"))
        team_t = sum(team_tgts.loc[t, "t"] for t in teams.index)
        team_a = sum(team_tgts.loc[t, "a"] for t in teams.index)
        tshare = g["pass_attempt"].sum() / team_t if team_t else None
        ashare = g["air_yards"].sum() / team_a if team_a else None
        rec = g[g["complete_pass"] == 1]
        out.setdefault(pid, {}).update({
            "targets": int(g["pass_attempt"].sum()),
            "tgt_share": num(tshare * 100, 1) if tshare is not None else None,
            "air_share": num(ashare * 100, 1) if ashare is not None else None,
            "wopr": num(1.5 * tshare + 0.7 * ashare, 2) if tshare is not None and ashare is not None else None,
            "adot_rec": num(g["air_yards"].mean(), 1),
            "catch_rate": ratio(g["complete_pass"].sum(), len(g), 100),
            "yac_rec": ratio(rec["yards_after_catch"].sum(), len(rec), nd=1),
            "epa_tgt": ratio(g["epa"].sum(), len(g), nd=3),
            "ypt": ratio(g["receiving_yards"].sum(), len(g), nd=1),
            "rz_targets": int((g["yardline_100"] <= 20).sum()),
        })
    if fp is not None:
        rc = fp[fp["receiver_player_id"].notna() & (fp["pass_attempt"] == 1)]
        for pid, g in rc.groupby("receiver_player_id"):
            catchable = g[g["is_catchable_ball"] == 1]
            contested = g[g["is_contested_ball"] == 1]
            out.setdefault(pid, {}).update({
                "drop_rate": ratio(g["is_drop"].sum(), len(catchable), 100),
                "contested_catch": ratio(contested["complete_pass"].sum(), len(contested), 100) if len(contested) >= 3 else None,
            })

    # Next Gen Stats: the season-long row (week 0) for this season.
    def season_rows(df):
        if df is None:
            return pd.DataFrame()
        d = df[(df["season"] == season) & (df["season_type"] == "REG")]
        if (d["week"] == 0).any():
            return d[d["week"] == 0]
        return d.groupby("player_gsis_id").mean(numeric_only=True).reset_index()

    for _, r in season_rows(ngs.get("passing")).iterrows():
        out.setdefault(r["player_gsis_id"], {}).update({"ttt": num(r.get("avg_time_to_throw"), 2), "agg": num(r.get("aggressiveness"), 1)})
    for _, r in season_rows(ngs.get("receiving")).iterrows():
        out.setdefault(r["player_gsis_id"], {}).update({"sep": num(r.get("avg_separation"), 2), "cushion": num(r.get("avg_cushion"), 2), "yacoe": num(r.get("avg_yac_above_expectation"), 2)})
    for _, r in season_rows(ngs.get("rushing")).iterrows():
        out.setdefault(r["player_gsis_id"], {}).update({"ryoe": num(r.get("rush_yards_over_expected_per_att"), 2), "box8": num(r.get("percent_attempts_gte_eight_defenders"), 1), "ttlos": num(r.get("avg_time_to_los"), 2)})
    return out


# Which metrics show for each position, how they read, whether lower is better,
# and the volume a player needs to be ranked.
METRICS = {
    "QB": [("epa_db", "EPA / dropback", False), ("cpoe", "CPOE", False), ("success", "Success rate %", False), ("ypa", "Yards / attempt", False),
           ("adot", "aDOT", False), ("deep_rate", "Deep throw %", False), ("td_rate", "TD %", False), ("int_rate", "INT %", True),
           ("sack_rate", "Sack %", True), ("scramble_rate", "Scramble %", False), ("ttt", "Time to throw (s)", None), ("pa_rate", "Play action %", None)],
    "RB": [("ypc", "Yards / carry", False), ("ryoe", "Rush yds over expected / att", False), ("rush_success", "Rush success %", False),
           ("rush_epa", "EPA / rush", False), ("explosive_run", "10+ yd run %", False), ("stuffed", "Stuffed %", True), ("box8", "8+ in box %", None),
           ("tgt_share", "Target share %", False), ("yac_rec", "YAC / catch", False), ("rz_carries", "Red zone carries", False)],
    "WR": [("tgt_share", "Target share %", False), ("air_share", "Air yards share %", False), ("wopr", "WOPR", False), ("adot_rec", "aDOT", None),
           ("ypt", "Yards / target", False), ("epa_tgt", "EPA / target", False), ("catch_rate", "Catch rate %", False), ("yac_rec", "YAC / catch", False),
           ("sep", "Separation (yds)", False), ("yacoe", "YAC over expected", False), ("drop_rate", "Drop rate %", True), ("contested_catch", "Contested catch %", False),
           ("rz_targets", "Red zone targets", False)],
}
METRICS["TE"] = METRICS["WR"]
QUALIFY = {"QB": ("dropbacks", 12), "RB": ("carries", 5), "WR": ("targets", 3), "TE": ("targets", 2)}  # per team game


def with_percentiles(adv: dict, pos_of: dict, weeks: int) -> dict:
    """Each player's metrics for their position, with a percentile among qualified players at it."""
    result = {}
    for pos, metrics in METRICS.items():
        key, per_game = QUALIFY[pos]
        pool = [pid for pid, m in adv.items() if pos_of.get(pid) == pos and (m.get(key) or 0) >= per_game * weeks]
        for pid, m in adv.items():
            if pos_of.get(pid) != pos:
                continue
            rows = []
            for k, label, lower_better in metrics:
                v = m.get(k)
                if v is None:
                    continue
                pct = None
                if lower_better is not None and pid in pool:
                    vals = [adv[o][k] for o in pool if adv[o].get(k) is not None]
                    if len(vals) >= 8:
                        below = sum(1 for x in vals if (x > v if lower_better else x < v))
                        pct = round(below / (len(vals) - 1) * 100) if len(vals) > 1 else None
                rows.append({"k": k, "label": label, "v": v, **({"pct": pct} if pct is not None else {})})
            result[pid] = {"qualified": pid in pool, "metrics": rows}
    return result


# ── Routes & pressure (participation seasons) ────────────────────────────────

def route_trees(pbp: pd.DataFrame, part: pd.DataFrame) -> dict:
    j = real_plays(pbp).merge(
        part.rename(columns={"nflverse_game_id": "game_id"})[["game_id", "play_id", "route", "was_pressure", "time_to_throw", "defense_man_zone_type"]],
        on=["game_id", "play_id"], how="left",
    )
    trees = {}
    tg = j[j["receiver_player_id"].notna() & (j["pass_attempt"] == 1) & j["route"].notna() & (j["route"] != "")]
    for pid, g in tg.groupby("receiver_player_id"):
        rows = []
        for route, r in g.groupby("route"):
            n = len(r)
            rows.append({
                "route": route, "tgt": n, "rec": int(r["complete_pass"].sum()), "yds": num(r["receiving_yards"].sum(), 0),
                "td": int(r["pass_touchdown"].sum()), "epa": num(r["epa"].sum() / n, 2), "adot": num(r["air_yards"].mean(), 1),
            })
        rows.sort(key=lambda x: -x["tgt"])
        man = g[g["defense_man_zone_type"] == "MAN_COVERAGE"]
        zone = g[g["defense_man_zone_type"] == "ZONE_COVERAGE"]
        def split(d):
            return {"tgt": len(d), "rec": int(d["complete_pass"].sum()), "yds": num(d["receiving_yards"].sum(), 0), "epa": num(d["epa"].sum() / len(d), 2) if len(d) else None}
        trees[pid] = {"routes": rows, "man": split(man), "zone": split(zone)}

    pressure = {}
    qb = j[j["passer_player_id"].notna() & (j["qb_dropback"] == 1) & j["was_pressure"].notna()]
    for pid, g in qb.groupby("passer_player_id"):
        def split(d):
            a = d[(d["pass_attempt"] == 1) & (d["sack"] != 1)]
            return {
                "db": len(d), "att": len(a), "cmp_pct": ratio(a["complete_pass"].sum(), len(a), 100), "ypa": ratio(a["passing_yards"].sum(), len(a)),
                "td": int(a["pass_touchdown"].sum()), "int": int(a["interception"].sum()), "sacks": int(d["sack"].sum()),
                "epa_db": ratio(d["epa"].sum(), len(d), nd=3),
            }
        pr = g[g["was_pressure"] == True]
        cl = g[g["was_pressure"] == False]
        pressure[pid] = {"rate": ratio(len(pr), len(g), 100), "pressured": split(pr), "clean": split(cl), "ttt": num(g["time_to_throw"].mean(), 2)}
    return {"routes": trees, "pressure": pressure}


def blitz_splits(plays: pd.DataFrame, ftn: pd.DataFrame | None) -> dict:
    """This season's QB splits vs the blitz and with play action (FTN charting, published weekly)."""
    if ftn is None or not len(ftn):
        return {}
    j = plays.merge(ftn.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"})[["game_id", "play_id", "n_blitzers", "is_play_action"]], on=["game_id", "play_id"], how="inner")
    out = {}
    qb = j[j["passer_player_id"].notna() & (j["qb_dropback"] == 1)]
    for pid, g in qb.groupby("passer_player_id"):
        def split(d):
            a = d[(d["pass_attempt"] == 1) & (d["sack"] != 1)]
            return {"db": len(d), "cmp_pct": ratio(a["complete_pass"].sum(), len(a), 100), "ypa": ratio(a["passing_yards"].sum(), len(a)), "epa_db": ratio(d["epa"].sum(), len(d), nd=3), "sacks": int(d["sack"].sum())}
        out[pid] = {
            "blitz": split(g[g["n_blitzers"] > 0]), "no_blitz": split(g[g["n_blitzers"] == 0]),
            "play_action": split(g[g["is_play_action"] == True]), "no_play_action": split(g[g["is_play_action"] == False]),
        }
    return out


def rushing_detail(plays: pd.DataFrame) -> dict:
    out = {}
    r = plays[plays["rusher_player_id"].notna() & (plays["rush_attempt"] == 1) & (plays["play_type"] == "run")].copy()
    r["gap"] = np.where(r["run_location"] == "middle", "middle", r["run_location"].fillna("") + " " + r["run_gap"].fillna(""))
    for pid, g in r.groupby("rusher_player_id"):
        gaps = []
        for gap, d in g.groupby("gap"):
            if not gap.strip():
                continue
            gaps.append({"gap": gap.strip(), "car": len(d), "yds": num(d["rushing_yards"].sum(), 0), "ypc": ratio(d["rushing_yards"].sum(), len(d)), "td": int(d["rush_touchdown"].sum()), "epa": ratio(d["epa"].sum(), len(d), nd=2)})
        downs = [{"down": int(dn), "car": len(d), "ypc": ratio(d["rushing_yards"].sum(), len(d)), "success": ratio(d["success"].sum(), len(d), 100)} for dn, d in g.groupby("down") if dn in (1, 2, 3, 4)]
        n = len(g)
        bands = [
            ("≤0", (g["rushing_yards"] <= 0).sum()), ("1–3", g["rushing_yards"].between(1, 3).sum()), ("4–9", g["rushing_yards"].between(4, 9).sum()),
            ("10–19", g["rushing_yards"].between(10, 19).sum()), ("20+", (g["rushing_yards"] >= 20).sum()),
        ]
        out[pid] = {"gaps": gaps, "downs": downs, "bands": [{"band": b, "car": int(c), "pct": ratio(c, n, 100)} for b, c in bands]}
    return out


# ── Build ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--out", default="dist")
    args = ap.parse_args()
    raw, out = Path(args.raw), Path(args.out)
    raw.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    # NFL seasons start in September; before then, the latest season is last year's.
    season = args.season or (now.year if now.month >= 9 else now.year - 1)
    print(f"Season {season}")

    pbp = read(raw, f"pbp/play_by_play_{season}.parquet")
    if pbp is None:
        raise SystemExit(f"No play-by-play for {season} yet")
    roster = read(raw, f"rosters/roster_{season}.parquet")
    ftn = read(raw, f"ftn_charting/ftn_charting_{season}.parquet")
    ngs = {k: read(raw, f"nextgen_stats/ngs_{k}.parquet") for k in ("passing", "receiving", "rushing")}
    schedule = read(raw, GAMES_CSV)

    plays = real_plays(pbp)
    week = int(plays["week"].max())
    lines = game_lines(plays, pbp)

    # Latest roster row per player.
    roster = roster.sort_values("week").drop_duplicates("gsis_id", keep="last")
    roster = roster[roster["position"].isin(SKILL) & roster["gsis_id"].notna()]
    pos_of = dict(zip(roster["gsis_id"], roster["position"]))

    defense = defense_vs_position(lines, pos_of)
    rank_of = {pos: {r["team"]: r for r in rows} for pos, rows in defense.items()}
    adv = with_percentiles(advanced_tables(plays, ftn, ngs, season), pos_of, week)
    blitz = blitz_splits(plays, ftn)
    rush_detail = rushing_detail(plays)

    # Routes & pressure: this season's participation if published, else the latest that is.
    part_season, part = season, read(raw, f"pbp_participation/pbp_participation_{season}.parquet")
    part_pbp = pbp
    if part is None:
        part_season = season - 1
        part = read(raw, f"pbp_participation/pbp_participation_{part_season}.parquet")
        part_pbp = read(raw, f"pbp/play_by_play_{part_season}.parquet")
    rp = route_trees(part_pbp, part) if part is not None and part_pbp is not None else {"routes": {}, "pressure": {}}

    # Upcoming games, for schedule difficulty.
    sched = schedule[(schedule["season"] == season) & (schedule["game_type"] == "REG")]
    upcoming = sched[sched["week"] > week]

    totals = lines.groupby("id").agg(
        g=("game_id", "nunique"), att=("att", "sum"), cmp=("cmp", "sum"), pass_yds=("pass_yds", "sum"), pass_td=("pass_td", "sum"), ints=("ints", "sum"),
        sacks=("sacks", "sum"), car=("car", "sum"), rush_yds=("rush_yds", "sum"), rush_td=("rush_td", "sum"), tgt=("tgt", "sum"), rec=("rec", "sum"),
        rec_yds=("rec_yds", "sum"), rec_td=("rec_td", "sum"), fum_lost=("fum_lost", "sum"), fp_ppr=("fp_ppr", "sum"), fp_half=("fp_half", "sum"), fp_std=("fp_std", "sum"),
    )
    # Positional fantasy rank (PPR).
    totals["pos"] = totals.index.map(pos_of)
    totals["pos_rank"] = totals.groupby("pos")["fp_ppr"].rank(ascending=False, method="min")

    index = []
    players_dir = out / "players"
    for _, r in roster.iterrows():
        pid, pos = r["gsis_id"], r["position"]
        t = totals.loc[pid] if pid in totals.index else None
        has_routes = pid in rp["routes"] or pid in rp["pressure"]
        if t is None and not has_routes:
            continue
        season_line = {k: num(t[k], 1 if k.startswith("fp") else 0) for k in totals.columns if k not in ("pos", "pos_rank")} if t is not None else None
        entry = {
            "id": pid, "name": r["full_name"], "pos": pos, "team": r["team"], "espn": str(int(r["espn_id"])) if pd.notna(r["espn_id"]) else None,
            "sleeper": str(r["sleeper_id"]) if pd.notna(r["sleeper_id"]) else None, "headshot": r["headshot_url"] if pd.notna(r["headshot_url"]) else None,
            "s": season_line, "rank": num(t["pos_rank"], 0) if t is not None else None,
        }
        index.append(entry)

        log = lines[lines["id"] == pid].sort_values("week")
        game_log = [{
            "week": int(g["week"]), "opp": g["opp"], "home": bool(g["at_home"]),
            **{k: num(g[k], 1 if k.startswith("fp") or k.endswith("epa") else 0) for k in (
                "att", "cmp", "pass_yds", "pass_td", "ints", "sacks", "car", "rush_yds", "rush_td", "long_rush", "tgt", "rec", "rec_yds", "rec_td", "long_rec", "fp_ppr", "fp_half")},
        } for _, g in log.iterrows()]

        team = r["team"]
        nxt = upcoming[(upcoming["home_team"] == team) | (upcoming["away_team"] == team)].sort_values("week").head(5)
        ahead = []
        for _, g in nxt.iterrows():
            opp = g["away_team"] if g["home_team"] == team else g["home_team"]
            d = rank_of.get(pos, {}).get(opp, {})
            ahead.append({"week": int(g["week"]), "opp": opp, "home": g["home_team"] == team, "day": g["gameday"], "rank": d.get("rank"), "ppg": d.get("ppg")})
        faced = [{"week": x["week"], "opp": x["opp"], "rank": rank_of.get(pos, {}).get(x["opp"], {}).get("rank")} for x in game_log]

        page = {
            **entry,
            "age": num((now - pd.to_datetime(r["birth_date"], utc=True)).days / 365.25, 1) if pd.notna(r.get("birth_date")) else None,
            "exp": num(r.get("years_exp"), 0), "college": r.get("college"), "height": num(r.get("height"), 0), "weight": num(r.get("weight"), 0),
            "jersey": num(r.get("jersey_number"), 0), "draft": num(r.get("draft_number"), 0),
            "advanced": adv.get(pid), "log": game_log,
            "schedule": {"faced": faced, "ahead": ahead},
            "rushing": rush_detail.get(pid) if pos in ("RB", "QB") else None,
            "routes": rp["routes"].get(pid) if pos in ("WR", "TE", "RB") else None,
            "pressure": rp["pressure"].get(pid) if pos == "QB" else None,
            "blitz": blitz.get(pid) if pos == "QB" else None,
        }
        write(players_dir / f"{pid}.json", page)

    index.sort(key=lambda e: -((e["s"] or {}).get("fp_ppr") or 0))
    write(out / "index.json", index)
    write(out / "defense.json", defense)
    write(out / "meta.json", {
        "generated": now.isoformat(timespec="seconds"), "season": season, "week": week,
        "routes_season": part_season if rp["routes"] else None, "players": len(index),
    })
    print(f"Wrote {len(index)} players through week {week} (routes/pressure: {part_season})")


if __name__ == "__main__":
    main()
