"""
CB Coverage Pipeline
====================
Builds cornerback coverage profiles by combining:
  1. PFR weekly defensive stats (targets/game, comp%, yards/tgt, passer rating allowed)
  2. PBP route × coverage-type interaction data (man vs zone effectiveness per route)
  3. Depth chart assignments (LCB1, RCB1, NB1 per team)

Outputs (saved as parquet for caching):
  data_{YEAR}_cb_stats.parquet   — per-CB season aggregates
  data_{YEAR}_team_coverage.parquet — per-team coverage scheme % (man vs zone)
  data_{YEAR}_route_coverage.parquet — route performance by coverage type
  data_{YEAR}_cb_depth.parquet   — CB depth chart assignments (LCB1/RCB1/NB per team)
"""

import os
import warnings
import pandas as pd
import numpy as np
from pathlib import Path

warnings.filterwarnings("ignore")

BACKEND = Path(__file__).parent.parent
YEARS = [2022, 2023, 2024, 2025]

MAN_COVERAGE_TYPES = {"COVER_0", "COVER_1", "2_MAN"}
CB_POSITIONS = {"LCB", "RCB", "NB"}  # left CB, right CB, nickel


def norm_name(n):
    return (n or "").lower().replace("'", "").replace(".", "").replace("-", "").replace(" ", "")


def collect_cb_stats(year: int) -> pd.DataFrame:
    """
    Aggregate CB coverage stats from PFR weekly defensive data.
    Returns per-CB season summary with quality metrics.
    """
    out_path = BACKEND / f"data_{year}_cb_stats.parquet"
    if out_path.exists():
        print(f"  [CB Stats {year}] Loading from cache...")
        return pd.read_parquet(out_path)

    print(f"  [CB Stats {year}] Fetching PFR weekly defensive data...")
    import nfl_data_py as nfl

    try:
        pfr = nfl.import_weekly_pfr("def", [year])
    except Exception as e:
        print(f"  [CB Stats {year}] ERROR: {e}")
        return pd.DataFrame()

    # Filter to CBs only using a heuristic: they show up in PFR def
    # PFR doesn't have position in weekly — use seasonal to get position mapping
    try:
        pfr_season = nfl.import_seasonal_pfr("def", [year])
        cb_ids = set(pfr_season[pfr_season["pos"] == "CB"]["pfr_id"].dropna())
        pfr_weekly_cbs = pfr[pfr["pfr_player_id"].isin(cb_ids)].copy()
    except Exception:
        # Fallback: include all defensive players with coverage data
        pfr_weekly_cbs = pfr[pfr["def_targets"].notna() & (pfr["def_targets"] > 0)].copy()

    if pfr_weekly_cbs.empty:
        return pd.DataFrame()

    # Per-game aggregates
    agg = pfr_weekly_cbs.groupby(["pfr_player_id", "pfr_player_name", "team"]).agg(
        games=("week", "count"),
        total_targets=("def_targets", "sum"),
        total_completions=("def_completions_allowed", "sum"),
        total_yards=("def_yards_allowed", "sum"),
        total_tds=("def_receiving_td_allowed", "sum"),
        total_ints=("def_ints", "sum"),
        avg_passer_rating=("def_passer_rating_allowed", "mean"),
        avg_adot=("def_adot", "mean"),
        avg_yac=("def_yards_after_catch", "mean"),
        avg_air_yards=("def_air_yards_completed", "mean"),
    ).reset_index()

    agg["season"] = year
    agg["targets_per_game"] = (agg["total_targets"] / agg["games"]).round(2)
    agg["comp_pct"] = (agg["total_completions"] / agg["total_targets"].replace(0, np.nan)).round(3)
    agg["yards_per_target"] = (agg["total_yards"] / agg["total_targets"].replace(0, np.nan)).round(2)
    agg["td_per_target"] = (agg["total_tds"] / agg["total_targets"].replace(0, np.nan)).round(4)
    agg["name_norm"] = agg["pfr_player_name"].apply(norm_name)

    # Coverage quality score: lower passer rating allowed = better CB
    # Normalize passer rating allowed to 0-100 (100 = best, 0 = worst)
    # NFL average passer rating is ~90; elite CBs allow ~60-70, bad CBs 110+
    agg["coverage_quality"] = (
        (130 - agg["avg_passer_rating"].clip(39.6, 130)) / (130 - 39.6) * 100
    ).clip(0, 100).round(1)

    # Coverage grade (A-F)
    def grade(q):
        if pd.isna(q): return "—"
        if q >= 75: return "A+"
        if q >= 65: return "A"
        if q >= 55: return "B+"
        if q >= 45: return "B"
        if q >= 35: return "C"
        if q >= 25: return "D"
        return "F"

    agg["coverage_grade"] = agg["coverage_quality"].apply(grade)

    agg.to_parquet(out_path, index=False)
    print(f"  [CB Stats {year}] Saved {len(agg)} CBs → {out_path.name}")
    return agg


def collect_team_coverage(year: int) -> pd.DataFrame:
    """
    Compute per-team coverage scheme frequencies from PBP.
    Returns % man, % zone, % each specific coverage type per team.
    """
    out_path = BACKEND / f"data_{year}_team_coverage.parquet"
    if out_path.exists():
        print(f"  [Team Coverage {year}] Loading from cache...")
        return pd.read_parquet(out_path)

    print(f"  [Team Coverage {year}] Computing from PBP...")
    import nfl_data_py as nfl

    pbp = nfl.import_pbp_data([year], downcast=True)
    pass_plays = pbp[
        (pbp["pass_attempt"] == 1) &
        (pbp["defense_coverage_type"].notna()) &
        (pbp["defense_coverage_type"] != "")
    ].copy()

    if pass_plays.empty:
        return pd.DataFrame()

    pass_plays["is_man"] = pass_plays["defense_coverage_type"].isin(MAN_COVERAGE_TYPES).astype(int)

    team_cov = pass_plays.groupby("defteam").agg(
        total_plays=("defense_coverage_type", "count"),
        man_plays=("is_man", "sum"),
    ).reset_index()

    # Per coverage type %
    for cov_type in pass_plays["defense_coverage_type"].unique():
        if pd.notna(cov_type) and cov_type:
            col = f"pct_{cov_type.replace(' ', '_').replace('/', '_').lower()}"
            counts = pass_plays[pass_plays["defense_coverage_type"] == cov_type].groupby("defteam").size()
            team_cov[col] = team_cov["defteam"].map(counts).fillna(0) / team_cov["total_plays"]

    team_cov["pct_man"] = (team_cov["man_plays"] / team_cov["total_plays"]).round(3)
    team_cov["pct_zone"] = (1 - team_cov["pct_man"]).round(3)
    team_cov["season"] = year

    team_cov.to_parquet(out_path, index=False)
    print(f"  [Team Coverage {year}] Saved {len(team_cov)} teams → {out_path.name}")
    return team_cov


def collect_route_coverage(year: int) -> pd.DataFrame:
    """
    Route performance breakdown by coverage type (man vs zone).
    Used to predict which WR routes thrive vs a given team's scheme.
    """
    out_path = BACKEND / f"data_{year}_route_coverage.parquet"
    if out_path.exists():
        print(f"  [Route Coverage {year}] Loading from cache...")
        return pd.read_parquet(out_path)

    print(f"  [Route Coverage {year}] Computing from PBP...")
    import nfl_data_py as nfl

    pbp = nfl.import_pbp_data([year], downcast=True)
    pass_plays = pbp[
        (pbp["pass_attempt"] == 1) &
        (pbp["route"].notna()) &
        (pbp["route"] != "") &
        (pbp["defense_coverage_type"].notna())
    ].copy()

    pass_plays["is_man"] = pass_plays["defense_coverage_type"].isin(MAN_COVERAGE_TYPES).astype(int)

    route_man = pass_plays.groupby(["route", "is_man"]).agg(
        plays=("complete_pass", "count"),
        comp_pct=("complete_pass", "mean"),
        ypa=("yards_gained", "mean"),
        air_yards=("air_yards", "mean"),
    ).reset_index()

    route_man = route_man[route_man["plays"] >= 20]
    route_man["season"] = year
    route_man["coverage_type"] = route_man["is_man"].map({1: "man", 0: "zone"})

    route_man.to_parquet(out_path, index=False)
    print(f"  [Route Coverage {year}] Saved {len(route_man)} route×coverage rows → {out_path.name}")
    return route_man


def collect_cb_depth(year: int) -> pd.DataFrame:
    """
    CB depth chart assignments from nflverse.
    Maps team → LCB1, RCB1, NB1 player names/IDs.
    """
    out_path = BACKEND / f"data_{year}_cb_depth.parquet"
    if out_path.exists():
        print(f"  [CB Depth {year}] Loading from cache...")
        return pd.read_parquet(out_path)

    print(f"  [CB Depth {year}] Fetching depth charts...")
    import nfl_data_py as nfl

    dc = nfl.import_depth_charts([year])

    # Handle two different schema versions across seasons
    if "pos_abb" in dc.columns:
        # 2025+ schema: pos_abb, team, dt, pos_rank
        cb_dc = dc[dc["pos_abb"].isin(CB_POSITIONS)].copy()
        cb_dc = cb_dc.sort_values("dt", ascending=False)
        starters = cb_dc[cb_dc["pos_rank"] == 1].drop_duplicates(subset=["team", "pos_abb"], keep="first")
        result = starters.rename(columns={"pos_abb": "cb_slot"})[["team", "cb_slot", "player_name", "gsis_id"]].copy()
    else:
        # Pre-2025 schema: position, depth_position, club_code, depth_team, full_name
        CB_DEPTH_POSITIONS = {"CB", "LCB", "RCB", "NB", "SCB", "DB"}
        # depth_position contains slot like 'LCB', 'RCB', 'NB'
        pos_col = "depth_position" if "depth_position" in dc.columns else "position"
        team_col = "club_code" if "club_code" in dc.columns else "team"
        name_col = "full_name" if "full_name" in dc.columns else "player_name"
        gsis_col = "gsis_id" if "gsis_id" in dc.columns else None

        cb_dc = dc[dc[pos_col].isin(CB_DEPTH_POSITIONS) | dc["position"].eq("CB")].copy()
        cb_dc = cb_dc[cb_dc["depth_team"] == 1].copy()  # starters only

        TEAM_FIX = {"LAR": "LA", "JAC": "JAX", "LVR": "LV"}
        cb_dc["team"] = cb_dc[team_col].map(lambda t: TEAM_FIX.get(t, t))
        cb_dc["cb_slot"] = cb_dc[pos_col]
        cb_dc["player_name"] = cb_dc[name_col]
        cb_dc["gsis_id"] = cb_dc[gsis_col] if gsis_col else None

        # Sort by week descending to get latest
        if "week" in cb_dc.columns:
            cb_dc = cb_dc.sort_values("week", ascending=False)

        starters = cb_dc.drop_duplicates(subset=["team", "cb_slot"], keep="first")
        result = starters[["team", "cb_slot", "player_name", "gsis_id"]].copy()

    result["season"] = year
    result["name_norm"] = result["player_name"].apply(norm_name)

    result.to_parquet(out_path, index=False)
    print(f"  [CB Depth {year}] Saved {len(result)} CB starter assignments → {out_path.name}")
    return result


def main():
    print("\n=== CB Coverage Pipeline ===\n")

    for year in YEARS:
        print(f"\n--- Season {year} ---")
        collect_cb_stats(year)
        collect_team_coverage(year)
        collect_route_coverage(year)
        collect_cb_depth(year)

    print("\n=== CB Pipeline Complete ===")


if __name__ == "__main__":
    main()
