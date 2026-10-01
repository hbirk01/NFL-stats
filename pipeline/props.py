"""
The BetTracker prop model: each player's expected stat line for a game, built
the way the game actually produces it.

  opportunity  x  team volume  x  efficiency  x  opponent  x  conditions

Opportunity. The player's share of his team's pass attempts (targets) and
rushes (carries), from the games he played this season (snap counts say who
played, so a game on the field without a touch counts as a zero), recent games
weighted more, blended with last season. The team's targets and carries are
then split among the players who are playing in proportion to those shares, so
the team adds up and a teammate who's out passes his share to the rest.

Team volume. The team's usual pass attempts and rushes, moved by the expected
game script: a team expected to score more throws and runs more; a favorite
runs more and throws less. The script comes from the betting market's spread
and total (or the model's, before lines are out).

Efficiency. Catch rate, yards per target, yards per carry, and for QBs
completion rate, yards and touchdowns per attempt: the player's own, shrunk
toward his position's average by how much he's shown.

Opponent. How the defense does against the position (yards per target and
catch rate allowed to WRs, TEs and RBs; yards per carry; passing yards per
attempt and completion rate), shrunk toward average for a small sample.

Conditions. Wind cuts passing.

Prop lines are medians (half the time over), and these stats skew right, so
the projection (a mean) is turned into a median before comparing with a line,
with a ratio fitted on past seasons.

  python pipeline/props.py --raw DIR --calibrate    # backtest 2022-2025, refit prop_spread.json
  python pipeline/props.py --raw DIR --lines DIR      # score against archived DraftKings lines
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from build import game_lines, injury_map, read, real_plays
from model import GAMES_CSV, load, pbp_for
import proplines

POSITIONS = ("QB", "RB", "WR", "TE")
DECAY = 0.85  # each older game counts this much of the next
PRIOR_GAMES = 3.0  # last season counts like this many games
PRIOR_EFF = 0.5  # last season's plays count half toward efficiency
# Shrinkage: opportunities of league-average efficiency added to a player's own.
K = {"catch": 40, "ypt": 60, "ypc": 80, "cmp": 150, "ypa": 200, "tdr": 400, "intr": 500}
DEF_K = 6.0  # games of league-average defense added to a defense's own

STATS = ("tgt", "rec", "rec_yds", "car", "rush_yds", "att", "cmp", "pass_yds", "pass_td", "ints")


# ── Data ─────────────────────────────────────────────────────────────────────

def season_data(raw: Path, season: int) -> dict | None:
    """Player-game lines (with zeros for games played without a touch), team-game volume, positions."""
    pbp = pbp_for(raw, season)
    if pbp is None:
        return None
    plays = real_plays(pbp)
    lines = game_lines(plays, pbp)
    roster = read(raw, f"rosters/roster_{season}.parquet")
    pos = dict(zip(roster["gsis_id"], roster["position"])) if roster is not None else {}
    lines["pos"] = lines["id"].map(pos)

    # Team volume per game: pass attempts (not sacks) and rushes.
    p = plays
    team = p.groupby(["game_id", "posteam"]).agg(
        week=("week", "first"),
        team_att=("pass_attempt", lambda s: int(((s == 1) & (p.loc[s.index, "sack"] != 1)).sum())),
        team_car=("rush_attempt", "sum"),
    ).reset_index().rename(columns={"posteam": "team"})

    # Games played without a touch: snap counts (by PFR id) say who was on the field.
    snaps = read(raw, f"snap_counts/snap_counts_{season}.parquet")
    if snaps is not None and roster is not None and "pfr_id" in roster.columns:
        pfr = dict(zip(roster["pfr_id"], roster["gsis_id"]))
        s = snaps[(snaps["game_type"] == "REG") & (snaps["offense_snaps"] > 0) & snaps["position"].isin(POSITIONS)].copy()
        s["id"] = s["pfr_player_id"].map(pfr)
        s = s.dropna(subset=["id"])
        s["snap_pct"] = s["offense_pct"]
        lines = lines.merge(s[["id", "game_id", "snap_pct"]], on=["id", "game_id"], how="outer")
        missing = lines["week"].isna()
        if missing.any():
            meta = s.drop_duplicates(["id", "game_id"]).set_index(["id", "game_id"])
            idx = list(zip(lines.loc[missing, "id"], lines.loc[missing, "game_id"]))
            lines.loc[missing, "posteam"] = [meta.loc[i, "team"] if i in meta.index else None for i in idx]
            lines.loc[missing, "opp"] = [meta.loc[i, "opponent"] if i in meta.index else None for i in idx]
            lines.loc[missing, "week"] = [meta.loc[i, "week"] if i in meta.index else None for i in idx]
            lines.loc[missing, "pos"] = lines.loc[missing, "id"].map(pos)
        for c in STATS + ("pass_td", "rec_td", "rush_td"):
            if c in lines.columns:
                lines[c] = lines[c].fillna(0)
    # Touchdowns scored and red-zone work (inside the 10), per player and team game, for the TD model.
    lines["td"] = lines.get("rush_td", 0) + lines.get("rec_td", 0)
    rz = p[p["yardline_100"] <= 10]
    rz_car = rz[rz["rush_attempt"] == 1].groupby(["rusher_player_id", "game_id"]).size().rename("rz_car")
    rz_tgt = rz[(rz["pass_attempt"] == 1) & rz["receiver_player_id"].notna()].groupby(["receiver_player_id", "game_id"]).size().rename("rz_tgt")
    lines = lines.merge(rz_car.rename_axis(["id", "game_id"]).reset_index(), on=["id", "game_id"], how="left")
    lines = lines.merge(rz_tgt.rename_axis(["id", "game_id"]).reset_index(), on=["id", "game_id"], how="left")
    lines[["rz_car", "rz_tgt", "td"]] = lines[["rz_car", "rz_tgt", "td"]].fillna(0)
    team_rz = rz.groupby(["game_id", "posteam"]).agg(
        team_rz_car=("rush_attempt", "sum"),
        team_rz_tgt=("pass_attempt", lambda s: int((s == 1).sum())),
    ).reset_index().rename(columns={"posteam": "team"})
    team_td = lines.groupby(["game_id", "posteam"])["td"].sum().rename("team_td").reset_index().rename(columns={"posteam": "team"})
    team = team.merge(team_rz, on=["game_id", "team"], how="left").merge(team_td, on=["game_id", "team"], how="left").fillna({"team_rz_car": 0, "team_rz_tgt": 0, "team_td": 0})
    lines = lines[lines["pos"].isin(POSITIONS) & lines["week"].notna()].copy()
    lines["week"] = lines["week"].astype(int)
    lines = lines.merge(
        team.rename(columns={"team": "posteam"})[["game_id", "posteam", "team_att", "team_car", "team_rz_car", "team_rz_tgt", "team_td"]], on=["game_id", "posteam"], how="left"
    )
    lines["season"] = season
    return {"lines": lines, "team": team, "pos": pos}


# ── Model ────────────────────────────────────────────────────────────────────

def _weighted(g: pd.DataFrame, week: int, cols: list[str]) -> pd.Series:
    """Recent-weighted sums of columns over a player's games before `week`."""
    w = DECAY ** (week - 1 - g["week"])
    return pd.Series({c: float((g[c] * w).sum()) for c in cols} | {"n": float(w.sum())})


class PropModel:
    """Projections for one season, from its games so far and last season's."""

    def __init__(self, cur: dict, prev: dict | None, volume_fit: dict):
        self.cur, self.prev, self.fit = cur, prev, volume_fit
        both = pd.concat([cur["lines"], prev["lines"]]) if prev else cur["lines"]
        self.league = league_rates(both)


    # Team volume ------------------------------------------------------------
    def team_volume(self, week: int) -> pd.DataFrame:
        cur = self.cur["team"][self.cur["team"]["week"] < week]
        prev = self.prev["team"] if self.prev else cur.iloc[0:0]
        rows = []
        for t in set(cur["team"]) | set(prev["team"]):
            c, p = cur[cur["team"] == t], prev[prev["team"] == t]
            w = DECAY ** (week - 1 - c["week"])
            pa, pc = (p["team_att"].mean(), p["team_car"].mean()) if len(p) else (self.league["team_att"], self.league["team_car"])
            n = w.sum()
            rows.append({
                "team": t,
                "att_base": (float((c["team_att"] * w).sum()) + pa * PRIOR_GAMES) / (n + PRIOR_GAMES),
                "car_base": (float((c["team_car"] * w).sum()) + pc * PRIOR_GAMES) / (n + PRIOR_GAMES),
            })
        return pd.DataFrame(rows).set_index("team")

    # Defense ----------------------------------------------------------------
    def defense(self, week: int) -> dict:
        """Per defense: factors vs league for yards/target and catch rate by position, ypc, QB ypa and cmp%."""
        cur = self.cur["lines"][self.cur["lines"]["week"] < week]
        prev = self.prev["lines"] if self.prev else cur.iloc[0:0]
        lg = self.league
        out: dict = {}
        for src, wt in ((cur, 1.0), (prev, PRIOR_EFF)):
            for (opp, pos), g in src.groupby(["opp", "pos"]):
                d = out.setdefault(opp, {}).setdefault(pos, {"tgt": 0, "rec": 0, "rec_yds": 0, "car": 0, "rush_yds": 0, "att": 0, "cmp": 0, "pass_yds": 0, "games": 0})
                for c in ("tgt", "rec", "rec_yds", "car", "rush_yds", "att", "cmp", "pass_yds"):
                    d[c] += wt * float(g[c].sum())
                d["games"] += wt * g["game_id"].nunique()
        factors = {}
        for opp, by_pos in out.items():
            f = {}
            for pos, d in by_pos.items():
                shrink = d["games"] / (d["games"] + DEF_K)
                def fac(num, den, league):
                    return 1.0 if not den or not league else 1 + (num / den / league - 1) * shrink
                f[pos] = {
                    "ypt": fac(d["rec_yds"], d["tgt"], lg["ypt"].get(pos)),
                    "catch": fac(d["rec"], d["tgt"], lg["catch"].get(pos)),
                    "ypc": fac(d["rush_yds"], d["car"], lg["ypc"].get(pos)),
                    "ypa": fac(d["pass_yds"], d["att"], lg["ypa"]),
                    "cmp": fac(d["cmp"], d["att"], lg["cmp"]),
                }
            factors[opp] = f
        return factors

    # Players ----------------------------------------------------------------
    def players(self, week: int) -> pd.DataFrame:
        """Each player's opportunity shares and efficiency before `week`."""
        cur = self.cur["lines"][self.cur["lines"]["week"] < week].copy()
        prev = self.prev["lines"].copy() if self.prev else cur.iloc[0:0].copy()
        lg = self.league
        for df in (cur, prev):
            df["tshare"] = np.where(df["team_att"] > 0, df["tgt"] / df["team_att"], 0)
            df["cshare"] = np.where(df["team_car"] > 0, df["car"] / df["team_car"], 0)
            df["ashare"] = np.where(df["team_att"] > 0, df["att"] / df["team_att"], 0)
        cols = ["tshare", "cshare", "ashare"]
        eff = ["tgt", "rec", "rec_yds", "car", "rush_yds", "att", "cmp", "pass_yds", "pass_td", "ints"]
        c_sh = cur.groupby("id").apply(lambda g: _weighted(g, week, cols), include_groups=False) if len(cur) else pd.DataFrame(columns=cols + ["n"])
        p_sh = prev.groupby("id")[cols].mean() if len(prev) else pd.DataFrame(columns=cols)
        c_eff = cur.groupby("id")[eff].sum() if len(cur) else pd.DataFrame(columns=eff)
        p_eff = prev.groupby("id")[eff].sum() if len(prev) else pd.DataFrame(columns=eff)
        ids = set(c_sh.index) | set(p_sh.index)
        last = pd.concat([prev, cur]).sort_values(["season", "week"]).groupby("id").last()
        rows = []
        for pid in ids:
            info = last.loc[pid] if pid in last.index else None
            pos = info["pos"] if info is not None else None
            if pos not in POSITIONS:
                continue
            n = float(c_sh.loc[pid, "n"]) if pid in c_sh.index else 0.0
            sh = {}
            for c in cols:
                cur_sum = float(c_sh.loc[pid, c]) if pid in c_sh.index else 0.0
                prior = float(p_sh.loc[pid, c]) if pid in p_sh.index else None
                if prior is None:  # no history last season: this season alone (or nothing)
                    sh[c] = cur_sum / n if n else 0.0
                else:
                    sh[c] = (cur_sum + prior * PRIOR_GAMES) / (n + PRIOR_GAMES)
            e = (c_eff.loc[pid] if pid in c_eff.index else pd.Series(0.0, index=eff)) + PRIOR_EFF * (p_eff.loc[pid] if pid in p_eff.index else pd.Series(0.0, index=eff))

            def rate(num, den, league, k):
                return (num + league * k) / (den + k)

            rows.append({
                "id": pid, "pos": pos, "team": info["posteam"],
                "tshare": sh["tshare"], "cshare": sh["cshare"], "ashare": sh["ashare"], "games": n,
                "catch": rate(e["rec"], e["tgt"], lg["catch"].get(pos, 0.65), K["catch"]),
                "ypt": rate(e["rec_yds"], e["tgt"], lg["ypt"].get(pos, 7.5), K["ypt"]),
                "ypc": rate(e["rush_yds"], e["car"], lg["ypc"].get(pos, 4.2), K["ypc"]),
                "cmp_rate": rate(e["cmp"], e["att"], lg["cmp"], K["cmp"]),
                "ypa": rate(e["pass_yds"], e["att"], lg["ypa"], K["ypa"]),
                "tdr": rate(e["pass_td"], e["att"], lg["tdr"], K["tdr"]),
                "intr": rate(e["ints"], e["att"], lg["intr"], K["intr"]),
            })
        return pd.DataFrame(rows).set_index("id")

    # Projection ---------------------------------------------------------------
    def project(self, week: int, games: pd.DataFrame, team_of: dict, starters: set | None = None) -> pd.DataFrame:
        """
        Projected stat lines for the week's games (nflverse games rows: home/away
        team, spread_line = home favored by, total_line, wind). `team_of`: the
        players expected to play, and their team this week. `starters`: QBs known
        to be starting (a sportsbook passing line says so), who get a starter's
        share even with little history; their team's other QBs get none.
        """
        players = self.players(week)
        vol = self.team_volume(week)
        dfn = self.defense(week)
        fit = self.fit
        out = []
        for _, g in games.iterrows():
            total = g.get("total_line") if pd.notna(g.get("total_line")) else 44.0
            spread = g.get("spread_line") if pd.notna(g.get("spread_line")) else 0.0
            wind = g.get("wind")
            wind_f = 0.88 if pd.notna(wind) and wind >= 20 else 0.94 if pd.notna(wind) and wind >= 15 else 1.0
            for team, opp, margin in ((g["home_team"], g["away_team"], spread), (g["away_team"], g["home_team"], -spread)):
                if team not in vol.index:
                    continue
                implied = total / 2 + margin / 2
                att = vol.loc[team, "att_base"] + fit["att_pts"] * (implied - fit["pts0"]) + fit["att_margin"] * margin
                car = vol.loc[team, "car_base"] + fit["car_pts"] * (implied - fit["pts0"]) + fit["car_margin"] * margin
                playing = players[players.index.isin({pid for pid, t in team_of.items() if t == team})].copy()
                qbs = playing[playing["pos"] == "QB"]
                named = [pid for pid in qbs.index if starters and pid in starters]
                if named:
                    for pid in qbs.index:
                        if pid in named:
                            playing.loc[pid, "ashare"] = max(playing.loc[pid, "ashare"], self.league["qb_att_share"])
                            playing.loc[pid, "cshare"] = max(playing.loc[pid, "cshare"], self.league["qb_car_share"])
                        else:
                            playing.loc[pid, ["ashare", "cshare", "tshare"]] = 0.0
                # The team's targets and carries, split by share among those playing.
                tsum, csum = playing["tshare"].sum(), playing["cshare"].sum()
                ts = self.league["tgt_rate"] / tsum if tsum else 0.0
                cs = 1.0 / csum if csum else 0.0
                d = dfn.get(opp, {})
                for pid, r in playing.iterrows():
                    f = d.get(r["pos"], {})
                    tgt = r["tshare"] * att * ts
                    rec = tgt * r["catch"] * f.get("catch", 1.0)
                    rec_yds = tgt * r["ypt"] * f.get("ypt", 1.0) * wind_f
                    c = r["cshare"] * car * cs
                    rush_yds = c * r["ypc"] * f.get("ypc", 1.0)
                    a = r["ashare"] * att if r["pos"] == "QB" else 0.0
                    qb = d.get("QB", {})
                    out.append({
                        "id": pid, "week": week, "team": team, "opp": opp, "pos": r["pos"],
                        # The inputs, for showing why: this week's shares and the team's expected volume.
                        "tgt_share": r["tshare"] * ts / self.league["tgt_rate"] if tsum else 0.0, "car_share": r["cshare"] * cs if csum else 0.0,
                        "team_att": att, "team_car": car,
                        "tgt": tgt, "rec": rec, "rec_yds": rec_yds, "car": c, "rush_yds": rush_yds,
                        "att": a, "cmp": a * r["cmp_rate"] * qb.get("cmp", 1.0),
                        "pass_yds": a * r["ypa"] * qb.get("ypa", 1.0) * wind_f,
                        "pass_td": a * r["tdr"] * (implied / fit["pts0"]),
                        "ints": a * r["intr"],
                    })
        return pd.DataFrame(out)


def league_rates(lines: pd.DataFrame) -> dict:
    by = lines.groupby("pos")[["tgt", "rec", "rec_yds", "car", "rush_yds"]].sum()
    qb = lines[lines["pos"] == "QB"][["att", "cmp", "pass_yds", "pass_td", "ints"]].sum()
    teams = lines.drop_duplicates(["game_id", "posteam"])
    return {
        "catch": (by["rec"] / by["tgt"]).to_dict(),
        "ypt": (by["rec_yds"] / by["tgt"]).to_dict(),
        "ypc": (by["rush_yds"] / by["car"]).to_dict(),
        "cmp": float(qb["cmp"] / qb["att"]), "ypa": float(qb["pass_yds"] / qb["att"]),
        "tdr": float(qb["pass_td"] / qb["att"]), "intr": float(qb["ints"] / qb["att"]),
        "team_att": float(teams["team_att"].mean()), "team_car": float(teams["team_car"].mean()),
        # A starting QB's usual share of his team's attempts and rushes (the top passer each game).
        **_starter_shares(lines),
        # Share of pass attempts that have a target (the rest: throwaways, spikes).
        "tgt_rate": float(lines["tgt"].sum() / teams["team_att"].sum()),
    }


def _starter_shares(lines: pd.DataFrame) -> dict:
    qb = lines[(lines["pos"] == "QB") & (lines["team_att"] > 0)]
    top = qb.sort_values("att").groupby(["game_id", "posteam"]).last()
    return {
        "qb_att_share": float((top["att"] / top["team_att"]).median()),
        "qb_car_share": float((top["car"] / top["team_car"].where(top["team_car"] > 0)).median()),
    }


def fit_volume(seasons: list[dict], games: pd.DataFrame) -> dict:
    """How team pass attempts and rushes move with implied points and expected margin (least squares)."""
    rows = []
    for sd in seasons:
        team = sd["team"]
        season = int(sd["lines"]["season"].iloc[0])
        g = games[(games["season"] == season) & (games["game_type"] == "REG")]
        for _, x in g.iterrows():
            if pd.isna(x.get("spread_line")) or pd.isna(x.get("total_line")):
                continue
            for t, m in ((x["home_team"], x["spread_line"]), (x["away_team"], -x["spread_line"])):
                tg = team[(team["game_id"] == x["game_id"]) & (team["team"] == t)]
                hist = team[(team["team"] == t) & (team["week"] < x["week"])]
                if not len(tg) or len(hist) < 3:
                    continue
                rows.append({"att": tg["team_att"].iloc[0] - hist["team_att"].mean(), "car": tg["team_car"].iloc[0] - hist["team_car"].mean(), "pts": x["total_line"] / 2 + m / 2, "margin": m})
    df = pd.DataFrame(rows)
    pts0 = float(df["pts"].mean())
    X = np.vstack([np.ones(len(df)), df["pts"] - pts0, df["margin"]]).T
    (_, ap, am), *_ = np.linalg.lstsq(X, df["att"].to_numpy(), rcond=None)
    (_, cp, cm), *_ = np.linalg.lstsq(X, df["car"].to_numpy(), rcond=None)
    return {"pts0": pts0, "att_pts": float(ap), "att_margin": float(am), "car_pts": float(cp), "car_margin": float(cm)}


# ── Backtest ─────────────────────────────────────────────────────────────────

PROP_STATS = ("rec", "rec_yds", "rush_yds", "car", "pass_yds", "att", "cmp", "pass_td", "ints")


def baseline(cur: pd.DataFrame, prev: pd.DataFrame, week: int, stat: str) -> pd.Series:
    """The old way: this season's average per game blended with last season's (3 games' weight)."""
    c = cur[cur["week"] < week].groupby("id")[stat].agg(["sum", "count"])
    p = prev.groupby("id")[stat].mean()
    ids = c.index.union(p.index)
    s, n = c["sum"].reindex(ids).fillna(0), c["count"].reindex(ids).fillna(0)
    pm = p.reindex(ids)
    return pd.Series(np.where(pm.notna(), (s + pm.fillna(0) * 3) / (n + 3), np.where(n > 0, s / n.replace(0, 1), np.nan)), index=ids)


def walk(raw: Path, seasons: list[int], games: pd.DataFrame) -> pd.DataFrame:
    """Projections vs actuals for every player-week of the given seasons (players who played)."""
    data = {s: season_data(raw, s) for s in range(min(seasons) - 3, max(seasons) + 1)}
    out = []
    for s in seasons:
        fit_on = [data[x] for x in (s - 3, s - 2, s - 1) if data.get(x)]
        fit = fit_volume(fit_on, games)
        model = PropModel(data[s], data.get(s - 1), fit)
        cur = data[s]["lines"]
        prev = data[s - 1]["lines"] if data.get(s - 1) else cur.iloc[0:0]
        g_season = games[(games["season"] == s) & (games["game_type"] == "REG")]
        for week in sorted(cur["week"].unique()):
            actual = cur[cur["week"] == week]
            # Who played and for whom: known before kickoff from rosters and injury reports.
            proj = model.project(int(week), g_season[g_season["week"] == week], dict(zip(actual["id"], actual["posteam"])))
            if not len(proj):
                continue
            m = proj.merge(actual[["id"] + list(PROP_STATS) + ["game_id"]], on="id", suffixes=("", "_act"))
            for stat in PROP_STATS:
                m[f"{stat}_base"] = m["id"].map(baseline(cur, prev, int(week), stat))
            m["season"] = s
            out.append(m)
        print(f"  {s}: {sum(len(x) for x in out if x['season'].iloc[0] == s)} player-weeks")
    return pd.concat(out, ignore_index=True)


# ── From a projection to a line ──────────────────────────────────────────────

SPREAD_FILE = Path(__file__).with_name("prop_spread.json")
# The model's confident unders beat blind unders in testing (2026 weeks 1-3);
# its overs didn't. It only bets unders, between these chances of going over:
# sure enough, but not so far off the line that the book likely knows
# something the model doesn't (a new starter, an injury not yet reported).
UNDER_AT = 0.42
UNDER_FLOOR = 0.25


def calibrate(walked: pd.DataFrame) -> dict:
    """How actual results spread around projections, per stat and projection size (thirds): 101 quantiles of actual/projection."""
    out = {}
    for st in PROP_STATS:
        h = walked[walked[st] > 0.5]
        cuts = h[st].quantile([1 / 3, 2 / 3]).round(3).to_list()
        bins = []
        for lo, hi in ((-1, cuts[0]), (cuts[0], cuts[1]), (cuts[1], 1e9)):
            g = h[(h[st] > lo) & (h[st] <= hi)]
            bins.append(np.quantile(g[f"{st}_act"] / g[st], np.linspace(0, 1, 101)).round(4).tolist())
        out[st] = {"cuts": cuts, "ratios": bins}
    return out


def _ratios(spread: dict, stat: str, proj: float) -> np.ndarray:
    s = spread[stat]
    i = 0 if proj <= s["cuts"][0] else 1 if proj <= s["cuts"][1] else 2
    return np.asarray(s["ratios"][i])


def p_over(spread: dict, stat: str, proj: float, line: float) -> float | None:
    """Chance the stat goes over the line, from how past results spread around projections."""
    if stat not in spread or proj <= 0:
        return None
    return float((_ratios(spread, stat, proj) * proj > line).mean())


def median(spread: dict, stat: str, proj: float) -> float:
    """The projection as a median (what a line is), not a mean."""
    return float(np.median(_ratios(spread, stat, proj)) * proj) if stat in spread and proj > 0 else proj


# ── This week ────────────────────────────────────────────────────────────────

def upcoming(raw: Path, season: int, games: pd.DataFrame, spread: dict | None = None) -> dict | None:
    """
    The next week's DraftKings prop lines with the model's projection, median
    and chance of going over each, and the inputs behind it. Who plays: the
    latest active roster, minus players out or doubtful on this week's report.
    """
    spread = spread or json.loads(SPREAD_FILE.read_text())
    cur, prev = season_data(raw, season), season_data(raw, season - 1)
    if cur is None or prev is None:
        return None
    prev2 = season_data(raw, season - 2)
    model = PropModel(cur, prev, fit_volume([x for x in (prev2, prev) if x], games))
    left = games[(games["season"] == season) & (games["game_type"] == "REG") & games["result"].isna()]
    if not len(left):
        return None
    week = int(left["week"].min())
    wk_games = left[left["week"] == week]

    roster = read(raw, f"rosters/roster_{season}.parquet")
    roster = roster[roster["week"] == roster["week"].max()]
    injuries = injury_map(read(raw, f"injuries/injuries_{season}.parquet"))
    report = max((i["week"] for i in injuries.values()), default=None)
    # This week's report once it's out (Wednesday on); before that, last week's outs.
    out_now = {g for g, i in injuries.items() if i["status"] in ("Out", "Doubtful")} if report == week else {g for g, i in injuries.items() if i["status"] == "Out"}
    act = roster[(roster["status"] == "ACT") & roster["position"].isin(POSITIONS) & ~roster["gsis_id"].isin(out_now)]
    team_of = dict(zip(act["gsis_id"], act["team"]))

    names = dict(zip(roster["gsis_id"], roster["full_name"]))
    espn_to = {str(int(e)): g for e, g in zip(roster["espn_id"], roster["gsis_id"]) if pd.notna(e)}
    events = [str(int(e)) for e in wk_games["espn"] if pd.notna(e)]
    lines = proplines.week_lines(events)
    # A passing line means the book expects him to start.
    starters = {espn_to[x["athlete"]] for x in lines if x["stat"] in ("pass_yds", "att") and x["athlete"] in espn_to}
    proj = model.project(week, wk_games, team_of, starters).set_index("id")
    rows = []
    for x in lines:
        g = espn_to.get(x["athlete"])
        if g not in proj.index or x["stat"] not in PROP_STATS:
            continue
        r = proj.loc[g]
        mean = float(r[x["stat"]])
        po = p_over(spread, x["stat"], mean, x["line"])
        rows.append({
            "espn": x["athlete"], "id": g, "name": names.get(g), "team": r["team"], "opp": r["opp"], "pos": r["pos"], "event": x["event"],
            "stat": x["stat"], "line": x["line"], "open": x["open"],
            "proj": round(mean, 1), "median": round(median(spread, x["stat"], mean), 1), "p_over": None if po is None else round(po, 3),
            "inputs": {
                "tgt": round(float(r["tgt"]), 1), "car": round(float(r["car"]), 1), "att": round(float(r["att"]), 1),
                "tgt_share": round(float(r["tgt_share"]), 3), "car_share": round(float(r["car_share"]), 3),
                "team_att": round(float(r["team_att"]), 1), "team_car": round(float(r["team_car"]), 1),
            },
        })
    rows.sort(key=lambda x: (x["p_over"] if x["p_over"] is not None else 0.5))
    # Every projected player's numbers by ESPN id, for lines that aren't DraftKings' (friends' bets).
    by_espn = {e: g for e, g in espn_to.items() if g in proj.index}
    # Anytime touchdown chances for everyone expected to play (pipeline/tds.py).
    try:
        import tds

        gsis_espn = {g: e for e, g in espn_to.items()}
        td_rows = tds.upcoming_tds(cur["lines"], prev["lines"], week, wk_games, team_of, names, gsis_espn)
    except Exception as e:  # noqa: BLE001
        print(f"  anytime TDs skipped: {e}")
        td_rows = []
    return {"season": season, "week": week, "report_week": report, "tds": td_rows, "under_at": UNDER_AT, "under_floor": UNDER_FLOOR, "props": rows, "_lines": lines,
            "_proj": {e: {st: float(proj.loc[g, st]) for st in PROP_STATS} | {"name": names.get(g), "team": proj.loc[g, "team"], "inputs": {k: float(proj.loc[g, k]) for k in ("tgt", "car", "att", "tgt_share", "car_share", "team_att", "team_car")}} for e, g in by_espn.items()}}


ARCHIVE = "https://raw.githubusercontent.com/hbirk01/NFL-stats/data/props-lines"


def archive(out: Path, season: int, week: int, lines: list[dict], games: pd.DataFrame) -> int:
    """
    Keeps every week's DraftKings lines on the data branch (props-lines/), which
    is rebuilt from scratch each run: last run's files are carried over, this
    week's are written fresh, and last week's are refreshed to their closing
    numbers. Returns how many weeks are archived.
    """
    import urllib.request

    folder = out / "props-lines"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(f"{ARCHIVE}/index.json", timeout=20) as r:
            names = json.load(r)
    except Exception:
        names = []
    for name in names:
        try:
            with urllib.request.urlopen(f"{ARCHIVE}/{name}", timeout=20) as r:
                (folder / name).write_bytes(r.read())
        except Exception as e:
            print(f"  props archive: couldn't carry {name}: {e}")
    (folder / f"{season}-w{week}.json").write_text(json.dumps(lines, separators=(",", ":")))
    # Last week's closing numbers; and on the first run, every earlier week ESPN still has.
    for w in range(1, week):
        if w < week - 1 and (folder / f"{season}-w{w}.json").exists():
            continue
        played = games[(games["season"] == season) & (games["week"] == w) & games["espn"].notna()]
        closing = proplines.week_lines([str(int(e)) for e in played["espn"]])
        if closing:
            (folder / f"{season}-w{w}.json").write_text(json.dumps(closing, separators=(",", ":")))
    names = sorted(f.name for f in folder.glob("*-w*.json"))
    (folder / "index.json").write_text(json.dumps(names))
    return len(names)


# Confidence: how often the model's unders have actually won, by its chance of the
# over (testing found no steady "further from the line = better" pattern, so it's
# measured, not assumed). Recomputed from the archived lines every data run;
# small samples lean toward break-even at -110.
BUCKETS = [(0.0, 0.25), (0.25, 0.30), (0.30, 0.34), (0.34, 0.38), (0.38, 0.42), (0.42, 0.46), (0.46, 0.50)]
BREAK_EVEN = 0.524
PRIOR_N = 40


def confidence_table(scored: pd.DataFrame) -> list[dict]:
    """Per range of the over chance: unders won and lost so far, and the (shrunk) win rate."""
    s = scored.dropna(subset=["p_over"])
    s = s[s["act"] != s["line"]]
    out = []
    for lo, hi in BUCKETS:
        g = s[(s["p_over"] > lo) & (s["p_over"] <= hi)]
        won = int((g["act"] < g["line"]).sum())
        lost = len(g) - won
        out.append({"lo": lo, "hi": hi, "won": won, "lost": lost, "rate": round((won + BREAK_EVEN * PRIOR_N) / (won + lost + PRIOR_N), 3)})
    return out


def confidence_of(table: list[dict] | None, p: float | None) -> dict | None:
    """The record for an under at this chance of going over (None for overs)."""
    if p is None or not table:
        return None
    for b in table:
        if b["lo"] < p <= b["hi"] or (b["lo"] == 0 and p == 0):
            return {"rate": b["rate"], "won": b["won"], "lost": b["lost"]}
    return None


def with_confidence(up: dict, raw: Path, season: int, games: pd.DataFrame, lines_dir: Path) -> None:
    """Scores this season's archived lines and adds each prop's confidence (and the table) to `up`."""
    walked = walk(raw, [season], games)
    roster = read(raw, f"rosters/roster_{season}.parquet")
    spread = json.loads(SPREAD_FILE.read_text())
    table = confidence_table(score_lines(walked, lines_dir, roster, spread))
    up["confidence"] = table
    for x in up["props"]:
        x["confidence"] = confidence_of(table, x["p_over"])


def score_lines(walked: pd.DataFrame, lines_dir: Path, roster: pd.DataFrame, spread: dict) -> pd.DataFrame:
    """Archived DraftKings lines joined with the walked projections and results."""
    espn = {str(int(e)): g for e, g in zip(roster["espn_id"], roster["gsis_id"]) if pd.notna(e)}
    rows = []
    for f in sorted(lines_dir.glob("*-w*.json")):
        season, week = (int(x) for x in f.stem.replace("w", "").split("-"))
        w = walked[(walked["season"] == season) & (walked["week"] == week)].set_index("id")
        for x in json.loads(f.read_text()):
            g = espn.get(x["athlete"])
            if g not in w.index or x["stat"] not in PROP_STATS:
                continue
            r = w.loc[g]
            rows.append({"season": season, "week": week, "stat": x["stat"], "line": x["line"], "proj": r[x["stat"]], "act": r[f"{x['stat']}_act"],
                         "p_over": p_over(spread, x["stat"], r[x["stat"]], x["line"])})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--calibrate", action="store_true", help="backtest 2022-2025 and rewrite prop_spread.json")
    ap.add_argument("--lines", help="a folder of archived lines (<season>-w<week>.json) to score")
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    raw = Path(args.raw)
    raw.mkdir(parents=True, exist_ok=True)
    games = load(raw, "games.csv", GAMES_CSV)
    if args.calibrate:
        walked = walk(raw, [2022, 2023, 2024, 2025], games)
        SPREAD_FILE.write_text(json.dumps(calibrate(walked), separators=(",", ":")))
        print(f"wrote {SPREAD_FILE.name}")
    if args.lines:
        walked = walk(raw, [args.season], games)
        roster = read(raw, f"rosters/roster_{args.season}.parquet")
        L = score_lines(walked, Path(args.lines), roster, json.loads(SPREAD_FILE.read_text())).dropna(subset=["p_over"])
        L = L[L["act"] != L["line"]]
        over = (L["act"] > L["line"]).astype(float)
        print(f"{len(L)} lines: over {over.mean():.1%}")
        unders = L[(L["p_over"] <= UNDER_AT) & (L["p_over"] > UNDER_FLOOR)]
        won = int((unders["act"] < unders["line"]).sum())
        print(f"model unders ({UNDER_FLOOR} < p_over <= {UNDER_AT}): {won}-{len(unders) - won} ({won / max(1, len(unders)):.1%})")
        for week, g in unders.groupby("week"):
            w = int((g["act"] < g["line"]).sum())
            print(f"  week {week}: {w}-{len(g) - w}")


if __name__ == "__main__":
    main()
