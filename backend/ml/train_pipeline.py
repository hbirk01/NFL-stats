"""
NFL Fantasy Value Score ML Pipeline
=====================================
Predicts which players will outperform their pre-season ADP (value score > 0).

TARGET: value_score for season Y
  = z-score-normalized(pos_adp_rank - performance_rank), scaled 0-100
  where performance_rank is ranked by weighted_ppg = PPG × (games/season_games)
  Positive = outperformed ADP.

MODEL CHOICE JUSTIFICATION
--------------------------
Dataset: ~150-300 players/year × 5 years ≈ 600-1000 rows.
With this small-data regime:

- Neural nets: SKIP. Require thousands of samples to avoid overfit; no interpretability.
- Linear Regression: Good baseline but no regularization; collinear features (ADP rank,
  prior stats) will inflate coefficients.
- Ridge/Lasso: Good regularized baseline; Ridge handles collinearity well, Lasso does
  feature selection. Chosen as baseline.
- Random Forest: Handles non-linearity (age curves, breakout vs bust), robust to outliers,
  no scaling needed, provides feature importance. Good mid-size dataset fit.
- XGBoost: Best overall for tabular data in this size range — boosting corrects errors
  iteratively, handles missing values natively, strong regularization options. Primary model.

Final ensemble: Ridge (baseline) + Random Forest + XGBoost.
Evaluation priority: Spearman rank correlation (we care about ordering, not exact scores).
"""

import os
import sys
import json
import re
import time
import warnings
import pickle
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error
import xgboost as xgb

warnings.filterwarnings("ignore")

# ── Paths ─────────────────────────────────────────────────────────────────────
BACKEND = Path(__file__).parent.parent
ML = Path(__file__).parent

# ── Constants ─────────────────────────────────────────────────────────────────
POSITIONS = ["QB", "WR", "RB", "TE"]
ADP_CUTOFF = 250
MIN_GAMES_TARGET = 8

TEAM_FIX = {"LAR": "LA", "JAC": "JAX", "LVR": "LV"}

norm = lambda n: (n or "").lower().replace("'", "").replace(".", "").replace("-", "").replace(" ", "")


def build_draft_combine_lookup(years: list[int]) -> dict:
    """
    Build a lookup dict: gsis_id → draft/combine features.
    Covers all players drafted in the given years.

    Draft capital features:
      - draft_round (1-7, 8 = undrafted)
      - draft_pick  (1-262, 300 = undrafted)

    Combine athleticism features (NaN if not measured):
      - forty, vertical, broad_jump, cone, shuttle, height_in, weight

    NOTE: college production stats (yards, dominator rating, etc.) require
    the College Football Data API (collegefootballdata.com) which is a
    separate integration — not included here.
    """
    import nfl_data_py as nfl

    draft_frames = []
    combine_frames = []

    for year in years:
        try:
            dp = nfl.import_draft_picks([year])
            dp = dp[dp["position"].isin(["QB", "WR", "RB", "TE"])].copy()
            dp = dp[dp["gsis_id"].notna()].copy()
            dp["gsis_id"] = dp["gsis_id"].astype(str)
            dp["draft_round_val"] = dp["round"].fillna(8).astype(int)
            dp["draft_pick_val"] = dp["pick"].fillna(300).astype(int)
            draft_frames.append(dp[["gsis_id", "pfr_player_id", "draft_round_val", "draft_pick_val", "pfr_player_name"]])
        except Exception:
            pass
        try:
            cb = nfl.import_combine_data([year])
            cb = cb[cb["pos"].isin(["QB", "WR", "RB", "TE"])].copy()
            cb = cb[cb["pfr_id"].notna()].copy()

            def _ht_to_inches(h):
                """Convert height string '6-2' to inches, or return NaN."""
                try:
                    if isinstance(h, str) and "-" in h:
                        ft, inch = h.split("-")
                        return int(ft) * 12 + int(inch)
                    return float(h) if h else np.nan
                except Exception:
                    return np.nan

            cb["height_in"] = cb["ht"].apply(_ht_to_inches)
            combine_frames.append(cb[["pfr_id", "forty", "vertical", "broad_jump", "cone", "shuttle", "height_in", "wt"]])
        except Exception:
            pass

    if not draft_frames:
        return {}

    all_draft = pd.concat(draft_frames, ignore_index=True).drop_duplicates("gsis_id")
    all_combine = pd.concat(combine_frames, ignore_index=True).drop_duplicates("pfr_id") if combine_frames else pd.DataFrame()

    # Join combine onto draft via pfr_player_id
    if not all_combine.empty:
        merged = all_draft.merge(all_combine, left_on="pfr_player_id", right_on="pfr_id", how="left")
    else:
        merged = all_draft.copy()
        for col in ["forty", "vertical", "broad_jump", "cone", "shuttle", "height_in", "wt"]:
            merged[col] = np.nan

    lookup = {}
    for _, row in merged.iterrows():
        gsis = row["gsis_id"]
        lookup[gsis] = {
            "draft_round": int(row.get("draft_round_val", 8)),
            "draft_pick": int(row.get("draft_pick_val", 300)),
            "forty": row.get("forty", np.nan),
            "vertical": row.get("vertical", np.nan),
            "broad_jump": row.get("broad_jump", np.nan),
            "cone": row.get("cone", np.nan),
            "shuttle": row.get("shuttle", np.nan),
            "height_in": row.get("height_in", np.nan),
            "weight": row.get("wt", np.nan),
        }
        # Also index by name for fallback
        name_key = norm(row.get("pfr_player_name", ""))
        if name_key:
            lookup[f"name:{name_key}"] = lookup[gsis]

    return lookup

SEASON_GAMES = {
    2020: 16,
    2021: 17,
    2022: 17,
    2023: 17,
    2024: 17,
    2025: 17,
    2026: 17,
}

# Wayback Machine ADP URLs — try two timestamps per year
ADP_URL_TEMPLATES = [
    "https://web.archive.org/web/20{yy}0901120000/https://www.fantasypros.com/nfl/adp/ppr-overall.php",
    "https://web.archive.org/web/20{yy}0901000000/https://www.fantasypros.com/nfl/adp/ppr-overall.php",
    "https://web.archive.org/web/20{yy}0902120000/https://www.fantasypros.com/nfl/adp/ppr-overall.php",
]


def parse_adp_html(html: str) -> list[dict]:
    """
    Parse FantasyPros PPR ADP HTML — handles multiple HTML versions across years.
    The page structure changed over time; we use row-by-row parsing that works
    for both the old (name in <a> text, fp-player-name optional) and
    new (fp-player-name attribute) formats.
    """
    row_pattern = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
    # Name: prefer fp-player-name attribute; fallback to player-name link text
    name_attr_re = re.compile(r'fp-player-name="([^"]+)"')
    name_text_re = re.compile(r'class="player-name[^"]*"[^>]*>([^<]+)</a>')
    team_re = re.compile(r"</a>[^<]*<small>([A-Z]{2,3})</small>")
    pos_rank_re = re.compile(r"<td>([A-Z]{2,2})(\d+)</td>")  # e.g. RB1, WR12

    players = []
    seen: set = set()

    for row_m in row_pattern.finditer(html):
        row = row_m.group(1)

        # Must have position+rank cell like RB1 or WR12
        pos_rank_m = pos_rank_re.search(row)
        if not pos_rank_m:
            continue
        pos = pos_rank_m.group(1)
        pos_rank = int(pos_rank_m.group(2))
        if pos not in POSITIONS:
            continue

        # Name
        name_m = name_attr_re.search(row)
        if name_m:
            name = name_m.group(1)
        else:
            name_m2 = name_text_re.search(row)
            if not name_m2:
                continue
            name = name_m2.group(1).strip()

        # Team — appears as <small>TEAM</small> right after the player link
        team_m = team_re.search(row)
        if not team_m:
            continue
        team = TEAM_FIX.get(team_m.group(1), team_m.group(1))

        # ADP = last float in a <td>
        tds = re.findall(r"<td[^>]*>([\d.]+)</td>", row)
        if not tds:
            continue
        adp = float(tds[-1])

        key = norm(name)
        if key in seen:
            continue
        seen.add(key)
        players.append({
            "name": name,
            "team": team,
            "position": pos,
            "overall_adp": adp,
            "pos_adp_rank": pos_rank,
        })

    return players


# ── Step 1: Fetch pre-season ADP data ─────────────────────────────────────────

def fetch_adp(year: int) -> list[dict]:
    """Fetch pre-season ADP from Wayback Machine for a given year."""
    out_path = BACKEND / f"data_{year}_preseason_adp.json"
    if out_path.exists():
        print(f"  [ADP {year}] Already exists, loading from cache.")
        with open(out_path) as f:
            return json.load(f)["players"]

    yy = str(year)[-2:]
    players = []
    for url_tmpl in ADP_URL_TEMPLATES:
        url = url_tmpl.format(yy=yy)
        print(f"  [ADP {year}] Fetching from {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            players = parse_adp_html(html)
            if players:
                break
        except Exception as e:
            print(f"  [ADP {year}] Attempt failed: {e}")
            time.sleep(1)

    if not players:
        print(f"  [ADP {year}] WARNING: No players parsed. Saving empty.")
    else:
        print(f"  [ADP {year}] Parsed {len(players)} players.")

    result = {"source": "FantasyPros PPR ADP (Wayback)", "date": f"{year}-09-01", "players": players}
    with open(out_path, "w") as f:
        json.dump(result, f)
    return players


# ── Step 2: Fetch season stats ─────────────────────────────────────────────────

def _compute_ppr(df: pd.DataFrame) -> pd.Series:
    cols = {
        "passing_yards": 0.04, "passing_tds": 4, "interceptions": -1,
        "rushing_yards": 0.1, "rushing_tds": 6,
        "receptions": 1, "receiving_yards": 0.1, "receiving_tds": 6,
    }
    total = pd.Series(0.0, index=df.index)
    for col, mult in cols.items():
        if col in df.columns:
            total += df[col].fillna(0) * mult
    return total


def _stats_from_pbp(year: int) -> pd.DataFrame:
    """Compute season stats from PBP data (used for 2025 which lacks pre-built seasonal)."""
    import nfl_data_py as nfl

    print(f"  [Stats {year}] Building from PBP (no seasonal data available)...")
    pbp = nfl.import_pbp_data([year], downcast=False)
    reg = pbp[pbp["season_type"] == "REG"]

    # Aggregate passing
    pass_agg = (
        reg[reg["passer_player_id"].notna()].groupby("passer_player_id").agg(
            passing_yards=("passing_yards", "sum"), passing_tds=("pass_touchdown", "sum"),
            interceptions=("interception", "sum"),
        ).reset_index().rename(columns={"passer_player_id": "player_id"})
    )
    rush_agg = (
        reg[reg["rusher_player_id"].notna() & reg["rush_attempt"].eq(1)].groupby("rusher_player_id").agg(
            rushing_yards=("rushing_yards", "sum"), rushing_tds=("rush_touchdown", "sum"),
        ).reset_index().rename(columns={"rusher_player_id": "player_id"})
    )
    rec_agg = (
        reg[reg["receiver_player_id"].notna()].groupby("receiver_player_id").agg(
            receptions=("complete_pass", "sum"), receiving_yards=("receiving_yards", "sum"),
            receiving_tds=("pass_touchdown", "sum"),
        ).reset_index().rename(columns={"receiver_player_id": "player_id"})
    )
    all_ids_set = (
        set(pass_agg["player_id"]) | set(rush_agg["player_id"]) | set(rec_agg["player_id"])
    )
    all_ids = pd.DataFrame({"player_id": list(all_ids_set)})

    # Games played
    games_raw = pd.concat([
        reg[["passer_player_id", "week"]].rename(columns={"passer_player_id": "player_id"}),
        reg[["rusher_player_id", "week"]].rename(columns={"rusher_player_id": "player_id"}),
        reg[["receiver_player_id", "week"]].rename(columns={"receiver_player_id": "player_id"}),
    ]).dropna(subset=["player_id"])
    games_map = games_raw.groupby("player_id")["week"].nunique().reset_index().rename(columns={"week": "games"})

    df = (all_ids
          .merge(pass_agg, on="player_id", how="left")
          .merge(rush_agg, on="player_id", how="left")
          .merge(rec_agg, on="player_id", how="left")
          .merge(games_map, on="player_id", how="left"))

    df["fantasy_points_ppr"] = _compute_ppr(df)
    df["season"] = year
    return df


def fetch_ngs_snap_data(year: int) -> None:
    """Fetch and save NGS (receiving/rushing/passing) and snap count data for a year."""
    import nfl_data_py as nfl

    # NGS Receiving
    recv_path = BACKEND / f"data_{year}_ngs_receiving.parquet"
    if not recv_path.exists():
        print(f"  [NGS Receiving {year}] Fetching...")
        try:
            df = nfl.import_ngs_data("receiving", [year])
            if not df.empty:
                df = df[df.get("season_type", pd.Series(["REG"] * len(df))).eq("REG")] if "season_type" in df.columns else df
                # Season-level: either week==None or a specific season-total row
                season_df = df[df["week"].isna()] if "week" in df.columns else df
                if season_df.empty:
                    # Some years use week==0 or the last week for season totals — try mean
                    season_df = df.groupby("player_gsis_id", as_index=False).mean(numeric_only=True)
                    if "player_display_name" in df.columns:
                        name_map = df.drop_duplicates("player_gsis_id")[["player_gsis_id", "player_display_name"]]
                        season_df = season_df.merge(name_map, on="player_gsis_id", how="left")
                if "player_display_name" in season_df.columns:
                    season_df["name_norm"] = season_df["player_display_name"].apply(norm)
                season_df.to_parquet(recv_path, index=False)
                print(f"  [NGS Receiving {year}] Saved {len(season_df)} rows.")
            else:
                print(f"  [NGS Receiving {year}] Empty.")
        except Exception as e:
            print(f"  [NGS Receiving {year}] Error: {e}")
    else:
        print(f"  [NGS Receiving {year}] Already exists.")

    # NGS Rushing
    rush_path = BACKEND / f"data_{year}_ngs_rushing.parquet"
    if not rush_path.exists():
        print(f"  [NGS Rushing {year}] Fetching...")
        try:
            df = nfl.import_ngs_data("rushing", [year])
            if not df.empty:
                df = df[df.get("season_type", pd.Series(["REG"] * len(df))).eq("REG")] if "season_type" in df.columns else df
                season_df = df[df["week"].isna()] if "week" in df.columns else df
                if season_df.empty:
                    season_df = df.groupby("player_gsis_id", as_index=False).mean(numeric_only=True)
                    if "player_display_name" in df.columns:
                        name_map = df.drop_duplicates("player_gsis_id")[["player_gsis_id", "player_display_name"]]
                        season_df = season_df.merge(name_map, on="player_gsis_id", how="left")
                if "player_display_name" in season_df.columns:
                    season_df["name_norm"] = season_df["player_display_name"].apply(norm)
                season_df.to_parquet(rush_path, index=False)
                print(f"  [NGS Rushing {year}] Saved {len(season_df)} rows.")
            else:
                print(f"  [NGS Rushing {year}] Empty.")
        except Exception as e:
            print(f"  [NGS Rushing {year}] Error: {e}")
    else:
        print(f"  [NGS Rushing {year}] Already exists.")

    # NGS Passing
    pass_path = BACKEND / f"data_{year}_ngs_passing.parquet"
    if not pass_path.exists():
        print(f"  [NGS Passing {year}] Fetching...")
        try:
            df = nfl.import_ngs_data("passing", [year])
            if not df.empty:
                df = df[df.get("season_type", pd.Series(["REG"] * len(df))).eq("REG")] if "season_type" in df.columns else df
                season_df = df[df["week"].isna()] if "week" in df.columns else df
                if season_df.empty:
                    season_df = df.groupby("player_gsis_id", as_index=False).mean(numeric_only=True)
                    if "player_display_name" in df.columns:
                        name_map = df.drop_duplicates("player_gsis_id")[["player_gsis_id", "player_display_name"]]
                        season_df = season_df.merge(name_map, on="player_gsis_id", how="left")
                if "player_display_name" in season_df.columns:
                    season_df["name_norm"] = season_df["player_display_name"].apply(norm)
                season_df.to_parquet(pass_path, index=False)
                print(f"  [NGS Passing {year}] Saved {len(season_df)} rows.")
            else:
                print(f"  [NGS Passing {year}] Empty.")
        except Exception as e:
            print(f"  [NGS Passing {year}] Error: {e}")
    else:
        print(f"  [NGS Passing {year}] Already exists.")

    # Snap counts
    snaps_path = BACKEND / f"data_{year}_snaps.parquet"
    if not snaps_path.exists():
        print(f"  [Snaps {year}] Fetching...")
        try:
            df = nfl.import_snap_counts([year])
            if not df.empty:
                if "game_type" in df.columns:
                    df = df[df["game_type"] == "REG"]
                if "offense_pct" in df.columns:
                    if "player" in df.columns:
                        df["name_norm"] = df["player"].apply(norm)
                        snap_season = df.groupby("name_norm", as_index=False)["offense_pct"].mean()
                        snap_season.to_parquet(snaps_path, index=False)
                        print(f"  [Snaps {year}] Saved {len(snap_season)} rows.")
                    else:
                        print(f"  [Snaps {year}] No 'player' column.")
                else:
                    print(f"  [Snaps {year}] No 'offense_pct' column.")
            else:
                print(f"  [Snaps {year}] Empty.")
        except Exception as e:
            print(f"  [Snaps {year}] Error: {e}")
    else:
        print(f"  [Snaps {year}] Already exists.")


def fetch_season_stats(year: int) -> pd.DataFrame:
    """Fetch actual season stats for a given year using nfl_data_py."""
    out_path = BACKEND / f"data_{year}_season_stats.parquet"
    if out_path.exists():
        print(f"  [Stats {year}] Already exists, loading from cache.")
        return pd.read_parquet(out_path)

    print(f"  [Stats {year}] Fetching via nfl_data_py...")
    import nfl_data_py as nfl

    # Try pre-aggregated seasonal data first (available through 2024 usually)
    df = pd.DataFrame()
    try:
        df = nfl.import_seasonal_data([year])
        if df.empty:
            raise ValueError("Empty dataframe")
        print(f"  [Stats {year}] Got seasonal data ({len(df)} rows)")
    except Exception as e:
        print(f"  [Stats {year}] Seasonal data unavailable ({e}), falling back to PBP...")

    if df.empty:
        df = _stats_from_pbp(year)

    if df.empty:
        print(f"  [Stats {year}] No data available.")
        return pd.DataFrame()

    season_games = SEASON_GAMES.get(year, 17)

    if "fantasy_points_ppr" not in df.columns:
        df["fantasy_points_ppr"] = _compute_ppr(df)

    if "games" not in df.columns or df["games"].isna().all():
        df["games"] = 1

    df["ppg"] = df["fantasy_points_ppr"] / df["games"].where(df["games"] > 0)
    df["weighted_ppg"] = df["ppg"] * (df["games"] / season_games)
    if "season" not in df.columns:
        df["season"] = year

    # Get roster for player names, positions, ages
    try:
        roster = nfl.import_seasonal_rosters([year])
        roster = roster.sort_values("week", ascending=False).drop_duplicates("player_id")
        keep_cols = [c for c in ["player_id", "player_name", "position", "team", "age", "years_exp"] if c in roster.columns]
        roster = roster[keep_cols]
        df = df.merge(roster, on="player_id", how="left")
    except Exception as e:
        print(f"  [Stats {year}] Roster fetch warning: {e}")

    df.to_parquet(out_path, index=False)
    print(f"  [Stats {year}] Saved {len(df)} rows.")
    return df


# ── Step 3: Build feature matrix ──────────────────────────────────────────────

def compute_value_score(adp_players: list[dict], stats_df: pd.DataFrame, year: int) -> pd.DataFrame:
    """
    Merge ADP and actual stats, compute value_score.
    value_score = z-score-normalized(pos_adp_rank - performance_rank), scaled 0-100.
    """
    if not adp_players or stats_df.empty:
        return pd.DataFrame()

    adp_df = pd.DataFrame(adp_players)
    adp_df = adp_df[adp_df["position"].isin(POSITIONS)]
    adp_df = adp_df[adp_df["overall_adp"] <= ADP_CUTOFF]
    adp_df["name_norm"] = adp_df["name"].apply(norm)

    # Normalize stats player names
    stats_df = stats_df.copy()
    if "player_name" in stats_df.columns:
        stats_df["name_norm"] = stats_df["player_name"].apply(norm)
    elif "player_display_name" in stats_df.columns:
        stats_df["name_norm"] = stats_df["player_display_name"].apply(norm)
    else:
        return pd.DataFrame()

    # Filter stats to relevant positions and minimum games
    if "position" in stats_df.columns:
        stats_df = stats_df[stats_df["position"].isin(POSITIONS)]
    stats_df = stats_df[stats_df["games"] >= MIN_GAMES_TARGET].copy()

    # Merge on name + position
    merged = adp_df.merge(
        stats_df[["name_norm", "position", "fantasy_points_ppr", "games", "ppg", "weighted_ppg", "player_id", "age", "years_exp"]].drop_duplicates("name_norm"),
        on="name_norm",
        how="inner",
        suffixes=("_adp", "_stats")
    )

    # Resolve position column
    if "position_adp" in merged.columns:
        merged["position"] = merged["position_adp"]
        merged = merged.drop(columns=["position_adp", "position_stats"], errors="ignore")

    if merged.empty:
        return pd.DataFrame()

    # Compute performance rank per position (lower rank = better)
    merged["performance_rank"] = merged.groupby("position")["weighted_ppg"].rank(ascending=False, method="min")

    # Value score: pos_adp_rank - performance_rank (positive = outperformed)
    merged["raw_value"] = merged["pos_adp_rank"] - merged["performance_rank"]

    # Z-score normalize per position, scale 0-100
    def z_normalize(series):
        mu, sigma = series.mean(), series.std()
        if sigma == 0:
            return pd.Series(50.0, index=series.index)
        z = (series - mu) / sigma
        # Clip at ±3 sigma, then scale to 0-100
        z = z.clip(-3, 3)
        return (z + 3) / 6 * 100

    merged["value_score"] = merged.groupby("position")["raw_value"].transform(z_normalize)
    merged["season"] = year

    return merged


def _load_ngs_snaps(year: int):
    """Load NGS and snap data for a given year into dicts keyed by player_gsis_id or name_norm."""
    ngs_recv, ngs_rush, ngs_pass, snaps = {}, {}, {}, {}

    recv_path = BACKEND / f"data_{year}_ngs_receiving.parquet"
    if recv_path.exists():
        df = pd.read_parquet(recv_path)
        id_col = "player_gsis_id" if "player_gsis_id" in df.columns else None
        for _, r in df.iterrows():
            key = r[id_col] if id_col and pd.notna(r.get(id_col)) else r.get("name_norm", "")
            if key:
                ngs_recv[key] = r

    rush_path = BACKEND / f"data_{year}_ngs_rushing.parquet"
    if rush_path.exists():
        df = pd.read_parquet(rush_path)
        id_col = "player_gsis_id" if "player_gsis_id" in df.columns else None
        for _, r in df.iterrows():
            key = r[id_col] if id_col and pd.notna(r.get(id_col)) else r.get("name_norm", "")
            if key:
                ngs_rush[key] = r

    pass_path = BACKEND / f"data_{year}_ngs_passing.parquet"
    if pass_path.exists():
        df = pd.read_parquet(pass_path)
        id_col = "player_gsis_id" if "player_gsis_id" in df.columns else None
        for _, r in df.iterrows():
            key = r[id_col] if id_col and pd.notna(r.get(id_col)) else r.get("name_norm", "")
            if key:
                ngs_pass[key] = r

    snaps_path = BACKEND / f"data_{year}_snaps.parquet"
    if snaps_path.exists():
        df = pd.read_parquet(snaps_path)
        for _, r in df.iterrows():
            key = r.get("name_norm", "")
            if key:
                snaps[key] = r

    return ngs_recv, ngs_rush, ngs_pass, snaps


def build_feature_matrix(years_data: dict) -> pd.DataFrame:
    """
    Build the full feature matrix. For each player-season Y:
    - Target: value_score in season Y
    - Features: prior year (Y-1) and two-year prior (Y-2) stats
    """
    feature_rows = []

    # Pre-load NGS/snap data for all years we'll need as prior year
    ngs_cache = {}
    for y in sorted(years_data.keys()):
        prev_y = y - 1
        if prev_y not in ngs_cache:
            ngs_cache[prev_y] = _load_ngs_snaps(prev_y)

    # Build draft capital + combine lookup (all draft years we might need)
    all_years = sorted(years_data.keys())
    draft_years = list(range(min(all_years) - 5, max(all_years) + 2))
    print(f"  [Draft/Combine] Building lookup for draft years {draft_years[0]}-{draft_years[-1]}...")
    draft_combine = build_draft_combine_lookup(draft_years)
    print(f"  [Draft/Combine] {len([k for k in draft_combine if not str(k).startswith('name:')])} players indexed")

    for year in sorted(years_data.keys()):
        if year not in years_data:
            continue
        current = years_data[year]
        if current.empty:
            continue

        prev_year = year - 1
        prev2_year = year - 2

        prev_stats = years_data.get(prev_year, pd.DataFrame())
        prev2_stats = years_data.get(prev2_year, pd.DataFrame())

        # Also load raw prev stats parquet for extra columns (targets, carries, etc.)
        raw_prev_path = BACKEND / f"data_{prev_year}_season_stats.parquet"
        if raw_prev_path.exists():
            raw_prev = pd.read_parquet(raw_prev_path)
            if "player_name" in raw_prev.columns:
                raw_prev["name_norm"] = raw_prev["player_name"].apply(norm)
            elif "player_display_name" in raw_prev.columns:
                raw_prev["name_norm"] = raw_prev["player_display_name"].apply(norm)
        else:
            raw_prev = pd.DataFrame()

        # NGS/snap dicts for prev year
        ngs_recv, ngs_rush, ngs_pass, snaps = ngs_cache.get(prev_year, ({}, {}, {}, {}))

        for _, row in current.iterrows():
            name_n = row.get("name_norm", norm(row.get("name", "")))
            pos = row.get("position", "")
            player_id = row.get("player_id", "")

            # Look up prior year stats
            if not prev_stats.empty and "name_norm" in prev_stats.columns:
                prev_match = prev_stats[prev_stats["name_norm"] == name_n]
            else:
                prev_match = pd.DataFrame()

            if not prev2_stats.empty and "name_norm" in prev2_stats.columns:
                prev2_match = prev2_stats[prev2_stats["name_norm"] == name_n]
            else:
                prev2_match = pd.DataFrame()

            # Raw prev stats row for extra columns
            if not raw_prev.empty and "name_norm" in raw_prev.columns:
                raw_prev_match = raw_prev[raw_prev["name_norm"] == name_n]
                rp = raw_prev_match.iloc[0] if not raw_prev_match.empty else None
            else:
                rp = None

            # Check if player has appeared in ANY prior season (not just Y-1)
            has_any_prior = any(
                not years_data.get(y, pd.DataFrame()).empty and
                "name_norm" in years_data.get(y, pd.DataFrame()).columns and
                name_n in years_data[y]["name_norm"].values
                for y in range(year - 5, year)
                if y in years_data
            )

            # Prior year features
            if not prev_match.empty:
                p = prev_match.iloc[0]
                weighted_ppg_prev = p.get("weighted_ppg", 0) or 0
                ppg_prev = p.get("ppg", 0) or 0
                games_prev = p.get("games", 0) or 0
                fp_prev = p.get("fantasy_points_ppr", 0) or 0
                games_missed_prev = SEASON_GAMES.get(prev_year, 17) - games_prev
                is_rookie = 0
                prev_team = p.get("team", "")
            else:
                weighted_ppg_prev = 0
                ppg_prev = 0
                games_prev = 0
                fp_prev = 0
                games_missed_prev = SEASON_GAMES.get(prev_year, 17)
                is_rookie = 0 if has_any_prior else 1
                prev_team = ""

            # Two-year trend
            if not prev2_match.empty and not prev_match.empty:
                weighted_ppg_prev2 = prev2_match.iloc[0].get("weighted_ppg", 0) or 0
                trend = weighted_ppg_prev - weighted_ppg_prev2
            else:
                weighted_ppg_prev2 = 0
                trend = 0

            # Age
            age = row.get("age", np.nan)
            if pd.isna(age):
                age = 26

            # Position one-hot
            pos_QB = int(pos == "QB")
            pos_WR = int(pos == "WR")
            pos_RB = int(pos == "RB")
            pos_TE = int(pos == "TE")

            # ── New features from raw season stats ──
            def _get(src, col, default=0):
                if src is None:
                    return default
                v = src.get(col, default)
                return default if pd.isna(v) else v

            targets_prev = _get(rp, "targets", 0) if pos in ("WR", "TE", "RB") else 0
            carries_prev = _get(rp, "carries", 0) if pos in ("RB", "QB") else 0
            tgt_sh_prev = _get(rp, "tgt_sh", 0) if pos in ("WR", "TE", "RB") else 0
            ay_sh_prev = _get(rp, "ay_sh", 0) if pos in ("WR", "TE") else 0
            wopr_prev = _get(rp, "wopr_y", 0) if pos in ("WR", "TE", "RB") else 0
            rec_epa_prev = _get(rp, "receiving_epa", 0) if pos != "QB" else 0
            rush_epa_prev = _get(rp, "rushing_epa", 0) if pos not in ("WR", "TE") else 0
            pass_epa_prev = _get(rp, "passing_epa", 0) if pos == "QB" else 0
            dom_prev = _get(rp, "dom", 0)
            years_exp_prev = _get(rp, "years_exp", 0)

            # Team change: 1 if prev team != current team
            current_team = row.get("team", "")
            team_change = int(bool(prev_team) and bool(current_team) and prev_team != current_team)

            # Derived opportunity rates
            targets_per_game_prev = (targets_prev / games_prev) if games_prev > 0 and pos in ("WR", "TE", "RB") else 0
            carries_per_game_prev = (carries_prev / games_prev) if games_prev > 0 and pos in ("RB", "QB") else 0
            age_sq = float(age) ** 2

            # ── NGS features — look up by player_id first, fallback to name_norm ──
            def _ngs_lookup(ngs_dict, pid, nn):
                row_data = ngs_dict.get(pid) if pid else None
                if row_data is None:
                    row_data = ngs_dict.get(nn)
                return row_data

            # NGS receiving (WR/TE only)
            ngs_r = _ngs_lookup(ngs_recv, player_id, name_n) if pos in ("WR", "TE") else None
            separation_prev = _get(ngs_r, "avg_separation", 0)
            cushion_prev = _get(ngs_r, "avg_cushion", 0)
            yac_above_exp_prev = _get(ngs_r, "avg_yac_above_expectation", 0)
            catch_pct_prev = _get(ngs_r, "catch_percentage", 0)

            # NGS rushing (RB only)
            ngs_ru = _ngs_lookup(ngs_rush, player_id, name_n) if pos == "RB" else None
            ryoe_per_att_prev = _get(ngs_ru, "rush_yards_over_expected_per_att", 0)
            rush_pct_over_exp_prev = _get(ngs_ru, "rush_pct_over_expected", 0)
            stacked_box_pct_prev = _get(ngs_ru, "percent_attempts_gte_eight_defenders", 0)

            # NGS passing (QB only)
            ngs_p = _ngs_lookup(ngs_pass, player_id, name_n) if pos == "QB" else None
            cpoe_prev = _get(ngs_p, "completion_percentage_above_expectation", 0)
            aggressiveness_prev = _get(ngs_p, "aggressiveness", 0)
            qb_air_yards_prev = _get(ngs_p, "avg_intended_air_yards", 0)

            # Snap pct
            snap_row = snaps.get(name_n)
            snap_pct_prev = _get(snap_row, "offense_pct", 0)

            # Draft capital + combine athleticism
            # Look up by gsis_id first, then fall back to name
            dc = draft_combine.get(player_id) or draft_combine.get(f"name:{name_n}", {})
            draft_round = dc.get("draft_round", 8)       # 8 = undrafted
            draft_pick  = dc.get("draft_pick", 300)      # 300 = undrafted
            is_undrafted = int(draft_round == 8)
            # Normalise pick to 0-1 range (pick 1 = 1.0, pick 300 = 0.0)
            draft_pick_norm = max(0.0, 1.0 - (draft_pick - 1) / 299)
            forty       = dc.get("forty", np.nan)
            vertical    = dc.get("vertical", np.nan)
            broad_jump  = dc.get("broad_jump", np.nan)
            cone        = dc.get("cone", np.nan)
            weight      = dc.get("weight", np.nan)
            height_in   = dc.get("height_in", np.nan)

            feature_rows.append({
                "season": year,
                "name": row.get("name", ""),
                "name_norm": name_n,
                "player_id": player_id,
                "position": pos,
                # Original features
                "weighted_ppg_prev": weighted_ppg_prev,
                "ppg_prev": ppg_prev,
                "games_prev": games_prev,
                "fp_prev": fp_prev,
                "weighted_ppg_prev2": weighted_ppg_prev2,
                "trend_weighted_ppg": trend,
                "age": age,
                "pos_adp_rank": row.get("pos_adp_rank", 999),
                "overall_adp": row.get("overall_adp", 999),
                "games_missed_prev": games_missed_prev,
                "is_rookie": is_rookie,
                "pos_QB": pos_QB,
                "pos_WR": pos_WR,
                "pos_RB": pos_RB,
                "pos_TE": pos_TE,
                # New features from season stats
                "targets_prev": targets_prev,
                "carries_prev": carries_prev,
                "tgt_sh_prev": tgt_sh_prev,
                "ay_sh_prev": ay_sh_prev,
                "wopr_prev": wopr_prev,
                "rec_epa_prev": rec_epa_prev,
                "rush_epa_prev": rush_epa_prev,
                "pass_epa_prev": pass_epa_prev,
                "dom_prev": dom_prev,
                "years_exp_prev": years_exp_prev,
                "team_change": team_change,
                # NGS receiving
                "separation_prev": separation_prev,
                "cushion_prev": cushion_prev,
                "yac_above_exp_prev": yac_above_exp_prev,
                "catch_pct_prev": catch_pct_prev,
                # NGS rushing
                "ryoe_per_att_prev": ryoe_per_att_prev,
                "rush_pct_over_exp_prev": rush_pct_over_exp_prev,
                "stacked_box_pct_prev": stacked_box_pct_prev,
                # NGS passing
                "cpoe_prev": cpoe_prev,
                "aggressiveness_prev": aggressiveness_prev,
                "qb_air_yards_prev": qb_air_yards_prev,
                # Snap
                "snap_pct_prev": snap_pct_prev,
                # Derived
                "age_sq": age_sq,
                "targets_per_game_prev": targets_per_game_prev,
                "carries_per_game_prev": carries_per_game_prev,
                # Draft capital + combine athleticism
                "draft_round": draft_round,
                "draft_pick_norm": draft_pick_norm,
                "is_undrafted": is_undrafted,
                "forty": forty,
                "vertical": vertical,
                "broad_jump": broad_jump,
                "cone": cone,
                "weight": weight,
                "height_in": height_in,
                # Target
                "value_score": row.get("value_score", np.nan),
                # For prediction output
                "team": row.get("team", ""),
                "weighted_ppg_actual": row.get("weighted_ppg", 0),
                "games_actual": row.get("games", 0),
            })

    df = pd.DataFrame(feature_rows)
    return df


FEATURE_COLS = [
    # Original 14 features
    "weighted_ppg_prev", "ppg_prev", "games_prev", "fp_prev",
    "weighted_ppg_prev2", "trend_weighted_ppg",
    "age", "pos_adp_rank", "overall_adp",
    "games_missed_prev", "is_rookie",
    "pos_QB", "pos_WR", "pos_RB", "pos_TE",
    # New: season stats
    "targets_prev", "carries_prev", "tgt_sh_prev", "ay_sh_prev", "wopr_prev",
    "rec_epa_prev", "rush_epa_prev", "pass_epa_prev", "dom_prev",
    "years_exp_prev", "team_change",
    # New: NGS receiving
    "separation_prev", "cushion_prev", "yac_above_exp_prev", "catch_pct_prev",
    # New: NGS rushing
    "ryoe_per_att_prev", "rush_pct_over_exp_prev", "stacked_box_pct_prev",
    # New: NGS passing
    "cpoe_prev", "aggressiveness_prev", "qb_air_yards_prev",
    # New: snaps + derived
    "snap_pct_prev", "age_sq", "targets_per_game_prev", "carries_per_game_prev",
    # Draft capital + combine athleticism
    "draft_round", "draft_pick_norm", "is_undrafted",
    "forty", "vertical", "broad_jump", "cone", "weight", "height_in",
]


# ── Step 4: Train/val/test splits ─────────────────────────────────────────────

def walk_forward_folds(fm: pd.DataFrame):
    """
    Walk-forward (expanding window) cross-validation — the correct approach for
    temporal sports data. Each fold trains on all seasons up to year Y-1 and
    tests on year Y. This gives 4 independent test folds instead of 1, so metrics
    are far more reliable and representative of real predictive performance.

    Random within-season splits are NOT used here because that would leak future
    information: knowing some players' 2023 outcomes during training would let the
    model implicitly learn 2023-era patterns that wouldn't be available pre-season.

    Folds:
      Fold 1: Train 2020        → Test 2021
      Fold 2: Train 2020-2021   → Test 2022
      Fold 3: Train 2020-2022   → Test 2023
      Fold 4: Train 2020-2023   → Test 2024
    """
    all_seasons = sorted(fm["season"].dropna().unique())
    # Only seasons where we have value_score (not the 2025/2026 prediction rows)
    labeled = fm.dropna(subset=["value_score"])
    labeled_seasons = sorted(labeled["season"].unique())

    folds = []
    for i in range(1, len(labeled_seasons)):
        train_seasons = labeled_seasons[:i]
        test_season   = labeled_seasons[i]
        tr = labeled[labeled["season"].isin(train_seasons)]
        te = labeled[labeled["season"] == test_season]
        if len(tr) >= 10 and len(te) >= 10:
            folds.append((train_seasons, test_season, tr, te))
    return folds


def get_splits(fm: pd.DataFrame):
    """Legacy single split — kept for backward compat but walk_forward_folds is preferred."""
    labeled = fm.dropna(subset=["value_score"])
    seasons = sorted(labeled["season"].unique())
    # Use last season as test, second-to-last as val, rest as train
    test_season = seasons[-1]
    val_season  = seasons[-2]
    train = labeled[~labeled["season"].isin([test_season, val_season])]
    val   = labeled[labeled["season"] == val_season]
    test  = labeled[labeled["season"] == test_season]
    return train, val, test


def evaluate(y_true, y_pred, name=""):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    rho, pval = spearmanr(y_true, y_pred)
    print(f"    {name}: MAE={mae:.2f} RMSE={rmse:.2f} Spearman={rho:.3f} (p={pval:.3f})")
    return {"mae": mae, "rmse": rmse, "spearman": rho, "spearman_pval": pval}


# ── Step 5: Train models ───────────────────────────────────────────────────────

def train_models(fm: pd.DataFrame):
    """
    Walk-forward cross-validation for honest evaluation, then retrain final
    models on ALL labeled data so predictions use the full history.
    """
    folds = walk_forward_folds(fm)
    labeled = fm.dropna(subset=["value_score"])

    print(f"\n  Walk-forward CV: {len(folds)} folds")
    for tr_seasons, te_season, tr, te in folds:
        print(f"    Train {tr_seasons} → Test {te_season}  ({len(tr)} / {len(te)} rows)")

    metrics = {}
    models = {}

    # ── Helper: evaluate across all folds ──
    def cv_evaluate(model_fn, name):
        """Run model_fn(X_tr, y_tr, X_va, y_va) → fitted model. Return avg Spearman + per-fold."""
        fold_rhos = []
        for tr_seasons, te_season, tr_fold, te_fold in folds:
            # For hyperparameter selection: use the fold just before test as val
            val_season = tr_seasons[-1] if len(tr_seasons) > 1 else tr_seasons[0]
            tr_inner = tr_fold[tr_fold["season"] != val_season]
            va_inner = tr_fold[tr_fold["season"] == val_season]
            if len(tr_inner) < 5 or len(va_inner) < 5:
                tr_inner, va_inner = tr_fold, te_fold  # fallback
            X_tr = tr_inner[FEATURE_COLS].fillna(0).values
            y_tr = tr_inner["value_score"].values
            X_va = va_inner[FEATURE_COLS].fillna(0).values
            y_va = va_inner["value_score"].values
            X_te = te_fold[FEATURE_COLS].fillna(0).values
            y_te = te_fold["value_score"].values
            m = model_fn(X_tr, y_tr, X_va, y_va)
            if isinstance(m, tuple):  # ridge returns (model, scaler)
                pred = m[0].predict(m[1].transform(X_te))
            else:
                pred = m.predict(X_te)
            rho, _ = spearmanr(y_te, pred)
            fold_rhos.append((te_season, rho))
        return fold_rhos

    # ── Ridge ──
    print("\n  Ridge — walk-forward CV...")
    best_alpha = 1.0

    def ridge_fn(X_tr, y_tr, X_va, y_va, alpha=None):
        a = alpha or best_alpha
        sc = StandardScaler(); X_tr_s = sc.fit_transform(X_tr); X_va_s = sc.transform(X_va)
        r = Ridge(alpha=a); r.fit(X_tr_s, y_tr)
        return (r, sc)

    # Find best alpha using fold-average Spearman
    best_alpha_val, best_alpha_rho = 1.0, -999
    for alpha in [0.1, 1.0, 5.0, 10.0, 50.0]:
        rhos = cv_evaluate(lambda X_tr, y_tr, X_va, y_va: ridge_fn(X_tr, y_tr, X_va, y_va, alpha), f"ridge_a{alpha}")
        avg_rho = np.mean([r for _, r in rhos])
        if avg_rho > best_alpha_rho:
            best_alpha_rho = avg_rho; best_alpha_val = alpha
    best_alpha = best_alpha_val

    fold_rhos = cv_evaluate(ridge_fn, "Ridge")
    for season, rho in fold_rhos:
        print(f"    Fold test {season}: Spearman={rho:.3f}")
    avg_rho = np.mean([r for _, r in fold_rhos])
    print(f"    Ridge CV avg Spearman={avg_rho:.3f}  (best alpha={best_alpha})")
    metrics["ridge"] = {"cv_spearman_avg": round(avg_rho, 4), "cv_folds": [{"season": s, "spearman": round(r, 4)} for s, r in fold_rhos], "best_alpha": best_alpha}

    # Final model on all labeled data
    X_all = labeled[FEATURE_COLS].fillna(0).values; y_all = labeled["value_score"].values
    final_scaler = StandardScaler(); X_all_s = final_scaler.fit_transform(X_all)
    final_ridge = Ridge(alpha=best_alpha); final_ridge.fit(X_all_s, y_all)
    models["ridge"] = (final_ridge, final_scaler)
    with open(ML / "model_ridge.pkl", "wb") as f:
        pickle.dump({"model": final_ridge, "scaler": final_scaler, "features": FEATURE_COLS}, f)

    # ── Random Forest ──
    print("\n  Random Forest — walk-forward CV...")
    best_rf_params = {"n_estimators": 100, "max_depth": 5, "min_samples_leaf": 3}
    best_rf_rho = -999
    for n_est in [100, 200]:
        for max_depth in [3, 5, None]:
            for min_samp in [3, 5]:
                def rf_fn(X_tr, y_tr, X_va, y_va, ne=n_est, md=max_depth, ms=min_samp):
                    rf = RandomForestRegressor(n_estimators=ne, max_depth=md, min_samples_leaf=ms, random_state=42, n_jobs=-1)
                    rf.fit(X_tr, y_tr); return rf
                rhos = cv_evaluate(rf_fn, "RF")
                avg = np.mean([r for _, r in rhos])
                if avg > best_rf_rho:
                    best_rf_rho = avg; best_rf_params = {"n_estimators": n_est, "max_depth": max_depth, "min_samples_leaf": min_samp}

    def best_rf_fn(X_tr, y_tr, X_va, y_va):
        rf = RandomForestRegressor(**best_rf_params, random_state=42, n_jobs=-1)
        rf.fit(X_tr, y_tr); return rf
    fold_rhos = cv_evaluate(best_rf_fn, "RF")
    for season, rho in fold_rhos:
        print(f"    Fold test {season}: Spearman={rho:.3f}")
    avg_rho = np.mean([r for _, r in fold_rhos])
    print(f"    RF CV avg Spearman={avg_rho:.3f}  params={best_rf_params}")
    metrics["random_forest"] = {"cv_spearman_avg": round(avg_rho, 4), "cv_folds": [{"season": s, "spearman": round(r, 4)} for s, r in fold_rhos], "best_params": best_rf_params}

    final_rf = RandomForestRegressor(**best_rf_params, random_state=42, n_jobs=-1)
    final_rf.fit(X_all, y_all)
    models["random_forest"] = final_rf
    with open(ML / "model_random_forest.pkl", "wb") as f:
        pickle.dump({"model": final_rf, "features": FEATURE_COLS}, f)

    # ── XGBoost ──
    print("\n  XGBoost — walk-forward CV...")
    best_xgb_params = {"lr": 0.05, "max_depth": 3, "n_est": 100, "subsample": 0.7}
    best_xgb_rho = -999
    for lr in [0.05, 0.1]:
        for max_depth in [3, 4]:
            for n_est in [100, 200]:
                for subsample in [0.7, 1.0]:
                    def xgb_fn(X_tr, y_tr, X_va, y_va, lr=lr, md=max_depth, ne=n_est, ss=subsample):
                        m = xgb.XGBRegressor(n_estimators=ne, max_depth=md, learning_rate=lr, subsample=ss, colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=1.0, random_state=42, verbosity=0)
                        m.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False); return m
                    rhos = cv_evaluate(xgb_fn, "XGB")
                    avg = np.mean([r for _, r in rhos])
                    if avg > best_xgb_rho:
                        best_xgb_rho = avg; best_xgb_params = {"lr": lr, "max_depth": max_depth, "n_est": n_est, "subsample": subsample}

    def best_xgb_fn(X_tr, y_tr, X_va, y_va):
        m = xgb.XGBRegressor(n_estimators=best_xgb_params["n_est"], max_depth=best_xgb_params["max_depth"], learning_rate=best_xgb_params["lr"], subsample=best_xgb_params["subsample"], colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=1.0, random_state=42, verbosity=0)
        m.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False); return m
    fold_rhos = cv_evaluate(best_xgb_fn, "XGB")
    for season, rho in fold_rhos:
        print(f"    Fold test {season}: Spearman={rho:.3f}")
    avg_rho = np.mean([r for _, r in fold_rhos])
    print(f"    XGBoost CV avg Spearman={avg_rho:.3f}  params={best_xgb_params}")
    metrics["xgboost"] = {"cv_spearman_avg": round(avg_rho, 4), "cv_folds": [{"season": s, "spearman": round(r, 4)} for s, r in fold_rhos], "best_params": best_xgb_params}

    X_va_all = labeled[FEATURE_COLS].fillna(0).values  # use all for final eval set
    final_xgb = xgb.XGBRegressor(n_estimators=best_xgb_params["n_est"], max_depth=best_xgb_params["max_depth"], learning_rate=best_xgb_params["lr"], subsample=best_xgb_params["subsample"], colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=1.0, random_state=42, verbosity=0)
    final_xgb.fit(X_all, y_all)
    models["xgboost"] = final_xgb
    with open(ML / "model_xgboost.pkl", "wb") as f:
        pickle.dump({"model": final_xgb, "features": FEATURE_COLS, "params": best_xgb_params}, f)

    def _to_py(obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, dict): return {k: _to_py(v) for k, v in obj.items()}
        if isinstance(obj, list): return [_to_py(v) for v in obj]
        return obj
    with open(ML / "metrics.json", "w") as f:
        json.dump(_to_py(metrics), f, indent=2)
    print(f"\n  Metrics saved → {ML}/metrics.json")

    return models, metrics


# ── Step 6: Generate 2026 predictions ─────────────────────────────────────────

def generate_2026_predictions(models, fm, years_data):
    """
    Use 2025 stats as prior year features + FantasyCalc redraft rankings as 2026 ADP proxy.
    """
    pred_path = ML / "predictions_2026.json"
    if pred_path.exists():
        print("  [2026 Predictions] Already exists, skipping.")
        return

    print("\n  [2026 Predictions] Generating...")

    # Fetch live FantasyCalc redraft rankings as 2026 ADP proxy
    import urllib.request
    try:
        url = "https://api.fantasycalc.com/values/current?isDynasty=false&numQbs=1"
        req = urllib.request.Request(url, headers={"User-Agent": "GridIron/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            fc_data = json.load(resp)
        print(f"  [2026 ADP] Fetched {len(fc_data)} players from FantasyCalc")
    except Exception as e:
        print(f"  [2026 ADP] Failed to fetch FantasyCalc: {e}. Using 2025 ADP as fallback.")
        fc_data = []

    # Build 2026 ADP from FantasyCalc
    adp_2026 = {}
    pos_counters = {"QB": 0, "WR": 0, "RB": 0, "TE": 0}
    if fc_data:
        # Sort by overallRank
        fc_sorted = sorted(fc_data, key=lambda x: x.get("overallRank", 9999))
        for entry in fc_sorted:
            p = entry.get("player", {})
            name_n = norm(p.get("name", ""))
            pos = p.get("position", "")
            if pos not in POSITIONS:
                continue
            overall_rank = entry.get("overallRank", 999)
            if overall_rank > ADP_CUTOFF:
                continue
            pos_counters[pos] = pos_counters.get(pos, 0) + 1
            adp_2026[name_n] = {
                "name": p.get("name", ""),
                "position": pos,
                "team": TEAM_FIX.get(p.get("maybeTeam", ""), p.get("maybeTeam", "")),
                "overall_adp": float(overall_rank),
                "pos_adp_rank": pos_counters[pos],
                "age": p.get("maybeAge", None),
            }
    else:
        # Fallback: use 2025 ADP
        adp_path = BACKEND / "data_2025_preseason_adp.json"
        if adp_path.exists():
            with open(adp_path) as f:
                adp_2025 = json.load(f)["players"]
            for p in adp_2025:
                adp_2026[norm(p["name"])] = p

    # Get 2025 actual stats as prior year features
    stats_2025 = years_data.get(2025, pd.DataFrame())
    stats_2024 = years_data.get(2024, pd.DataFrame())

    if stats_2025.empty:
        print("  [2026 Predictions] No 2025 stats available. Using 2024 stats as prior year.")
        stats_2025 = years_data.get(2024, pd.DataFrame())
        stats_2024 = years_data.get(2023, pd.DataFrame())

    # Normalize names in stats
    if not stats_2025.empty:
        if "player_name" in stats_2025.columns:
            stats_2025["name_norm"] = stats_2025["player_name"].apply(norm)
        elif "player_display_name" in stats_2025.columns:
            stats_2025["name_norm"] = stats_2025["player_display_name"].apply(norm)

    if not stats_2024.empty:
        if "player_name" in stats_2024.columns:
            stats_2024["name_norm"] = stats_2024["player_name"].apply(norm)
        elif "player_display_name" in stats_2024.columns:
            stats_2024["name_norm"] = stats_2024["player_display_name"].apply(norm)

    # Load raw 2025 season stats parquet for extended columns
    raw_2025_path = BACKEND / "data_2025_season_stats.parquet"
    if raw_2025_path.exists():
        raw_2025 = pd.read_parquet(raw_2025_path)
        if "player_name" in raw_2025.columns:
            raw_2025["name_norm"] = raw_2025["player_name"].apply(norm)
        elif "player_display_name" in raw_2025.columns:
            raw_2025["name_norm"] = raw_2025["player_display_name"].apply(norm)
    else:
        raw_2025 = pd.DataFrame()

    # Load NGS + snap data for 2025 (prior year for 2026 predictions)
    ngs_recv_2025, ngs_rush_2025, ngs_pass_2025, snaps_2025 = _load_ngs_snaps(2025)

    # Draft capital + combine for 2026 rookies (draft class 2026) and any veteran lookups
    print("  [Draft/Combine 2026] Building lookup...")
    draft_combine_2026 = build_draft_combine_lookup(list(range(2015, 2027)))

    rows = []
    for name_n, adp_entry in adp_2026.items():
        pos = adp_entry.get("position", "")
        if pos not in POSITIONS:
            continue

        # Prior year (2025) stats
        if not stats_2025.empty and "name_norm" in stats_2025.columns:
            m = stats_2025[stats_2025["name_norm"] == name_n]
        else:
            m = pd.DataFrame()

        # Check if player has appeared in ANY of the last 5 seasons
        prior_season_dfs = {
            yr: years_data.get(yr, pd.DataFrame())
            for yr in range(2021, 2026)
            if yr in years_data
        }
        has_any_prior = any(
            not df.empty and "name_norm" in df.columns and name_n in df["name_norm"].values
            for df in prior_season_dfs.values()
        )

        if not m.empty:
            p = m.iloc[0]
            weighted_ppg_prev = p.get("weighted_ppg", 0) or 0
            ppg_prev = p.get("ppg", 0) or 0
            games_prev = p.get("games", 0) or 0
            fp_prev = p.get("fantasy_points_ppr", 0) or 0
            games_missed_prev = SEASON_GAMES.get(2025, 17) - games_prev
            is_rookie = 0
            player_id = p.get("player_id", "")
            age = adp_entry.get("age") or p.get("age", 26) or 26
        else:
            weighted_ppg_prev = 0
            ppg_prev = 0
            games_prev = 0
            fp_prev = 0
            games_missed_prev = 17
            is_rookie = 0 if has_any_prior else 1
            player_id = ""
            age = adp_entry.get("age", 23) or 23

        # Two-year trend
        if not stats_2024.empty and "name_norm" in stats_2024.columns:
            m2 = stats_2024[stats_2024["name_norm"] == name_n]
        else:
            m2 = pd.DataFrame()

        if not m2.empty:
            weighted_ppg_prev2 = m2.iloc[0].get("weighted_ppg", 0) or 0
            trend = weighted_ppg_prev - weighted_ppg_prev2
        else:
            weighted_ppg_prev2 = 0
            trend = 0

        # Raw 2025 stats for new feature columns
        if not raw_2025.empty and "name_norm" in raw_2025.columns:
            raw_m = raw_2025[raw_2025["name_norm"] == name_n]
            rp = raw_m.iloc[0] if not raw_m.empty else None
        else:
            rp = None

        def _get(src, col, default=0):
            if src is None:
                return default
            v = src.get(col, default)
            return default if pd.isna(v) else v

        targets_prev = _get(rp, "targets", 0) if pos in ("WR", "TE", "RB") else 0
        carries_prev = _get(rp, "carries", 0) if pos in ("RB", "QB") else 0
        tgt_sh_prev = _get(rp, "tgt_sh", 0) if pos in ("WR", "TE", "RB") else 0
        ay_sh_prev = _get(rp, "ay_sh", 0) if pos in ("WR", "TE") else 0
        wopr_prev = _get(rp, "wopr_y", 0) if pos in ("WR", "TE", "RB") else 0
        rec_epa_prev = _get(rp, "receiving_epa", 0) if pos != "QB" else 0
        rush_epa_prev = _get(rp, "rushing_epa", 0) if pos not in ("WR", "TE") else 0
        pass_epa_prev = _get(rp, "passing_epa", 0) if pos == "QB" else 0
        dom_prev = _get(rp, "dom", 0)
        years_exp_prev = _get(rp, "years_exp", 0)
        team_change = 0  # unknown for 2026 predictions — teams may not be set yet

        targets_per_game_prev = (targets_prev / games_prev) if games_prev > 0 and pos in ("WR", "TE", "RB") else 0
        carries_per_game_prev = (carries_prev / games_prev) if games_prev > 0 and pos in ("RB", "QB") else 0
        age_sq = float(age) ** 2

        def _ngs_lookup(ngs_dict, pid, nn):
            row_data = ngs_dict.get(pid) if pid else None
            if row_data is None:
                row_data = ngs_dict.get(nn)
            return row_data

        ngs_r = _ngs_lookup(ngs_recv_2025, player_id, name_n) if pos in ("WR", "TE") else None
        separation_prev = _get(ngs_r, "avg_separation", 0)
        cushion_prev = _get(ngs_r, "avg_cushion", 0)
        yac_above_exp_prev = _get(ngs_r, "avg_yac_above_expectation", 0)
        catch_pct_prev = _get(ngs_r, "catch_percentage", 0)

        ngs_ru = _ngs_lookup(ngs_rush_2025, player_id, name_n) if pos == "RB" else None
        ryoe_per_att_prev = _get(ngs_ru, "rush_yards_over_expected_per_att", 0)
        rush_pct_over_exp_prev = _get(ngs_ru, "rush_pct_over_expected", 0)
        stacked_box_pct_prev = _get(ngs_ru, "percent_attempts_gte_eight_defenders", 0)

        ngs_p = _ngs_lookup(ngs_pass_2025, player_id, name_n) if pos == "QB" else None
        cpoe_prev = _get(ngs_p, "completion_percentage_above_expectation", 0)
        aggressiveness_prev = _get(ngs_p, "aggressiveness", 0)
        qb_air_yards_prev = _get(ngs_p, "avg_intended_air_yards", 0)

        snap_row = snaps_2025.get(name_n)
        snap_pct_prev = _get(snap_row, "offense_pct", 0)

        # Draft capital + combine
        dc = draft_combine_2026.get(player_id) or draft_combine_2026.get(f"name:{name_n}", {})
        draft_round    = dc.get("draft_round", 8)
        draft_pick     = dc.get("draft_pick", 300)
        is_undrafted   = int(draft_round == 8)
        draft_pick_norm = max(0.0, 1.0 - (draft_pick - 1) / 299)
        forty          = dc.get("forty", np.nan)
        vertical       = dc.get("vertical", np.nan)
        broad_jump     = dc.get("broad_jump", np.nan)
        cone           = dc.get("cone", np.nan)
        weight         = dc.get("weight", np.nan)
        height_in      = dc.get("height_in", np.nan)

        rows.append({
            "name_norm": name_n,
            "name": adp_entry.get("name", ""),
            "player_id": player_id,
            "position": pos,
            "team": adp_entry.get("team", ""),
            "overall_adp": adp_entry.get("overall_adp", 999),
            "pos_adp_rank": adp_entry.get("pos_adp_rank", 99),
            "age": float(age),
            "weighted_ppg_prev": weighted_ppg_prev,
            "ppg_prev": ppg_prev,
            "games_prev": games_prev,
            "fp_prev": fp_prev,
            "weighted_ppg_prev2": weighted_ppg_prev2,
            "trend_weighted_ppg": trend,
            "games_missed_prev": games_missed_prev,
            "is_rookie": is_rookie,
            "pos_QB": int(pos == "QB"),
            "pos_WR": int(pos == "WR"),
            "pos_RB": int(pos == "RB"),
            "pos_TE": int(pos == "TE"),
            "targets_prev": targets_prev,
            "carries_prev": carries_prev,
            "tgt_sh_prev": tgt_sh_prev,
            "ay_sh_prev": ay_sh_prev,
            "wopr_prev": wopr_prev,
            "rec_epa_prev": rec_epa_prev,
            "rush_epa_prev": rush_epa_prev,
            "pass_epa_prev": pass_epa_prev,
            "dom_prev": dom_prev,
            "years_exp_prev": years_exp_prev,
            "team_change": team_change,
            "separation_prev": separation_prev,
            "cushion_prev": cushion_prev,
            "yac_above_exp_prev": yac_above_exp_prev,
            "catch_pct_prev": catch_pct_prev,
            "ryoe_per_att_prev": ryoe_per_att_prev,
            "rush_pct_over_exp_prev": rush_pct_over_exp_prev,
            "stacked_box_pct_prev": stacked_box_pct_prev,
            "cpoe_prev": cpoe_prev,
            "aggressiveness_prev": aggressiveness_prev,
            "qb_air_yards_prev": qb_air_yards_prev,
            "snap_pct_prev": snap_pct_prev,
            "age_sq": age_sq,
            "targets_per_game_prev": targets_per_game_prev,
            "carries_per_game_prev": carries_per_game_prev,
            # Draft capital + combine
            "draft_round": draft_round,
            "draft_pick_norm": draft_pick_norm,
            "is_undrafted": is_undrafted,
            "forty": forty,
            "vertical": vertical,
            "broad_jump": broad_jump,
            "cone": cone,
            "weight": weight,
            "height_in": height_in,
        })

    if not rows:
        print("  [2026 Predictions] No rows built. Aborting.")
        return

    pred_df = pd.DataFrame(rows)
    X_pred = pred_df[FEATURE_COLS].fillna(0).values

    # Ensemble predictions
    all_preds = {}

    r_model, r_scaler = models["ridge"]
    X_pred_s = r_scaler.transform(X_pred)
    all_preds["ridge"] = r_model.predict(X_pred_s)

    all_preds["random_forest"] = models["random_forest"].predict(X_pred)
    all_preds["xgboost"] = models["xgboost"].predict(X_pred)

    pred_arr = np.stack([all_preds["ridge"], all_preds["random_forest"], all_preds["xgboost"]])
    ensemble_mean = pred_arr.mean(axis=0)
    ensemble_std = pred_arr.std(axis=0)

    pred_df["predicted_value_score"] = ensemble_mean
    pred_df["confidence"] = ensemble_std
    pred_df["ridge_pred"] = all_preds["ridge"]
    pred_df["rf_pred"] = all_preds["random_forest"]
    pred_df["xgb_pred"] = all_preds["xgboost"]

    pred_df = pred_df.sort_values("predicted_value_score", ascending=False)

    results = []
    for _, row in pred_df.iterrows():
        results.append({
            "player_id": row.get("player_id", ""),
            "name": row["name"],
            "position": row["position"],
            "team": row["team"],
            "predicted_value_score": round(float(row["predicted_value_score"]), 2),
            "confidence": round(float(row["confidence"]), 2),
            "adp_rank": int(row["overall_adp"]),
            "pos_adp_rank": int(row["pos_adp_rank"]),
            "prior_weighted_ppg": round(float(row["weighted_ppg_prev"]), 3),
            "prior_games": int(row["games_prev"]),
            "is_rookie": bool(row["is_rookie"]),
            "age": float(row["age"]),
            "draft_round": int(row.get("draft_round", 8)) if not pd.isna(row.get("draft_round", 8)) else 8,
            "draft_pick_norm": round(float(row.get("draft_pick_norm", 0)), 3),
            "is_undrafted": bool(row.get("is_undrafted", 1)),
            "forty": round(float(row["forty"]), 2) if pd.notna(row.get("forty")) else None,
            "vertical": round(float(row["vertical"]), 1) if pd.notna(row.get("vertical")) else None,
            "broad_jump": round(float(row["broad_jump"]), 0) if pd.notna(row.get("broad_jump")) else None,
            "ridge_pred": round(float(row["ridge_pred"]), 2),
            "rf_pred": round(float(row["rf_pred"]), 2),
            "xgb_pred": round(float(row["xgb_pred"]), 2),
        })

    with open(pred_path, "w") as f:
        json.dump({"generated": "2026-06-04", "players": results}, f, indent=2)
    print(f"  [2026 Predictions] Saved {len(results)} players to {pred_path}")

    # Spot-check top 10
    print("\n  === TOP 10 PREDICTED 2026 VALUE PICKS ===")
    print(f"  {'Rank':<5} {'Name':<25} {'Pos':<5} {'ADP':<6} {'Score':<8} {'Conf':<8} {'Prev wPPG'}")
    for i, r in enumerate(results[:10], 1):
        print(f"  {i:<5} {r['name']:<25} {r['position']:<5} {r['adp_rank']:<6} {r['predicted_value_score']:<8.1f} {r['confidence']:<8.2f} {r['prior_weighted_ppg']:.3f}")


# ── Main Pipeline ──────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("NFL Fantasy Value Score ML Pipeline")
    print("=" * 60)

    import nfl_data_py as nfl  # noqa

    # ── Collect data for all years ──
    ALL_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
    years_data = {}

    for year in ALL_YEARS:
        print(f"\n[Year {year}]")
        adp_players = fetch_adp(year)
        stats_df = fetch_season_stats(year)
        fetch_ngs_snap_data(year)

        if not adp_players or stats_df.empty:
            print(f"  Skipping {year} due to missing data.")
            years_data[year] = pd.DataFrame()
            continue

        # Add name_norm to stats
        if "player_name" in stats_df.columns:
            stats_df["name_norm"] = stats_df["player_name"].apply(norm)
        elif "player_display_name" in stats_df.columns:
            stats_df["name_norm"] = stats_df["player_display_name"].apply(norm)

        value_df = compute_value_score(adp_players, stats_df, year)
        print(f"  Computed value scores for {len(value_df)} players in {year}")
        years_data[year] = value_df

    # ── Build feature matrix ──
    fm_path = ML / "feature_matrix.parquet"
    if fm_path.exists():
        print(f"\n[Feature Matrix] Loading from cache...")
        fm = pd.read_parquet(fm_path)
    else:
        print(f"\n[Feature Matrix] Building...")
        # Build raw stats dict for prev-year lookups
        raw_stats = {}
        for year in ALL_YEARS:
            sp = BACKEND / f"data_{year}_season_stats.parquet"
            if sp.exists():
                raw_stats[year] = pd.read_parquet(sp)
                if "player_name" in raw_stats[year].columns:
                    raw_stats[year]["name_norm"] = raw_stats[year]["player_name"].apply(norm)

        fm = build_feature_matrix(years_data)
        fm.to_parquet(fm_path, index=False)
        print(f"  Feature matrix: {len(fm)} rows, {len(fm.columns)} columns")
        print(f"  Saved to {fm_path}")

    print(f"\n  Season distribution:\n{fm.groupby('season')['value_score'].describe().round(2)}")

    labeled = fm.dropna(subset=["value_score"])
    print(f"\n[Walk-forward CV] {len(labeled)} labeled rows across seasons: {sorted(labeled['season'].unique())}")

    if len(labeled) < 20:
        print("ERROR: Not enough labeled data. Check data collection.")
        return

    # ── Train models (walk-forward CV + final refit on all data) ──
    print("\n[Training]")
    models, metrics = train_models(fm)

    # Print summary
    print("\n[Test Set Results]")
    for name, m in metrics.items():
        print(f"  {name}: CV avg Spearman={m['cv_spearman_avg']:.3f}  folds={[f['spearman'] for f in m['cv_folds']]}")

    best_model = max(metrics, key=lambda k: metrics[k]["cv_spearman_avg"])
    print(f"\n  Best model by CV Spearman: {best_model} (avg rho={metrics[best_model]['cv_spearman_avg']:.3f})")

    # ── Load raw stats dict for 2026 predictions ──
    raw_stats = {}
    for year in [2024, 2025]:
        sp = BACKEND / f"data_{year}_season_stats.parquet"
        if sp.exists():
            raw_stats[year] = pd.read_parquet(sp)
            if "player_name" in raw_stats[year].columns:
                raw_stats[year]["name_norm"] = raw_stats[year]["player_name"].apply(norm)

    # ── Generate 2026 predictions ──
    generate_2026_predictions(models, fm, raw_stats)

    print("\n[Pipeline Complete]")


if __name__ == "__main__":
    main()
