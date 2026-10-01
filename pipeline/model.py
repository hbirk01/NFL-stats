"""
The BetTracker model: predicts each NFL game's margin and total from team
efficiency, then bets spreads, totals and moneylines where it disagrees with
the sportsbook line by enough. No AI: a transparent formula over free data.

Ratings. Each team's EPA per play on offense and allowed on defense, game by
game, counting only plays while the game is competitive (garbage time says
little about a team). Early in a season they lean on last season's (pulled
halfway to the league average for offseason changes); each game played shifts
weight to this season, and a team with a new starting QB keeps only half of
last season's offense (that offense was someone else's). Each QB also has his
own rating (EPA per dropback, career to date): the offense moves by the gap
between this week's starter and the QBs who produced its rating. Defense counts half: it's much less consistent week to
week than offense.

Game. Expected EPA/play for each offense = league average + its offense rating
+ the other defense's rating. Margin = the difference x plays x a fitted scale,
plus home field, rest and a backup-QB penalty. Total = the league's scoring
+ both expected EPAs x plays x a fitted scale, plus weather (wind and cold
lower scoring, domes raise it a touch). Totals are then centered on the
market's: the average gap between the model and the lines over recent games is
taken out, so the model only bets where one game differs from the rest, not on
its own idea of the league's scoring level (which ran 1-2 points high, every
season, and had it betting overs).

Bets. Spread or total when the model's number differs from the line by at
least the threshold; moneyline when its win chance beats the no-vig implied
chance by at least the threshold.

  python pipeline/model.py --seasons 2021-2025 --raw DIR
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

RELEASES = "https://github.com/nflverse/nflverse-data/releases/download"
GAMES_CSV = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"

PLAYS = 62  # scrimmage plays per team per game, roughly
PRIOR_GAMES = 4  # last season counts like this many games of this season
MARGIN_SD = 13.5  # spread of actual margins around the prediction, for win chances
NEUTRAL_WP = (0.1, 0.9)  # plays count while neither team is above 90% to win
DEF_WEIGHT = 0.5  # defense ratings count half
CENTER_GAMES = 48  # last season's final games that center totals early in a season
# QB ratings: each QB's own EPA per
# dropback, career to date, recent seasons weighted more, pulled toward
# replacement level for small samples. A game's offense moves by the gap between
# its starter and the QBs who produced the team's rating, scaled by how much of
# the offense is dropbacks.
QB_WEIGHT = 1.5  # walk-forward 2021-2026: margin error 10.245 -> 10.177 points; bets unchanged (+9.5u -> +9.8u)
DROPBACK_SHARE = 0.6
QB_K = 250  # dropbacks of replacement-level play added to a QB's own
QB_DECAY = 0.6  # each earlier season counts this much
REPLACEMENT = -0.08  # EPA/dropback below league average for an unproven QB
NEW_QB_PRIOR = 0.5  # how much of last season's offense carries over when the team has a new starting QB


@dataclass
class Params:
    hfa: float = 1.5
    margin_scale: float = 1.0
    total_scale: float = 1.0
    base_total: float = 44.0
    backup_qb: float = 0.08  # EPA/play an offense loses without its starting QB
    rest_per_day: float = 0.25
    wind_15: float = 2.0
    wind_20: float = 4.0
    cold: float = 1.5  # at or below 25F
    dome: float = 0.5
    spread_edge: float = 3.0
    total_edge: float = 3.5
    ml_edge: float = 0.05


# ── Data ─────────────────────────────────────────────────────────────────────

def load(raw: Path, name: str, url: str) -> pd.DataFrame | None:
    import urllib.request

    path = raw / name
    if not path.exists():
        try:
            urllib.request.urlretrieve(url, path)
        except Exception:
            return None
    return pd.read_csv(path, low_memory=False) if name.endswith(".csv") else pd.read_parquet(path)


def pbp_for(raw: Path, season: int) -> pd.DataFrame | None:
    return load(raw, f"play_by_play_{season}.parquet", f"{RELEASES}/pbp/play_by_play_{season}.parquet")


def team_games(pbp: pd.DataFrame) -> pd.DataFrame:
    """One row per team per game: offensive EPA/play, defensive EPA/play allowed, and its main passer."""
    p = pbp[pbp["play_type"].isin(["pass", "run"]) & (pbp["two_point_attempt"].fillna(0) == 0) & pbp["epa"].notna()]
    if "wp" in p.columns:
        p = p[p["wp"].between(*NEUTRAL_WP)]
    off = p.groupby(["game_id", "season", "week", "posteam"]).agg(off_epa=("epa", "mean"), plays=("epa", "size")).reset_index().rename(columns={"posteam": "team"})
    dfn = p.groupby(["game_id", "defteam"]).agg(def_epa=("epa", "mean")).reset_index().rename(columns={"defteam": "team"})
    qb = (
        p[p["passer_player_id"].notna()]
        .groupby(["game_id", "posteam", "passer_player_id"]).size().rename("n").reset_index()
        .sort_values("n", ascending=False).drop_duplicates(["game_id", "posteam"])
        .rename(columns={"posteam": "team", "passer_player_id": "qb"})[["game_id", "team", "qb"]]
    )
    return off.merge(dfn, on=["game_id", "team"]).merge(qb, on=["game_id", "team"], how="left")


def qb_games(pbp: pd.DataFrame) -> pd.DataFrame:
    """Each QB's dropbacks and EPA per game (competitive plays only)."""
    p = pbp[(pbp["qb_dropback"] == 1) & (pbp["two_point_attempt"].fillna(0) == 0) & pbp["epa"].notna()]
    if "wp" in p.columns:
        p = p[p["wp"].between(*NEUTRAL_WP)]
    p = p.assign(qb=p["passer_player_id"].fillna(p["rusher_player_id"]))
    return p.groupby(["season", "week", "game_id", "posteam", "qb"]).agg(db=("epa", "size"), epa=("epa", "sum")).reset_index()


class QBRatings:
    """Every QB's EPA per dropback before a given week, relative to league average."""

    def __init__(self, qbg: pd.DataFrame):
        self.qbg = qbg
        self.lg = float(qbg["epa"].sum() / qbg["db"].sum())
        self._cache: dict = {}

    def table(self, season: int, week: int) -> dict:
        key = (season, week)
        if key not in self._cache:
            h = self.qbg[(self.qbg["season"] < season) | ((self.qbg["season"] == season) & (self.qbg["week"] < week))]
            w = QB_DECAY ** (season - h["season"])
            agg = pd.DataFrame({"epa": h["epa"] * w, "db": h["db"] * w, "qb": h["qb"]}).groupby("qb")[["epa", "db"]].sum()
            rating = (agg["epa"] + (self.lg + REPLACEMENT) * QB_K) / (agg["db"] + QB_K) - self.lg
            self._cache[key] = rating.to_dict()
        return self._cache[key]

    def of(self, table: dict, qb) -> float:
        return table.get(qb, REPLACEMENT) if isinstance(qb, str) else REPLACEMENT


class Ratings:
    """Team ratings as of a given week: this season's games so far, blended with last season's."""

    def __init__(self, cur: pd.DataFrame, prev: pd.DataFrame | None, qbr: QBRatings | None = None):
        self.cur, self.prev, self.qbr = cur, prev, qbr
        self.season = int(cur["season"].max()) if len(cur) else (int(prev["season"].max()) + 1 if prev is not None else 0)
        self.lg = float(pd.concat([cur["off_epa"], prev["off_epa"]]).mean()) if prev is not None else float(cur["off_epa"].mean())
        self.prior = {}
        self.cur_qb = {t: g["qb"].mode().iloc[0] for t, g in cur.groupby("team") if g["qb"].notna().any()} if len(cur) else {}
        # Last season's usual QB per team, to spot a new starter.
        self.prev_qb = {t: g["qb"].mode().iloc[0] for t, g in prev.groupby("team") if g["qb"].notna().any()} if prev is not None else {}
        if prev is not None:
            for team, g in prev.groupby("team"):
                # Halfway back to average: rosters and coaches change.
                self.prior[team] = ((g["off_epa"].mean() - self.lg) * 0.5, (g["def_epa"].mean() - self.lg) * 0.5)
        # Each team's usual QB: most starts this season, else last season.
        both = pd.concat([cur, prev]) if prev is not None else cur
        self.main_qb = {}
        for team, g in both.groupby("team"):
            this = g[g["season"] == cur["season"].max()] if len(cur) else g
            src = this if len(this) else g
            if src["qb"].notna().any():
                self.main_qb[team] = src["qb"].mode().iloc[0]

    def at(self, week: int, starters: dict | None = None) -> dict:
        """Ratings before `week`. `starters` (team -> QB id this week) marks teams with a new starting QB."""
        before = self.cur[self.cur["week"] < week]
        out = {}
        teams = set(self.prior) | set(before["team"])
        for team in teams:
            g = before[before["team"] == team]
            n = len(g)
            po, pd_ = self.prior.get(team, (0.0, 0.0))
            # This week's listed starter, else who has started for them this season.
            qb = (starters or {}).get(team) or self.cur_qb.get(team)
            if isinstance(qb, str) and self.prev_qb.get(team) and qb != self.prev_qb[team]:
                po *= NEW_QB_PRIOR
            o = ((g["off_epa"].mean() - self.lg) * n + po * PRIOR_GAMES) / (n + PRIOR_GAMES) if n else po
            d = ((g["def_epa"].mean() - self.lg) * n + pd_ * PRIOR_GAMES) / (n + PRIOR_GAMES) if n else pd_
            starter = (starters or {}).get(team)
            if self.qbr is not None and QB_WEIGHT and isinstance(starter, str):
                # The QBs behind the rating, weighted like the rating: this season's games
                # in full, last season's (halved, like its offense) as PRIOR_GAMES games.
                tab = self.qbr.table(self.season, week)
                cur_r = sum(self.qbr.of(tab, q) for q in g["qb"])
                pg = self.prev[self.prev["team"] == team] if self.prev is not None else g.iloc[0:0]
                prev_r = (sum(self.qbr.of(tab, q) for q in pg["qb"]) / len(pg)) * 0.5 if len(pg) else 0.0
                behind = (cur_r + prev_r * PRIOR_GAMES) / (n + PRIOR_GAMES)
                o += QB_WEIGHT * DROPBACK_SHARE * (self.qbr.of(tab, starter) - behind)
            out[team] = (o, d * DEF_WEIGHT)
        return out


def predict(game: pd.Series, ratings: dict, lg: float, main_qb: dict, p: Params) -> tuple[float, float]:
    """(home margin, total) for one game."""
    ho, hd = ratings.get(game["home_team"], (0.0, 0.0))
    ao, ad = ratings.get(game["away_team"], (0.0, 0.0))
    # A backup QB starting costs the offense.
    for side in ("home", "away"):
        starter = game.get(f"{side}_qb_id")
        usual = main_qb.get(game[f"{side}_team"])
        if isinstance(starter, str) and usual and starter != usual:
            if side == "home":
                ho -= p.backup_qb
            else:
                ao -= p.backup_qb
    exp_h = lg + ho + ad
    exp_a = lg + ao + hd
    margin = (exp_h - exp_a) * PLAYS * p.margin_scale + p.hfa
    rest = (game.get("home_rest") or 7) - (game.get("away_rest") or 7)
    margin += max(-6, min(6, rest)) * p.rest_per_day
    total = p.base_total + (exp_h + exp_a - 2 * lg) * PLAYS * p.total_scale
    roof = str(game.get("roof") or "")
    wind = game.get("wind")
    temp = game.get("temp")
    if roof in ("dome", "closed"):
        total += p.dome
    else:
        if isinstance(wind, (int, float)) and not math.isnan(wind):
            total -= p.wind_20 if wind >= 20 else p.wind_15 if wind >= 15 else 0
        if isinstance(temp, (int, float)) and not math.isnan(temp) and temp <= 25:
            total -= p.cold
    return margin, total


# ── Betting ──────────────────────────────────────────────────────────────────

def implied(odds: float) -> float:
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)


def payout(odds: float) -> float:
    """Profit per unit staked."""
    return odds / 100 if odds > 0 else 100 / -odds


def win_prob(margin: float) -> float:
    return 0.5 * (1 + math.erf(margin / (MARGIN_SD * math.sqrt(2))))


def picks_for(game: pd.Series, margin: float, total: float, p: Params) -> list[dict]:
    """The bets the model would make on a game, with the edge behind each."""
    out = []
    line = game.get("spread_line")  # home favored by this many
    if isinstance(line, (int, float)) and not math.isnan(line):
        edge = margin - line
        if abs(edge) >= p.spread_edge:
            side = "home" if edge > 0 else "away"
            odds = game.get(f"{side}_spread_odds")
            out.append({"market": "spread", "side": side, "line": line, "odds": odds if isinstance(odds, (int, float)) and not math.isnan(odds) else -110, "edge": round(edge, 1)})
    tl = game.get("total_line")
    if isinstance(tl, (int, float)) and not math.isnan(tl):
        edge = total - tl
        if abs(edge) >= p.total_edge:
            side = "over" if edge > 0 else "under"
            odds = game.get(f"{side}_odds")
            out.append({"market": "total", "side": side, "line": tl, "odds": odds if isinstance(odds, (int, float)) and not math.isnan(odds) else -110, "edge": round(edge, 1)})
    hm, am = game.get("home_moneyline"), game.get("away_moneyline")
    if all(isinstance(x, (int, float)) and not math.isnan(x) for x in (hm, am)):
        ih, ia = implied(hm), implied(am)
        fair_h = ih / (ih + ia)
        ph = win_prob(margin)
        for side, pr, fair, odds in (("home", ph, fair_h, hm), ("away", 1 - ph, 1 - fair_h, am)):
            # Long shots and heavy favorites are where simple models are least reliable.
            if pr - fair >= p.ml_edge and -250 <= odds <= 250:
                out.append({"market": "moneyline", "side": side, "odds": odds, "edge": round((pr - fair) * 100, 1), "prob": round(pr, 3)})
    return out


def grade(game: pd.Series, pick: dict) -> float | None:
    """Profit per unit for a pick on a finished game (0 on a push)."""
    res = game.get("result")  # home score - away score
    tot = game.get("total")
    if not isinstance(res, (int, float)) or math.isnan(res):
        return None
    if pick["market"] == "spread":
        cover = res - pick["line"] if pick["side"] == "home" else pick["line"] - res
        return 0.0 if cover == 0 else payout(pick["odds"]) if cover > 0 else -1.0
    if pick["market"] == "total":
        diff = tot - pick["line"] if pick["side"] == "over" else pick["line"] - tot
        return 0.0 if diff == 0 else payout(pick["odds"]) if diff > 0 else -1.0
    won = res > 0 if pick["side"] == "home" else res < 0
    return 0.0 if res == 0 else payout(pick["odds"]) if won else -1.0


# ── Backtest ─────────────────────────────────────────────────────────────────

def season_games(games: pd.DataFrame, season: int) -> pd.DataFrame:
    return games[(games["season"] == season) & (games["game_type"] == "REG") & games["result"].notna()].sort_values(["week", "gameday"])


def build_qb_ratings(pbps: list) -> QBRatings:
    """QB ratings from the play-by-play seasons given (oldest to newest)."""
    return QBRatings(pd.concat([qb_games(p) for p in pbps if p is not None]))


def live_starters(wk: pd.DataFrame, main_qb: dict, injuries: dict) -> dict:
    """
    Who starts at QB this week: nflverse's listed starter, else the team's usual
    one; "backup" (replacement level) when that QB is out or doubtful.
    """
    out = {}
    listed = week_starters(wk)
    for _, g in wk.iterrows():
        for side in ("home", "away"):
            team = g[f"{side}_team"]
            qb = listed.get(team) or main_qb.get(team)
            usual = main_qb.get(team)
            hurt = {q for q in (qb, usual) if q and injuries.get(q, {}).get("status") in ("Out", "Doubtful")}
            out[team] = "backup" if qb in hurt or (qb == usual and usual in hurt) else qb
    return out


def week_starters(wk: pd.DataFrame) -> dict:
    """Team -> listed starting QB for a week's games (nflverse's games file)."""
    out = {}
    for _, g in wk.iterrows():
        for side in ("home", "away"):
            if isinstance(g.get(f"{side}_qb_id"), str):
                out[g[f"{side}_team"]] = g[f"{side}_qb_id"]
    return out


def total_offset(history: pd.DataFrame, week: int, anchor: pd.DataFrame | None = None) -> float:
    """
    How far the market's totals sit from the model's raw totals on average, over
    this season's games before `week` plus the end of last season (`anchor`).
    Adding it centers the model's totals on the market's.
    """
    rows = [history[history["market"].isna() & (history["week"] < week)]] if len(history) else []
    if anchor is not None and len(anchor):
        rows.insert(0, anchor[anchor["market"].isna()].tail(CENTER_GAMES))
    h = pd.concat(rows) if rows else pd.DataFrame()
    h = h[h["total_line"].notna()] if len(h) else h
    return float((h["total_line"] - h["total_raw"]).mean()) if len(h) else 0.0


def run(games: pd.DataFrame, cur: pd.DataFrame, prev: pd.DataFrame | None, season: int, p: Params, anchor: pd.DataFrame | None = None, qbr: QBRatings | None = None) -> pd.DataFrame:
    """
    Every prediction and pick for a season, week by week, using only games
    before each week. `anchor` is last season's run, which centers the totals
    in the first weeks.
    """
    r = Ratings(cur, prev, qbr)
    preds = []
    for week, wk in season_games(games, season).groupby("week"):
        ratings = r.at(int(week), week_starters(wk))
        for _, g in wk.iterrows():
            margin, total = predict(g, ratings, r.lg, r.main_qb, p)
            preds.append((int(week), g, margin, total))
    raw = pd.DataFrame([{"week": w, "market": None, "total_raw": t, "total_line": g["total_line"]} for w, g, _, t in preds])
    rows = []
    offsets: dict[int, float] = {}
    for week, g, margin, total_raw in preds:
        if week not in offsets:
            offsets[week] = total_offset(raw, week, anchor)
        total = total_raw + offsets[week]
        base = {"week": week, "game": f"{g['away_team']} @ {g['home_team']}", "margin": margin, "total_pred": total, "total_raw": total_raw, "result": g["result"], "total": g["total"], "spread_line": g["spread_line"], "total_line": g["total_line"]}
        rows.append({**base, "market": None})
        for pick in picks_for(g, margin, total, p):
            rows.append({**base, **pick, "profit": grade(g, pick)})
    return pd.DataFrame(rows)


def live_offset(games: pd.DataFrame, cur: pd.DataFrame, prev: pd.DataFrame, prev2: pd.DataFrame | None, season: int, p: Params, week: int, qbr: QBRatings | None = None) -> float:
    """The totals offset for an upcoming week: this season's finished games plus the end of last season."""
    anchor = run(games, prev, prev2, season - 1, p, qbr=qbr)
    return total_offset(run(games, cur, prev, season, p, anchor, qbr=qbr), week, anchor)


def fit(df: pd.DataFrame, p: Params) -> Params:
    """Calibrate the margin/total scales and base total by least squares on a season's predictions."""
    preds = df[df["market"].isna()]
    raw_margin = (preds["margin"] - p.hfa) / p.margin_scale
    k = float((raw_margin * (preds["result"] - p.hfa)).sum() / (raw_margin**2).sum())
    # The raw totals: centering on the market comes after.
    raw_total = (preds["total_raw"] - p.base_total) / p.total_scale
    X = np.vstack([np.ones(len(raw_total)), raw_total]).T
    (b, kt), *_ = np.linalg.lstsq(X, preds["total"].to_numpy(), rcond=None)
    return Params(**{**p.__dict__, "margin_scale": max(0.3, k), "total_scale": max(0.3, float(kt)), "base_total": float(b)})


def summarize(df: pd.DataFrame, label: str) -> dict:
    preds = df[df["market"].isna()]
    out = {
        "label": label,
        "games": len(preds),
        "model_margin_mae": round(float((preds["margin"] - preds["result"]).abs().mean()), 2),
        "line_margin_mae": round(float((preds["spread_line"] - preds["result"]).abs().mean()), 2),
        "model_total_mae": round(float((preds["total_pred"] - preds["total"]).abs().mean()), 2),
        "line_total_mae": round(float((preds["total_line"] - preds["total"]).abs().mean()), 2),
    }
    for market in ("spread", "total", "moneyline"):
        b = df[df["market"] == market]
        if not len(b):
            continue
        w = int((b["profit"] > 0).sum())
        l = int((b["profit"] < 0).sum())
        out[market] = {"bets": len(b), "record": f"{w}-{l}-{len(b) - w - l}", "win_pct": round(w / max(1, w + l) * 100, 1), "units": round(float(b["profit"].sum()), 2), "roi": round(float(b["profit"].mean()) * 100, 1)}
    allb = df[df["market"].notna()]
    out["all"] = {"bets": len(allb), "units": round(float(allb["profit"].sum()), 2), "roi": round(float(allb["profit"].mean()) * 100, 1) if len(allb) else None}
    return out


def live_params(p: Params) -> Params:
    """The live rules: spreads and totals 4+ points off the line, no moneylines."""
    return Params(**{**p.__dict__, "spread_edge": 4.0, "total_edge": 4.0, "ml_edge": 1.0})


def walk_forward(games: pd.DataFrame, tg: dict, season: int, qbr: QBRatings | None = None) -> pd.DataFrame:
    """One season as the live model would have played it: calibrated on the season before, live rules."""
    p = live_params(fit(run(games, tg[season - 1], tg[season - 2], season - 1, Params(), qbr=qbr), Params()))
    anchor = run(games, tg[season - 1], tg[season - 2], season - 1, p, qbr=qbr)
    return run(games, tg[season], tg[season - 1], season, p, anchor, qbr=qbr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2021-2025", help="test seasons, e.g. 2021-2025 (each needs the two before it)")
    ap.add_argument("--raw", default="raw")
    args = ap.parse_args()
    raw = Path(args.raw)
    raw.mkdir(parents=True, exist_ok=True)
    games = load(raw, "games.csv", GAMES_CSV)
    first, _, last = args.seasons.partition("-")
    seasons = list(range(int(first), int(last or first) + 1))
    pbp = {s: pbp_for(raw, s) for s in range(seasons[0] - 2, seasons[-1] + 1)}
    tg = {s: team_games(p) for s, p in pbp.items()}
    qbr = build_qb_ratings(list(pbp.values())) if QB_WEIGHT else None
    runs = []
    for season in seasons:
        df = walk_forward(games, tg, season, qbr)
        runs.append(df)
        print(season, summarize(df, str(season)))
    print("all ", summarize(pd.concat(runs), args.seasons))


if __name__ == "__main__":
    main()
