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


def build_feature_matrix(years_data: dict) -> pd.DataFrame:
    """
    Build the full feature matrix. For each player-season Y:
    - Target: value_score in season Y
    - Features: prior year (Y-1) and two-year prior (Y-2) stats
    """
    feature_rows = []

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

        for _, row in current.iterrows():
            name_n = row.get("name_norm", norm(row.get("name", "")))
            pos = row.get("position", "")

            # Look up prior year stats
            if not prev_stats.empty and "name_norm" in prev_stats.columns:
                prev_match = prev_stats[prev_stats["name_norm"] == name_n]
            else:
                prev_match = pd.DataFrame()

            if not prev2_stats.empty and "name_norm" in prev2_stats.columns:
                prev2_match = prev2_stats[prev2_stats["name_norm"] == name_n]
            else:
                prev2_match = pd.DataFrame()

            # Prior year features
            if not prev_match.empty:
                p = prev_match.iloc[0]
                weighted_ppg_prev = p.get("weighted_ppg", 0) or 0
                ppg_prev = p.get("ppg", 0) or 0
                games_prev = p.get("games", 0) or 0
                fp_prev = p.get("fantasy_points_ppr", 0) or 0
                games_missed_prev = SEASON_GAMES.get(prev_year, 17) - games_prev
                is_rookie = 0
            else:
                weighted_ppg_prev = 0
                ppg_prev = 0
                games_prev = 0
                fp_prev = 0
                games_missed_prev = SEASON_GAMES.get(prev_year, 17)
                is_rookie = 1

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
                age = 26  # league average if unknown

            # Position one-hot
            pos_QB = int(pos == "QB")
            pos_WR = int(pos == "WR")
            pos_RB = int(pos == "RB")
            pos_TE = int(pos == "TE")

            feature_rows.append({
                "season": year,
                "name": row.get("name", ""),
                "name_norm": name_n,
                "player_id": row.get("player_id", ""),
                "position": pos,
                # Features
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
    "weighted_ppg_prev", "ppg_prev", "games_prev", "fp_prev",
    "weighted_ppg_prev2", "trend_weighted_ppg",
    "age", "pos_adp_rank", "overall_adp",
    "games_missed_prev", "is_rookie",
    "pos_QB", "pos_WR", "pos_RB", "pos_TE",
]


# ── Step 4: Train/val/test splits ─────────────────────────────────────────────

def get_splits(fm: pd.DataFrame):
    train = fm[fm["season"].isin([2020, 2021, 2022])].dropna(subset=["value_score"])
    val   = fm[fm["season"] == 2023].dropna(subset=["value_score"])
    test  = fm[fm["season"] == 2024].dropna(subset=["value_score"])
    return train, val, test


def evaluate(y_true, y_pred, name=""):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    rho, pval = spearmanr(y_true, y_pred)
    print(f"    {name}: MAE={mae:.2f} RMSE={rmse:.2f} Spearman={rho:.3f} (p={pval:.3f})")
    return {"mae": mae, "rmse": rmse, "spearman": rho, "spearman_pval": pval}


# ── Step 5: Train models ───────────────────────────────────────────────────────

def train_models(train, val, test):
    X_tr = train[FEATURE_COLS].fillna(0).values
    y_tr = train["value_score"].values
    X_va = val[FEATURE_COLS].fillna(0).values
    y_va = val["value_score"].values
    X_te = test[FEATURE_COLS].fillna(0).values
    y_te = test["value_score"].values

    metrics = {}
    models = {}

    # ── Ridge Regression ──
    print("\n  Training Ridge...")
    best_ridge, best_ridge_spearman = None, -999
    for alpha in [0.1, 1.0, 5.0, 10.0, 50.0, 100.0]:
        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_va_s = scaler.transform(X_va)
        r = Ridge(alpha=alpha)
        r.fit(X_tr_s, y_tr)
        pred_va = r.predict(X_va_s)
        rho, _ = spearmanr(y_va, pred_va)
        if rho > best_ridge_spearman:
            best_ridge_spearman = rho
            best_ridge = (r, scaler, alpha)

    r_model, r_scaler, r_alpha = best_ridge
    print(f"    Best Ridge alpha={r_alpha} val_spearman={best_ridge_spearman:.3f}")
    X_te_s = r_scaler.transform(X_te)
    pred_te = r_model.predict(X_te_s)
    metrics["ridge"] = evaluate(y_te, pred_te, "Ridge (test)")
    metrics["ridge"]["best_alpha"] = r_alpha
    models["ridge"] = (r_model, r_scaler)
    with open(ML / "model_ridge.pkl", "wb") as f:
        pickle.dump({"model": r_model, "scaler": r_scaler, "features": FEATURE_COLS}, f)

    # ── Random Forest ──
    print("\n  Training Random Forest...")
    best_rf, best_rf_spearman = None, -999
    for n_est in [100, 200]:
        for max_depth in [3, 5, None]:
            for min_samples in [3, 5]:
                rf = RandomForestRegressor(
                    n_estimators=n_est, max_depth=max_depth,
                    min_samples_leaf=min_samples, random_state=42, n_jobs=-1
                )
                rf.fit(X_tr, y_tr)
                pred_va = rf.predict(X_va)
                rho, _ = spearmanr(y_va, pred_va)
                if rho > best_rf_spearman:
                    best_rf_spearman = rho
                    best_rf = rf

    print(f"    Best RF val_spearman={best_rf_spearman:.3f}")
    pred_te = best_rf.predict(X_te)
    metrics["random_forest"] = evaluate(y_te, pred_te, "Random Forest (test)")
    models["random_forest"] = best_rf
    with open(ML / "model_random_forest.pkl", "wb") as f:
        pickle.dump({"model": best_rf, "features": FEATURE_COLS}, f)

    # ── XGBoost ──
    print("\n  Training XGBoost...")
    best_xgb_model, best_xgb_spearman = None, -999
    best_xgb_params = {}
    for lr in [0.05, 0.1]:
        for max_depth in [3, 4, 5]:
            for n_est in [100, 200]:
                for subsample in [0.7, 1.0]:
                    xgb_m = xgb.XGBRegressor(
                        n_estimators=n_est, max_depth=max_depth,
                        learning_rate=lr, subsample=subsample,
                        colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=1.0,
                        random_state=42, verbosity=0
                    )
                    xgb_m.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False)
                    pred_va = xgb_m.predict(X_va)
                    rho, _ = spearmanr(y_va, pred_va)
                    if rho > best_xgb_spearman:
                        best_xgb_spearman = rho
                        best_xgb_model = xgb_m
                        best_xgb_params = {"lr": lr, "max_depth": max_depth, "n_est": n_est, "subsample": subsample}

    print(f"    Best XGBoost params={best_xgb_params} val_spearman={best_xgb_spearman:.3f}")
    pred_te = best_xgb_model.predict(X_te)
    metrics["xgboost"] = evaluate(y_te, pred_te, "XGBoost (test)")
    metrics["xgboost"]["best_params"] = best_xgb_params
    models["xgboost"] = best_xgb_model
    with open(ML / "model_xgboost.pkl", "wb") as f:
        pickle.dump({"model": best_xgb_model, "features": FEATURE_COLS, "params": best_xgb_params}, f)

    # Save metrics
    with open(ML / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\n  Metrics saved to {ML}/metrics.json")

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
            is_rookie = 1
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

    # ── Train/val/test splits ──
    train, val, test = get_splits(fm)
    print(f"\n[Splits] Train: {len(train)} | Val: {len(val)} | Test: {len(test)}")

    if len(train) < 10:
        print("ERROR: Not enough training data. Check data collection.")
        return

    # ── Train models ──
    print("\n[Training]")
    models, metrics = train_models(train, val, test)

    # Print summary
    print("\n[Test Set Results]")
    for name, m in metrics.items():
        print(f"  {name}: Spearman={m['spearman']:.3f} MAE={m['mae']:.2f} RMSE={m['rmse']:.2f}")

    best_model = max(metrics, key=lambda k: metrics[k]["spearman"])
    print(f"\n  Best model by Spearman: {best_model} (rho={metrics[best_model]['spearman']:.3f})")

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
