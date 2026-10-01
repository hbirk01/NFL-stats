"""
Anytime touchdown chances: how likely each player is to score (rushing or
receiving) in a game.

  team's expected touchdowns  x  the player's expected share of them

Team touchdowns come from the market's implied points (spread and total).
A player's share comes from his usage: carries and targets inside the 10-yard
line (where most touchdowns happen) and overall, recent games weighted more,
blended with last season, with weights fitted on past seasons. Touchdowns are
rare and roughly independent, so the chance of at least one is
1 - e^(-expected touchdowns).

Sportsbooks' touchdown prices aren't available for free, so this gives fair
chances to compare with the odds people actually get.

  python pipeline/tds.py --raw DIR        # fit on 2019-2021, test 2022 on
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from props import DECAY, PRIOR_GAMES, season_data
from model import GAMES_CSV, load

FEATURES = ["rz_car_share", "rz_tgt_share", "car_share", "tgt_share"]
COEF_FILE = Path(__file__).with_name("td_fit.json")


def implied_points(games: pd.DataFrame) -> pd.DataFrame:
    """Each team's implied points per game from the closing spread and total."""
    rows = []
    for _, g in games.iterrows():
        if pd.isna(g.get("spread_line")) or pd.isna(g.get("total_line")):
            continue
        for team, m in ((g["home_team"], g["spread_line"]), (g["away_team"], -g["spread_line"])):
            rows.append({"game_id": g["game_id"], "team": team, "implied": g["total_line"] / 2 + m / 2})
    return pd.DataFrame(rows)


def shares_before(cur: pd.DataFrame, prev: pd.DataFrame | None, week: int) -> pd.DataFrame:
    """Each player's usage shares from games before `week`: recent-weighted, blended with last season."""
    def share(df):
        out = pd.DataFrame({"id": df["id"], "week": df["week"]})
        for col, team_col, name in (("rz_car", "team_rz_car", "rz_car_share"), ("rz_tgt", "team_rz_tgt", "rz_tgt_share"), ("car", "team_car", "car_share"), ("tgt", "team_att", "tgt_share")):
            out[name] = np.where(df[team_col] > 0, df[col] / df[team_col].where(df[team_col] > 0, 1), 0.0)
        out["td"] = df["td"]
        return out

    c = share(cur[cur["week"] < week])
    c["w"] = DECAY ** (week - 1 - c["week"])
    cols = FEATURES + ["td"]
    num = c[cols].multiply(c["w"], axis=0).groupby(c["id"]).sum()
    n = c.groupby("id")["w"].sum()
    out = num.div(n, axis=0) if len(c) else pd.DataFrame(columns=cols)
    out["n"] = n
    if prev is not None and len(prev):
        p = share(prev).groupby("id")[cols].mean()
        ids = out.index.union(p.index)
        out = out.reindex(ids)
        p = p.reindex(ids)
        nn = out["n"].fillna(0)
        for col in cols:
            has_prior = p[col].notna()
            mine = out[col].fillna(0) * nn
            out[col] = np.where(has_prior, (mine + p[col].fillna(0) * PRIOR_GAMES) / (nn + PRIOR_GAMES), np.where(nn > 0, mine / nn.where(nn > 0, 1), 0.0))
        out["n"] = nn
    return out


def season_rows(data: dict, games: pd.DataFrame) -> pd.DataFrame:
    """Per player-game with prior data: pre-game shares, team implied points and team TDs, and the player's TDs."""
    imp = implied_points(games)
    out = []
    for season, sd in sorted(data.items()):
        prev = data.get(season - 1)
        cur = sd["lines"]
        for week in sorted(cur["week"].unique()):
            if week < 2 and prev is None:
                continue
            sh = shares_before(cur, prev["lines"] if prev else None, int(week))
            act = cur[cur["week"] == week][["id", "game_id", "posteam", "pos", "td"]].rename(columns={"td": "td_act"})
            m = act.merge(sh, left_on="id", right_index=True, how="inner").merge(imp.rename(columns={"team": "posteam"}), on=["game_id", "posteam"], how="left")
            m["season"], m["week"] = season, int(week)
            out.append(m)
    return pd.concat(out, ignore_index=True).dropna(subset=["implied"])


def fit(rows: pd.DataFrame) -> dict:
    """Team TDs from implied points, and the player's TD share from usage (least squares)."""
    team = rows.drop_duplicates(["game_id", "posteam"])
    tt = rows.groupby(["game_id", "posteam"])["td_act"].sum()  # TDs by players in the data
    team = team.set_index(["game_id", "posteam"]).join(tt.rename("team_td"))
    b, a = np.polyfit(team["implied"], team["team_td"], 1)
    exp_team = a + b * rows["implied"]
    X = rows[FEATURES].to_numpy() * exp_team.to_numpy()[:, None]
    beta, *_ = np.linalg.lstsq(X, rows["td_act"].to_numpy(), rcond=None)
    return {"team_a": float(a), "team_b": float(b), "beta": [float(x) for x in beta]}


def expected_tds(rows: pd.DataFrame, f: dict) -> np.ndarray:
    exp_team = np.maximum(0.3, f["team_a"] + f["team_b"] * rows["implied"].to_numpy())
    share = np.clip(rows[FEATURES].to_numpy() @ np.asarray(f["beta"]), 0.0, 0.9)
    return exp_team * share


def p_anytime(lam: np.ndarray | float) -> np.ndarray | float:
    return 1 - np.exp(-np.asarray(lam))


def fair_odds(p: float) -> int:
    """American odds with no margin for a chance p."""
    p = min(max(p, 0.005), 0.995)
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def upcoming_tds(cur: pd.DataFrame, prev: pd.DataFrame | None, week: int, wk_games: pd.DataFrame, team_of: dict, names: dict, espn_of: dict, f: dict | None = None) -> list[dict]:
    """This week's anytime TD chances for the players expected to play (5%+ only)."""
    f = f or json.loads(COEF_FILE.read_text())
    sh = shares_before(cur, prev, week)
    imp = implied_points(wk_games)
    opp_of = {}
    for _, g in wk_games.iterrows():
        opp_of[g["home_team"]], opp_of[g["away_team"]] = g["away_team"], g["home_team"]
    pos_of = dict(zip(cur["id"], cur["pos"])) | (dict(zip(prev["id"], prev["pos"])) if prev is not None else {})
    rows = []
    for pid, team in team_of.items():
        if pid not in sh.index or team not in opp_of:
            continue
        r = imp[imp["team"] == team]
        if not len(r):
            continue
        rows.append({"id": pid, "team": team, "implied": float(r["implied"].iloc[0]), **{k: float(sh.loc[pid, k]) for k in FEATURES}})
    if not rows:
        return []
    df = pd.DataFrame(rows)
    lam = expected_tds(df, f)
    out = []
    for (_, r), l in zip(df.iterrows(), lam):
        p = float(p_anytime(l))
        if p < 0.05 or not espn_of.get(r["id"]):
            continue
        out.append({
            "espn": espn_of[r["id"]], "id": r["id"], "name": names.get(r["id"]), "team": r["team"], "opp": opp_of[r["team"]], "pos": pos_of.get(r["id"]),
            "p": round(p, 3), "fair": fair_odds(p),
            "inputs": {"team_tds": round(max(0.3, f["team_a"] + f["team_b"] * r["implied"]), 2), **{k: round(r[k], 3) for k in FEATURES}},
        })
    return sorted(out, key=lambda x: -x["p"])


def report(rows: pd.DataFrame, p: np.ndarray, label: str) -> None:
    y = (rows["td_act"] >= 1).astype(float).to_numpy()
    pc = np.clip(p, 1e-4, 1 - 1e-4)
    ll = -np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))
    brier = np.mean((pc - y) ** 2)
    print(f"  {label:12s} log loss {ll:.4f}  brier {brier:.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="raw")
    args = ap.parse_args()
    raw = Path(args.raw)
    games = load(raw, "games.csv", GAMES_CSV)
    data = {s: season_data(raw, s) for s in range(2019, 2027)}
    data = {s: d for s, d in data.items() if d}
    rows = season_rows(data, games)
    train, test = rows[rows["season"] <= 2021], rows[rows["season"] >= 2022]
    f = fit(train)
    print("fit", json.dumps(f))
    COEF_FILE.write_text(json.dumps(f))
    # The simple way: the player's own touchdowns per game (recent-weighted, blended with last season).
    lam = expected_tds(test, f)
    p_model, p_base = p_anytime(lam), p_anytime(test["td"].to_numpy())
    for season in sorted(test["season"].unique()):
        m = (test["season"] == season).to_numpy()
        print(season)
        report(test[m], p_model[m], "model")
        report(test[m], p_base[m], "TD rate")
    print("all")
    report(test, p_model, "model")
    report(test, p_base, "TD rate")
    # Calibration: predicted vs actual in bins.
    y = (test["td_act"] >= 1).astype(float).to_numpy()
    bins = [0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 1]
    print("calibration (model):")
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (p_model > lo) & (p_model <= hi)
        if m.sum():
            print(f"  {lo:.2f}-{hi:.2f}: predicted {p_model[m].mean():.3f}  actual {y[m].mean():.3f}  n={m.sum()}")


if __name__ == "__main__":
    main()
