"""
NFL Run/Pass Play-Calling Predictor
=====================================
Predicts whether a given offensive snap will be a run or a pass using only
pre-snap situational information, then compares the model's pick to what the
offense actually did to rank the 32 teams from most to least predictable.

TARGET: pass_attempt (1 = pass, 0 = run) for every non-special-teams,
non-kneel/spike, non-two-point offensive snap.

FEATURES (all known before the snap):
  - down, ydstogo, yardline_100 (field position)
  - score_differential (posteam perspective), qtr, game_seconds_remaining
  - posteam_timeouts_remaining, defteam_timeouts_remaining
  - shotgun, no_huddle, is_home
  - personnel package: offense RB/TE/WR counts parsed from offense_personnel
  - posteam, defteam (team identity, native XGBoost categorical)

MODEL CHOICE JUSTIFICATION
---------------------------
Dataset: ~40-45k plays/season x 5 seasons ~= 200k rows, ~20 features, binary
target. This is squarely tabular, medium-size, non-linear (down x distance x
field position interact heavily, e.g. "3rd and short near midfield" behaves
nothing like a linear combination of down/distance/field position alone).

- Logistic Regression: fine baseline, but can't capture down x distance x
  score interactions without manual feature crosses.
- Random Forest: robust, no scaling needed, but weaker than boosting on this
  much data and slower to reach similar accuracy.
- XGBoost: best fit here -- boosting captures the interaction effects that
  actually drive play-calling (e.g. 3rd-and-short vs 3rd-and-long is a totally
  different distribution), handles the team categorical natively, gives clean
  feature importances, and trains in seconds on data this size. Chosen as the
  sole model.

PREDICTABILITY METHODOLOGY
---------------------------
Train on TRAIN_YEARS, evaluate on the held-out TEST_YEAR (a season the model
never saw). The model has learned each team's tendencies *as of the training
years* plus league-wide situational norms. For every held-out play we compare
the model's predicted call (argmax of predicted pass probability) to the
offense's actual call:

  - accuracy per team  -> how often the model's guess matched reality
  - log loss per team  -> how confidently wrong the model was when it missed

Teams with HIGH accuracy / LOW log loss are "predictable": their situational
tendencies are stable and a model trained on their recent past nails their
calls. Teams with LOW accuracy / HIGH log loss are "unpredictable": they
deviate from both league norms and their own historical tendencies often
enough that even a model with team-specific history struggles.
"""

import re
import json
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score, confusion_matrix
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import nfl_data_py as nfl

warnings.filterwarnings("ignore")

# ── Paths ─────────────────────────────────────────────────────────────────────
ML = Path(__file__).parent
RAW_CACHE = ML / "pbp_raw"
OUT = ML / "play_prediction_output"
RAW_CACHE.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

# ── Config ────────────────────────────────────────────────────────────────────
TRAIN_YEARS = [2019, 2020, 2021, 2022, 2023]
TEST_YEAR = 2024

FEATURE_COLS = [
    "down", "ydstogo", "yardline_100", "score_differential", "qtr",
    "game_seconds_remaining", "posteam_timeouts_remaining",
    "defteam_timeouts_remaining", "shotgun", "no_huddle", "is_home",
    "off_rb", "off_te", "off_wr", "off_ol",
    "posteam", "defteam",
]
CATEGORICAL_COLS = ["posteam", "defteam"]
TARGET = "pass_attempt"


# ── Data loading ─────────────────────────────────────────────────────────────
def load_season(year: int) -> pd.DataFrame:
    """Download (or read cached) raw PBP for one season."""
    path = RAW_CACHE / f"pbp_{year}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    print(f"  downloading {year} play-by-play...")
    df = nfl.import_pbp_data([year], downcast=True, cache=False)
    df.to_parquet(path)
    return df


PERSONNEL_RE = re.compile(r"(\d+)\s*(RB|TE|WR|OL|QB)")


def parse_personnel(series: pd.Series) -> pd.DataFrame:
    """'1 RB, 2 TE, 2 WR' -> off_rb=1, off_te=2, off_wr=2, off_ol=0 (OL only listed for jumbo/heavy sets)."""
    out = pd.DataFrame(index=series.index)
    for pos, col in [("RB", "off_rb"), ("TE", "off_te"), ("WR", "off_wr"), ("OL", "off_ol")]:
        out[col] = series.fillna("").str.extract(rf"(\d+)\s*{pos}", expand=False).astype(float)
    out["off_ol"] = out["off_ol"].fillna(0)
    # base personnel always has 5 offensive linemen; off_ol counts only *extra* OL used
    # in jumbo packages (e.g. "6 OL, 1 RB, 2 TE, 2 WR" reports 6, so keep as-is).
    return out


def build_features(pbp: pd.DataFrame) -> pd.DataFrame:
    df = pbp[
        (pbp["play_type"].isin(["run", "pass"]))
        & (pbp["qb_kneel"] == 0)
        & (pbp["qb_spike"] == 0)
        & (pbp["two_point_attempt"] == 0)
        & (pbp["down"].notna())
    ].copy()

    personnel = parse_personnel(df["offense_personnel"])
    df = pd.concat([df, personnel], axis=1)

    df["is_home"] = (df["posteam"] == df["home_team"]).astype(int)
    df["pass_attempt"] = df["pass_attempt"].astype(int)

    keep = FEATURE_COLS + [TARGET, "season", "week", "game_id"]
    df = df[keep].dropna(subset=[c for c in FEATURE_COLS if c not in CATEGORICAL_COLS])

    for col in CATEGORICAL_COLS:
        df[col] = df[col].astype("category")

    return df.reset_index(drop=True)


def load_dataset(years: list[int]) -> pd.DataFrame:
    frames = []
    for y in years:
        raw = load_season(y)
        frames.append(build_features(raw))
    return pd.concat(frames, ignore_index=True)


# ── Training ──────────────────────────────────────────────────────────────────
def align_categories(train_df: pd.DataFrame, test_df: pd.DataFrame):
    """XGBoost categorical support needs matching category sets between train/test."""
    for col in CATEGORICAL_COLS:
        cats = sorted(set(train_df[col].astype(str)) | set(test_df[col].astype(str)))
        train_df[col] = train_df[col].astype(str).astype("category").cat.set_categories(cats)
        test_df[col] = test_df[col].astype(str).astype("category").cat.set_categories(cats)
    return train_df, test_df


def train_model(train_df: pd.DataFrame):
    X = train_df[FEATURE_COLS]
    y = train_df[TARGET]

    model = xgb.XGBClassifier(
        n_estimators=400,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="logloss",
        enable_categorical=True,
        tree_method="hist",
        random_state=42,
    )
    model.fit(X, y)
    return model


# ── Evaluation / predictability ranking ─────────────────────────────────────
def evaluate(model, test_df: pd.DataFrame) -> pd.DataFrame:
    X = test_df[FEATURE_COLS]
    y = test_df[TARGET]

    proba = model.predict_proba(X)[:, 1]
    pred = (proba >= 0.5).astype(int)

    print(f"\nHeld-out {TEST_YEAR} season — overall model performance")
    print(f"  accuracy : {accuracy_score(y, pred):.4f}")
    print(f"  AUC      : {roc_auc_score(y, proba):.4f}")
    print(f"  log loss : {log_loss(y, proba):.4f}")
    print(f"  baseline (always predict league pass rate): "
          f"{max(y.mean(), 1 - y.mean()):.4f} accuracy if always guessing majority class")

    out = test_df[["posteam", TARGET]].copy()
    out["pred"] = pred
    out["proba"] = proba
    out["correct"] = (out["pred"] == out[TARGET]).astype(int)
    return out


def predictability_by_team(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for team, g in results.groupby("posteam", observed=True):
        rows.append({
            "team": team,
            "plays": len(g),
            "accuracy": accuracy_score(g[TARGET], g["pred"]),
            "log_loss": log_loss(g[TARGET], g["proba"], labels=[0, 1]),
            "actual_pass_rate": g[TARGET].mean(),
        })
    ranking = pd.DataFrame(rows).sort_values("accuracy", ascending=False).reset_index(drop=True)
    ranking["predictability_rank"] = ranking.index + 1
    return ranking


# ── Plots ─────────────────────────────────────────────────────────────────────
def plot_predictability(ranking: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(9, 11))
    ordered = ranking.sort_values("accuracy")
    colors = plt.cm.RdYlGn(np.interp(ordered["accuracy"], (ordered["accuracy"].min(), ordered["accuracy"].max()), (0, 1)))
    ax.barh(ordered["team"], ordered["accuracy"], color=colors)
    ax.axvline(ranking["accuracy"].mean(), color="black", linestyle="--", linewidth=1, label="league avg")
    ax.set_xlabel("Model accuracy predicting actual play call")
    ax.set_title(f"NFL Offensive Predictability, {TEST_YEAR} Season\n(low = defies tendencies, high = plays to form)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "predictability_ranking.png", dpi=150)
    plt.close(fig)


def plot_feature_importance(model):
    importance = pd.Series(model.feature_importances_, index=FEATURE_COLS).sort_values()
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh(importance.index, importance.values, color="#2b6cb0")
    ax.set_title("Feature Importance — Run/Pass Predictor")
    ax.set_xlabel("XGBoost importance (gain)")
    fig.tight_layout()
    fig.savefig(OUT / "feature_importance.png", dpi=150)
    plt.close(fig)


def plot_confusion(results: pd.DataFrame):
    cm = confusion_matrix(results[TARGET], results["pred"])
    fig, ax = plt.subplots(figsize=(5, 5))
    im = ax.imshow(cm, cmap="Blues")
    labels = ["Run", "Pass"]
    ax.set_xticks([0, 1]); ax.set_xticklabels(labels)
    ax.set_yticks([0, 1]); ax.set_yticklabels(labels)
    ax.set_xlabel("Predicted"); ax.set_ylabel("Actual")
    ax.set_title(f"Confusion Matrix — {TEST_YEAR} Holdout")
    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"{cm[i, j]:,}", ha="center", va="center",
                     color="white" if cm[i, j] > cm.max() / 2 else "black")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(OUT / "confusion_matrix.png", dpi=150)
    plt.close(fig)


def plot_pass_rate_by_down(test_df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(7, 5))
    rates = test_df.groupby("down")[TARGET].mean()
    ax.bar(rates.index.astype(str), rates.values, color="#c05621")
    ax.set_xlabel("Down"); ax.set_ylabel("Actual pass rate")
    ax.set_title(f"League Pass Rate by Down — {TEST_YEAR}")
    for i, v in enumerate(rates.values):
        ax.text(i, v + 0.01, f"{v:.0%}", ha="center")
    fig.tight_layout()
    fig.savefig(OUT / "pass_rate_by_down.png", dpi=150)
    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"Loading training seasons {TRAIN_YEARS}...")
    train_df = load_dataset(TRAIN_YEARS)
    print(f"  {len(train_df):,} plays")

    print(f"Loading test season {TEST_YEAR}...")
    test_df = load_dataset([TEST_YEAR])
    print(f"  {len(test_df):,} plays")

    train_df, test_df = align_categories(train_df, test_df)

    print("Training XGBoost classifier...")
    model = train_model(train_df)

    results = evaluate(model, test_df)
    ranking = predictability_by_team(results)

    print("\nMost predictable offenses (model calls it right most often):")
    print(ranking.head(5).to_string(index=False))
    print("\nLeast predictable offenses (model calls it right least often):")
    print(ranking.tail(5).sort_values("accuracy").to_string(index=False))

    print("\nGenerating plots...")
    plot_predictability(ranking)
    plot_feature_importance(model)
    plot_confusion(results)
    plot_pass_rate_by_down(test_df)

    model.save_model(OUT / "play_predictor_xgb.json")
    with open(OUT / "play_predictor.pkl", "wb") as f:
        pickle.dump(model, f)
    ranking.to_csv(OUT / "predictability_ranking.csv", index=False)

    importance = pd.Series(model.feature_importances_, index=FEATURE_COLS).sort_values(ascending=False)
    pass_rate_by_down = test_df.groupby("down")[TARGET].mean()

    metrics = {
        "train_years": TRAIN_YEARS,
        "test_year": TEST_YEAR,
        "n_train": len(train_df),
        "n_test": len(test_df),
        "accuracy": accuracy_score(results[TARGET], results["pred"]),
        "auc": roc_auc_score(results[TARGET], results["proba"]),
        "log_loss": log_loss(results[TARGET], results["proba"]),
        "majority_class_baseline": float(max(results[TARGET].mean(), 1 - results[TARGET].mean())),
        "feature_importance": [
            {"feature": f, "importance": float(v)} for f, v in importance.items()
        ],
        "pass_rate_by_down": [
            {"down": int(d), "pass_rate": float(r)} for d, r in pass_rate_by_down.items()
        ],
    }
    with open(OUT / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"\nSaved model, rankings, metrics, and plots to {OUT}/")


if __name__ == "__main__":
    main()
