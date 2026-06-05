import os
import json
import asyncio
from functools import lru_cache
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import nfl_data_py as nfl
import pandas as pd
import anthropic

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# ── Data cache ──────────────────────────────────────────────────────────────

_cache: dict = {}

def _agg_stats_from_pbp(pbp: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-player season totals from play-by-play.
    Each player_id produces exactly ONE row — all stats (passing, rushing, receiving)
    are accumulated together. Position is NOT assigned here; the caller merges roster data.
    """
    reg = pbp[pbp["season_type"] == "REG"]

    # ── Passing stats (keyed on passer_player_id) ──
    pass_agg = (
        reg[reg["passer_player_id"].notna()]
        .groupby("passer_player_id")
        .agg(
            completions=("complete_pass", "sum"),
            attempts=("pass_attempt", "sum"),
            passing_yards=("passing_yards", "sum"),
            passing_tds=("pass_touchdown", "sum"),
            interceptions=("interception", "sum"),
            passing_epa=("epa", "sum"),
            sacks=("sack", "sum"),
        )
        .reset_index()
        .rename(columns={"passer_player_id": "player_id"})
    )

    # ── Rushing stats (keyed on rusher_player_id) ──
    rush_plays = reg[reg["rusher_player_id"].notna() & reg["rush_attempt"].eq(1)]
    rush_agg = (
        rush_plays
        .groupby("rusher_player_id")
        .agg(
            carries=("rush_attempt", "sum"),
            rushing_yards=("rushing_yards", "sum"),
            rushing_tds=("rush_touchdown", "sum"),
            rushing_epa=("epa", "sum"),
        )
        .reset_index()
        .rename(columns={"rusher_player_id": "player_id"})
    )

    # ── Receiving stats (keyed on receiver_player_id) ──
    rec_plays = reg[reg["receiver_player_id"].notna()]
    rec_agg = (
        rec_plays
        .groupby("receiver_player_id")
        .agg(
            targets=("pass_attempt", "sum"),
            receptions=("complete_pass", "sum"),
            receiving_yards=("receiving_yards", "sum"),
            receiving_yac=("yards_after_catch", "sum"),
            receiving_air_yards=("air_yards", "sum"),
            receiving_epa=("epa", "sum"),
            receiving_tds=("pass_touchdown", "sum"),
        )
        .reset_index()
        .rename(columns={"receiver_player_id": "player_id"})
    )

    # ── Games played (union of all player roles) ──
    all_pids = pd.concat([
        reg[["passer_player_id", "week"]].rename(columns={"passer_player_id": "player_id"}),
        reg[["rusher_player_id", "week"]].rename(columns={"rusher_player_id": "player_id"}),
        reg[["receiver_player_id", "week"]].rename(columns={"receiver_player_id": "player_id"}),
    ]).dropna(subset=["player_id"])
    games_map = all_pids.groupby("player_id")["week"].nunique().reset_index().rename(columns={"week": "games"})

    # ── Team (most recent) ──
    team_map = pd.concat([
        reg[["passer_player_id", "posteam", "week"]].rename(columns={"passer_player_id": "player_id"}),
        reg[["rusher_player_id", "posteam", "week"]].rename(columns={"rusher_player_id": "player_id"}),
        reg[["receiver_player_id", "posteam", "week"]].rename(columns={"receiver_player_id": "player_id"}),
    ]).dropna(subset=["player_id"]).sort_values("week", ascending=False).drop_duplicates("player_id")[["player_id", "posteam"]]

    # ── Merge all stat tables onto a single player_id spine ──
    all_ids = pd.DataFrame({"player_id": list(
        set(pass_agg["player_id"]) | set(rush_agg["player_id"]) | set(rec_agg["player_id"])
    )})
    df = (
        all_ids
        .merge(pass_agg, on="player_id", how="left")
        .merge(rush_agg, on="player_id", how="left")
        .merge(rec_agg, on="player_id", how="left")
        .merge(games_map, on="player_id", how="left")
        .merge(team_map, on="player_id", how="left")
    )

    # Fill numeric nulls with 0
    num_cols = ["completions", "attempts", "passing_yards", "passing_tds", "interceptions",
                "passing_epa", "sacks", "carries", "rushing_yards", "rushing_tds",
                "rushing_epa", "targets", "receptions", "receiving_yards", "receiving_yac",
                "receiving_air_yards", "receiving_epa", "receiving_tds"]
    for col in num_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)

    df = df.rename(columns={"posteam": "recent_team"})

    # PPR fantasy points
    df["fantasy_points_ppr"] = (
        df["passing_yards"] * 0.04 +
        df["passing_tds"] * 4 +
        df["interceptions"] * -1 +
        df["rushing_yards"] * 0.1 +
        df["rushing_tds"] * 6 +
        df["receptions"] * 1 +
        df["receiving_yards"] * 0.1 +
        df["receiving_tds"] * 6
    )

    return df


def load_data():
    if _cache.get("players") is not None:
        return _cache

    seasons = [2025]

    # Roster for player names, positions, headshots
    roster = nfl.import_seasonal_rosters(seasons)
    roster = roster.sort_values("week", ascending=False).drop_duplicates("player_id")
    roster = roster[["player_id", "player_name", "position", "team", "headshot_url", "age", "years_exp", "college", "height", "weight"]]

    # Build season totals from play-by-play (nflverse pre-built files not yet available for 2025)
    pbp = nfl.import_pbp_data(seasons, downcast=False)
    agg = _agg_stats_from_pbp(pbp)

    # Attach roster info — roster is authoritative for name, position, headshot.
    # No suffix conflicts since _agg_stats_from_pbp no longer includes these columns.
    agg = agg.merge(
        roster[["player_id", "player_name", "position", "headshot_url"]],
        on="player_id", how="left"
    )
    agg = agg.rename(columns={"player_name": "player_display_name"})

    # NGS receiving (separation, cushion, YAC above expectation)
    ngs_rec = nfl.import_ngs_data("receiving", seasons)
    ngs_rec = ngs_rec[ngs_rec["week"] == 0]
    ngs_rec = ngs_rec[["player_gsis_id", "avg_cushion", "avg_separation", "avg_intended_air_yards", "avg_yac", "avg_expected_yac", "avg_yac_above_expectation", "catch_percentage"]]
    ngs_rec = ngs_rec.rename(columns={"player_gsis_id": "player_id"})

    # NGS passing
    ngs_pass = nfl.import_ngs_data("passing", seasons)
    ngs_pass = ngs_pass[ngs_pass["week"] == 0]
    pass_cols = [c for c in ["player_gsis_id", "avg_time_to_throw", "avg_completed_air_yards", "avg_intended_air_yards", "completion_percentage_above_expectation", "passer_rating", "avg_air_yards_differential"] if c in ngs_pass.columns]
    ngs_pass = ngs_pass[pass_cols].rename(columns={"player_gsis_id": "player_id", "avg_intended_air_yards": "pass_avg_intended_air_yards"})

    # NGS rushing
    ngs_rush = nfl.import_ngs_data("rushing", seasons)
    ngs_rush = ngs_rush[ngs_rush["week"] == 0]
    rush_cols = [c for c in ["player_gsis_id", "efficiency", "percent_attempts_gte_eight_defenders", "avg_time_to_los", "expected_rushing_yards", "rush_yards_over_expected_per_att"] if c in ngs_rush.columns]
    ngs_rush = ngs_rush[rush_cols].rename(columns={"player_gsis_id": "player_id"})

    # Store pbp in a local var — only write to _cache atomically at the end
    _pbp = pbp

    # Merge NGS on top of PBP aggregates
    df = agg.merge(ngs_rec, on="player_id", how="left")
    df = df.merge(ngs_pass, on="player_id", how="left")
    df = df.merge(ngs_rush, on="player_id", how="left")

    # Derived metrics — use where() to avoid object-dtype issues from replace()
    df["yards_per_carry"] = (df["rushing_yards"] / df["carries"].where(df["carries"] > 0)).round(2)
    df["yards_per_target"] = (df["receiving_yards"] / df["targets"].where(df["targets"] > 0)).round(2)
    df["air_yards_per_rec"] = (df["receiving_air_yards"] / df["receptions"].where(df["receptions"] > 0)).round(2)
    df["yac_per_rec"] = (df["receiving_yac"] / df["receptions"].where(df["receptions"] > 0)).round(2)
    df["completion_pct"] = (df["completions"] / df["attempts"].where(df["attempts"] > 0) * 100).round(1)
    df["td_int_ratio"] = (df["passing_tds"] / df["interceptions"].where(df["interceptions"] > 0)).round(2)

    # ── Advanced stats from PBP ──────────────────────────────────────────────
    reg = _pbp[_pbp["season_type"] == "REG"]

    # QB advanced: aDOT, deep/short/medium splits, scramble rate, red zone
    qb_adv = []
    for pid, grp in reg[reg["passer_player_id"].notna()].groupby("passer_player_id"):
        attempts = grp[grp["pass_attempt"] == 1]
        deep = attempts[attempts["air_yards"] >= 20]
        short = attempts[attempts["air_yards"] < 10]
        medium = attempts[(attempts["air_yards"] >= 10) & (attempts["air_yards"] < 20)]
        rz = attempts[attempts["yardline_100"] <= 20]
        dropbacks = len(attempts) + int(grp["sack"].sum())
        scrambles = int(grp["qb_scramble"].sum())
        qb_adv.append({
            "player_id": pid,
            "qb_adot": round(float(attempts["air_yards"].mean()), 2) if len(attempts) else None,
            "deep_att": int(len(deep)),
            "deep_comp_pct": round(float(deep["complete_pass"].mean() * 100), 1) if len(deep) else None,
            "short_comp_pct": round(float(short["complete_pass"].mean() * 100), 1) if len(short) else None,
            "medium_comp_pct": round(float(medium["complete_pass"].mean() * 100), 1) if len(medium) else None,
            "scramble_rate": round(scrambles / dropbacks * 100, 1) if dropbacks else None,
            "rz_attempts": int(len(rz)),
            "rz_td_rate": round(float(rz["pass_touchdown"].mean() * 100), 1) if len(rz) else None,
            "first_down_rate_pass": round(float(attempts["first_down_pass"].mean() * 100), 1) if len(attempts) else None,
        })
    qb_adv_df = pd.DataFrame(qb_adv)

    # WR/TE advanced: aDOT, air yards share, target share, WOPR, red zone targets, first down rate
    # Team totals for share calculations
    rec_plays_all = reg[reg["receiver_player_id"].notna()]
    team_air = rec_plays_all.groupby("posteam")["air_yards"].sum().reset_index()
    team_air.columns = ["posteam", "team_total_air_yards"]
    team_targets_map = rec_plays_all.groupby("posteam")["pass_attempt"].sum().reset_index()
    team_targets_map.columns = ["posteam", "team_total_targets"]

    rec_adv = []
    for pid, grp in rec_plays_all.groupby("receiver_player_id"):
        rz = grp[grp["yardline_100"] <= 20]
        team = grp["posteam"].mode()[0] if len(grp) else None
        t_air = team_air[team_air["posteam"] == team]["team_total_air_yards"].values
        t_tgts = team_targets_map[team_targets_map["posteam"] == team]["team_total_targets"].values
        player_air = float(grp["air_yards"].sum())
        player_targets = int(grp["pass_attempt"].sum())
        air_yds_share = round(player_air / t_air[0] * 100, 1) if len(t_air) and t_air[0] > 0 else None
        tgt_share = round(player_targets / t_tgts[0], 4) if len(t_tgts) and t_tgts[0] > 0 else None
        wopr = round(1.5 * tgt_share + 0.7 * (air_yds_share / 100), 3) if tgt_share is not None and air_yds_share is not None else None
        rec_adv.append({
            "player_id": pid,
            "adot": round(float(grp["air_yards"].mean()), 2) if grp["air_yards"].notna().any() else None,
            "air_yards_share": air_yds_share,
            "target_share": tgt_share,
            "wopr": wopr,
            "rz_targets": int(len(rz)),
            "rz_receptions": int(rz["complete_pass"].sum()),
            "first_down_rate_rec": round(float(grp["first_down_pass"].mean() * 100), 1) if len(grp) else None,
            "endzone_targets": int(grp[grp["yardline_100"] <= 10].shape[0]),
        })
    rec_adv_df = pd.DataFrame(rec_adv)

    # RB advanced: red zone carries, opportunity share, first down rate, long runs
    team_opportunities = reg.groupby("posteam").agg(
        team_carries=("rush_attempt", "sum"),
        team_targets=("pass_attempt", "sum"),
    ).reset_index()

    rush_adv = []
    for pid, grp in reg[reg["rusher_player_id"].notna() & reg["rush_attempt"].eq(1)].groupby("rusher_player_id"):
        rz = grp[grp["yardline_100"] <= 20]
        team = grp["posteam"].mode()[0] if len(grp) else None
        opp = team_opportunities[team_opportunities["posteam"] == team]
        rush_adv.append({
            "player_id": pid,
            "rz_carries": int(len(rz)),
            "rz_carry_td_rate": round(float(rz["rush_touchdown"].mean() * 100), 1) if len(rz) else None,
            "first_down_rate_rush": round(float(grp["first_down_rush"].mean() * 100), 1) if len(grp) else None,
            "long_rush": int(grp["rushing_yards"].max()) if len(grp) else None,
            "stuffed_rate": round(float((grp["rushing_yards"] <= 0).mean() * 100), 1),
            "ten_plus_rate": round(float((grp["rushing_yards"] >= 10).mean() * 100), 1),
        })
    rush_adv_df = pd.DataFrame(rush_adv)

    # Merge advanced stats
    df = df.merge(qb_adv_df, on="player_id", how="left")
    df = df.merge(rec_adv_df, on="player_id", how="left")
    df = df.merge(rush_adv_df, on="player_id", how="left")

    # Clean up any _x/_y suffix columns caused by overlapping merge keys
    # (shouldn't happen now since qb_adot is distinct from adot, but as safety net)
    for col in list(df.columns):
        if col.endswith("_x"):
            base = col[:-2]
            y_col = base + "_y"
            if y_col in df.columns:
                # Use whichever side has a value (prefer non-null)
                df[base] = df[col].combine_first(df[y_col])
                df = df.drop(columns=[col, y_col])
        elif col.endswith("_y") and col[:-2] not in df.columns:
            df = df.rename(columns={col: col[:-2]})

    # Filter to meaningful contributors only
    mask = (
        ((df["position"] == "QB") & (df["attempts"] >= 50)) |
        ((df["position"] == "RB") & (df["carries"] + df["targets"] >= 30)) |
        ((df["position"] == "WR") & (df["targets"] >= 20)) |
        ((df["position"] == "TE") & (df["targets"] >= 10))
    )
    df = df[mask].copy()

    # Write both keys atomically so no request sees a partial cache
    _cache["pbp"] = _pbp
    _cache["players"] = df
    return _cache


def player_to_dict(row):
    d = {}
    for k, v in row.items():
        if pd.isna(v) if not isinstance(v, str) else False:
            d[k] = None
        else:
            d[k] = v
    return d


# ── Scouting report cache ────────────────────────────────────────────────────
_reports: dict = {}

POSITION_PROMPTS = {
    "QB": """Focus on: completion % above expectation (CPOE), EPA under pressure vs clean pocket, time to throw, air yards differential, TD/INT ratio. Highlight clutch performance and decision-making.
Key stats to reference: completion_pct, passing_epa, completion_percentage_above_expectation, avg_time_to_throw, avg_completed_air_yards, td_int_ratio, interceptions.""",

    "WR": """Focus on: separation ability, route versatility (air yards vs YAC split tells you if they're a separator or YAC monster), target share, WOPR (combined air yards + target share dominance), catch percentage vs expectation.
Key stats to reference: avg_separation, avg_cushion, receiving_air_yards, yac_per_rec, avg_yac_above_expectation, target_share, wopr, receiving_epa.""",

    "RB": """Focus on: rushing efficiency (yards over expected), broken tackle potential (efficiency vs expected tells this story), receiving ability (receiving EPA, target share), pass protection implied by usage.
Key stats to reference: yards_per_carry, rushing_epa, rush_yards_over_expected_per_att, efficiency (NGS), receiving_yards, targets, receiving_epa.""",

    "TE": """Focus on: dual-threat value (blocking role implied by target rate vs snaps, receiving production), separation for a big man, YAC ability, red zone value (TD rate).
Key stats to reference: avg_separation, receiving_tds, receiving_epa, targets, yac_per_rec, air_yards_per_rec.""",
}


def build_scouting_prompt(player: dict) -> str:
    pos = player.get("position", "")
    name = player.get("player_display_name", "Unknown")
    team = player.get("recent_team", "")
    pos_guidance = POSITION_PROMPTS.get(pos, "Analyze all-around performance.")

    # Build a clean stats string, skipping nulls
    skip = {"player_id", "player_display_name", "position", "recent_team", "headshot_url", "position_group"}
    stats_lines = []
    for k, v in player.items():
        if k in skip or v is None:
            continue
        if isinstance(v, float):
            stats_lines.append(f"  {k}: {v:.2f}")
        else:
            stats_lines.append(f"  {k}: {v}")
    stats_str = "\n".join(stats_lines)

    return f"""You are an elite NFL scout writing a player evaluation for a professional analytics site.

Player: {name} | Position: {pos} | Team: {team}

2025 Season Stats:
{stats_str}

{pos_guidance}

Write exactly 3 concise paragraphs:
1. STRENGTHS — what this player does exceptionally well, citing specific numbers
2. LIMITATIONS — honest weaknesses or ceiling concerns
3. OUTLOOK — scheme fit, role, and what to watch next season

Be direct. Use specific stats. No filler phrases. Write like a scout who respects the reader's intelligence."""


# ── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/players")
def get_players(position: str = None, team: str = None, limit: int = 200):
    data = load_data()
    df = data["players"]

    if position and position != "ALL":
        df = df[df["position"] == position]
    if team:
        df = df[df["recent_team"] == team]

    df = df.sort_values("fantasy_points_ppr", ascending=False).head(limit)
    records = [player_to_dict(r) for _, r in df.iterrows()]
    return {"players": records, "count": len(records)}


@app.get("/api/players/{player_id}")
def get_player(player_id: str):
    data = load_data()
    df = data["players"]
    row = df[df["player_id"] == player_id]
    if row.empty:
        raise HTTPException(status_code=404, detail="Player not found")
    return player_to_dict(row.iloc[0])


@app.get("/api/players/{player_id}/scouting-report")
def get_scouting_report(player_id: str):
    if player_id in _reports:
        return _reports[player_id]

    data = load_data()
    df = data["players"]
    row = df[df["player_id"] == player_id]
    if row.empty:
        raise HTTPException(status_code=404, detail="Player not found")

    player = player_to_dict(row.iloc[0])

    if not claude:
        report = {
            "player_id": player_id,
            "name": player.get("player_display_name"),
            "position": player.get("position"),
            "report": "AI scouting reports require an ANTHROPIC_API_KEY environment variable.",
            "strengths": "",
            "limitations": "",
            "outlook": "",
        }
        return report

    prompt = build_scouting_prompt(player)
    message = claude.messages.create(
        model="claude-opus-4-8",
        max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    full_text = message.content[0].text

    # Split into paragraphs
    paragraphs = [p.strip() for p in full_text.strip().split("\n\n") if p.strip()]

    report = {
        "player_id": player_id,
        "name": player.get("player_display_name"),
        "position": player.get("position"),
        "report": full_text,
        "strengths": paragraphs[0] if len(paragraphs) > 0 else "",
        "limitations": paragraphs[1] if len(paragraphs) > 1 else "",
        "outlook": paragraphs[2] if len(paragraphs) > 2 else "",
    }
    _reports[player_id] = report
    return report


@app.get("/api/positions")
def get_positions():
    return ["QB", "WR", "RB", "TE"]


@app.get("/api/teams")
def get_teams():
    data = load_data()
    teams = sorted(data["players"]["recent_team"].dropna().unique().tolist())
    return teams


@app.get("/api/leaderboard")
def get_leaderboard(position: str, metric: str, limit: int = 25):
    data = load_data()
    df = data["players"]
    df = df[df["position"] == position]

    if metric not in df.columns:
        raise HTTPException(status_code=400, detail=f"Unknown metric: {metric}")

    df = df[df[metric].notna()].sort_values(metric, ascending=False).head(limit)
    return {
        "position": position,
        "metric": metric,
        "leaders": [player_to_dict(r) for _, r in df.iterrows()],
    }


@app.get("/api/players/{player_id}/routes")
def get_player_routes(player_id: str):
    """WR route tree breakdown: per-route targets, catches, yards, EPA, catch rate."""
    data = load_data()
    pbp = data.get("pbp")
    if pbp is None:
        raise HTTPException(status_code=503, detail="PBP data not loaded")

    reg = pbp[(pbp["season_type"] == "REG") & (pbp["receiver_player_id"] == player_id) & (pbp["route"].notna()) & (pbp["route"] != "")]

    if reg.empty:
        return {"routes": []}

    route_stats = reg.groupby("route").agg(
        targets=("pass_attempt", "sum"),
        receptions=("complete_pass", "sum"),
        yards=("receiving_yards", "sum"),
        epa=("epa", "sum"),
        air_yards=("air_yards", "sum"),
        yac=("yards_after_catch", "sum"),
        tds=("pass_touchdown", "sum"),
    ).reset_index()

    route_stats["catch_rate"] = (route_stats["receptions"] / route_stats["targets"].where(route_stats["targets"] > 0) * 100).round(1)
    route_stats["yards_per_target"] = (route_stats["yards"] / route_stats["targets"].where(route_stats["targets"] > 0)).round(1)
    route_stats["epa_per_target"] = (route_stats["epa"] / route_stats["targets"].where(route_stats["targets"] > 0)).round(2)
    route_stats = route_stats.sort_values("targets", ascending=False)

    return {"routes": route_stats.to_dict(orient="records")}


@app.get("/api/players/{player_id}/pressure")
def get_player_pressure(player_id: str):
    """QB performance under pressure vs clean pocket."""
    data = load_data()
    pbp = data.get("pbp")
    if pbp is None:
        raise HTTPException(status_code=503, detail="PBP data not loaded")

    reg = pbp[(pbp["season_type"] == "REG") & (pbp["passer_player_id"] == player_id) & (pbp["pass_attempt"] == 1)]

    if reg.empty:
        return {"pressure": None, "clean": None}

    def split_stats(df):
        comps = df["complete_pass"].sum()
        atts = len(df)
        yards = df["passing_yards"].sum()
        tds = df["pass_touchdown"].sum()
        ints = df["interception"].sum()
        epa = df["epa"].sum()
        return {
            "completions": int(comps),
            "attempts": int(atts),
            "comp_pct": round(comps / atts * 100, 1) if atts else None,
            "yards": round(float(yards), 0),
            "tds": int(tds),
            "ints": int(ints),
            "epa": round(float(epa), 2),
            "epa_per_att": round(float(epa) / atts, 3) if atts else None,
        }

    pressured = reg[reg["was_pressure"] == 1]
    clean = reg[reg["was_pressure"] == 0]

    return {
        "pressure": split_stats(pressured) if len(pressured) else None,
        "clean": split_stats(clean) if len(clean) else None,
        "total_attempts": int(len(reg)),
        "pressure_rate": round(len(pressured) / len(reg) * 100, 1) if len(reg) else None,
    }


@app.get("/api/players/{player_id}/rushing-detail")
def get_rushing_detail(player_id: str):
    """RB deep stats: gap distribution, down splits, yards after contact proxy."""
    data = load_data()
    pbp = data.get("pbp")
    if pbp is None:
        raise HTTPException(status_code=503, detail="PBP data not loaded")

    reg = pbp[(pbp["season_type"] == "REG") & (pbp["rusher_player_id"] == player_id) & (pbp["rush_attempt"] == 1)]

    if reg.empty:
        return {"run_gap": [], "down_splits": [], "yardage_bands": []}

    # Run gap breakdown
    if "run_gap" in reg.columns and "run_location" in reg.columns:
        reg["gap_label"] = reg["run_location"].fillna("?") + " " + reg["run_gap"].fillna("?")
        gap = reg.groupby("gap_label").agg(
            carries=("rush_attempt", "sum"),
            yards=("rushing_yards", "sum"),
            epa=("epa", "sum"),
            tds=("rush_touchdown", "sum"),
        ).reset_index()
        gap["ypc"] = (gap["yards"] / gap["carries"].where(gap["carries"] > 0)).round(2)
        gap = gap[gap["gap_label"].str.strip().ne("? ?")].sort_values("carries", ascending=False)
        gap_records = gap.to_dict(orient="records")
    else:
        gap_records = []

    # Down splits
    down_splits = []
    for down in [1, 2, 3]:
        d = reg[reg["down"] == down]
        if len(d):
            down_splits.append({
                "down": down,
                "carries": int(len(d)),
                "yards": float(d["rushing_yards"].sum()),
                "ypc": round(float(d["rushing_yards"].sum()) / len(d), 2),
                "epa": round(float(d["epa"].sum()), 2),
            })

    # Yardage bands (explosion plays)
    bands = [
        ("0 or less", reg["rushing_yards"] <= 0),
        ("1–3", (reg["rushing_yards"] > 0) & (reg["rushing_yards"] <= 3)),
        ("4–9", (reg["rushing_yards"] > 3) & (reg["rushing_yards"] <= 9)),
        ("10–19", (reg["rushing_yards"] > 9) & (reg["rushing_yards"] <= 19)),
        ("20+", reg["rushing_yards"] >= 20),
    ]
    yardage_bands = []
    total = len(reg)
    for label, mask in bands:
        cnt = int(mask.sum())
        yardage_bands.append({"band": label, "carries": cnt, "pct": round(cnt / total * 100, 1) if total else 0})

    return {"run_gap": gap_records, "down_splits": down_splits, "yardage_bands": yardage_bands}


@app.get("/api/players/{player_id}/sos")
def get_player_sos(player_id: str):
    """
    Schedule difficulty for a specific player — which defenses they faced and
    how those defenses ranked vs their position group.
    """
    data = load_data()
    pbp = data.get("pbp")
    if pbp is None:
        raise HTTPException(status_code=503, detail="PBP not loaded")

    # Get player's position
    players_df = data["players"]
    row = players_df[players_df["player_id"] == player_id]
    if row.empty:
        raise HTTPException(status_code=404, detail="Player not found")
    pos = row.iloc[0]["position"]

    # Get SOS rankings (compute if not cached)
    sos_data = data.get("sos")
    if not sos_data:
        # Trigger SOS computation inline
        from fastapi.testclient import TestClient
        pass  # will fall through to recompute below

    # Compute defensive rankings for this position if not already cached
    reg = pbp[pbp["season_type"] == "REG"]

    if not sos_data:
        # Recompute full SOS (same logic as /api/sos)
        pass

    # Get every week + defteam the player faced
    if pos == "QB":
        player_plays = reg[reg["passer_player_id"] == player_id][["week", "defteam"]].dropna()
    elif pos == "RB":
        player_plays = pd.concat([
            reg[reg["rusher_player_id"] == player_id][["week", "defteam"]],
            reg[reg["receiver_player_id"] == player_id][["week", "defteam"]],
        ]).dropna()
    else:
        player_plays = reg[reg["receiver_player_id"] == player_id][["week", "defteam"]].dropna()

    if player_plays.empty:
        return {"opponents": [], "avg_rank": None, "pos": pos}

    # One entry per week (some weeks player may have both rush and rec plays)
    player_weeks = player_plays.drop_duplicates("week").sort_values("week")

    # Get the defensive rankings for this position from /api/sos data
    if sos_data:
        pos_rankings = {r["defteam"]: r for r in sos_data["positions"].get(pos, [])}
    else:
        # Compute inline for this position
        if pos == "QB":
            pts_vs = reg[reg["passer_player_id"].notna()].copy()
            pts_vs["pts"] = pts_vs["passing_yards"] * 0.04 + pts_vs["pass_touchdown"] * 4 + pts_vs["interception"] * -1
            grp = pts_vs.groupby("defteam").agg(total=("pts", "sum")).reset_index()
        elif pos == "RB":
            rush_pts = reg[reg["rusher_player_id"].notna() & reg["rush_attempt"].eq(1)].copy()
            rush_pts["pts"] = rush_pts["rushing_yards"] * 0.1 + rush_pts["rush_touchdown"] * 6
            rec_pts = reg[reg["receiver_player_id"].notna()].copy()
            rec_pts = rec_pts.merge(
                players_df[["player_id", "position"]].rename(columns={"player_id": "receiver_player_id"}),
                on="receiver_player_id", how="left"
            )
            rec_pts = rec_pts[rec_pts["position"] == "RB"].copy()
            rec_pts["pts"] = rec_pts["complete_pass"] + rec_pts["receiving_yards"] * 0.1 + rec_pts["pass_touchdown"] * 6
            all_pts = pd.concat([
                rush_pts[["defteam", "pts"]],
                rec_pts[["defteam", "pts"]],
            ])
            grp = all_pts.groupby("defteam").agg(total=("pts", "sum")).reset_index()
        else:
            rec_pts = reg[reg["receiver_player_id"].notna()].copy()
            rec_pts = rec_pts.merge(
                players_df[["player_id", "position"]].rename(columns={"player_id": "receiver_player_id"}),
                on="receiver_player_id", how="left"
            )
            rec_pts = rec_pts[rec_pts["position"] == pos].copy()
            rec_pts["pts"] = rec_pts["complete_pass"] + rec_pts["receiving_yards"] * 0.1 + rec_pts["pass_touchdown"] * 6
            grp = rec_pts.groupby("defteam").agg(total=("pts", "sum")).reset_index()

        games_played = reg.groupby("defteam")["week"].nunique().reset_index().rename(columns={"week": "games"})
        grp = grp.merge(games_played, on="defteam", how="left")
        grp["pts_per_game"] = (grp["total"] / grp["games"].where(grp["games"] > 0)).round(1)
        grp = grp.sort_values("pts_per_game", ascending=False).reset_index(drop=True)
        grp["rank"] = grp.index + 1
        pos_rankings = {r["defteam"]: {"rank": r["rank"], "pts_per_game": r["pts_per_game"]} for _, r in grp.iterrows()}

    opponents = []
    for _, row in player_weeks.iterrows():
        team = row["defteam"]
        rank_info = pos_rankings.get(team, {})
        opponents.append({
            "week": int(row["week"]),
            "opponent": team,
            "def_rank": rank_info.get("rank"),
            "pts_per_game": rank_info.get("pts_per_game"),
        })

    ranks = [o["def_rank"] for o in opponents if o["def_rank"] is not None]
    avg_rank = round(sum(ranks) / len(ranks), 1) if ranks else None

    return {
        "player_id": player_id,
        "position": pos,
        "opponents": opponents,
        "avg_rank": avg_rank,
        "games": len(opponents),
    }


@app.get("/api/fantasy")
def get_fantasy(position: str = None, sort: str = "fantasy_points_ppr", limit: int = 300):
    """Fantasy rankings with PPR/standard/half-PPR points, PPG, floor, ceiling, consistency."""
    data = load_data()
    df = data["players"].copy()
    pbp = data.get("pbp")

    # Compute weekly fantasy scores per player from PBP
    if pbp is not None and "weekly_stats" not in data:
        reg = pbp[pbp["season_type"] == "REG"]

        # Weekly passing
        wp = reg[reg["passer_player_id"].notna()].groupby(["passer_player_id", "week"]).agg(
            pass_yds=("passing_yards", "sum"),
            pass_tds=("pass_touchdown", "sum"),
            ints=("interception", "sum"),
        ).reset_index().rename(columns={"passer_player_id": "player_id"})
        wp["weekly_ppr"] = wp["pass_yds"] * 0.04 + wp["pass_tds"] * 4 + wp["ints"] * -1

        # Weekly rushing
        wr = reg[reg["rusher_player_id"].notna() & reg["rush_attempt"].eq(1)].groupby(["rusher_player_id", "week"]).agg(
            rush_yds=("rushing_yards", "sum"),
            rush_tds=("rush_touchdown", "sum"),
        ).reset_index().rename(columns={"rusher_player_id": "player_id"})
        wr["weekly_ppr"] = wr["rush_yds"] * 0.1 + wr["rush_tds"] * 6

        # Weekly receiving
        wrec = reg[reg["receiver_player_id"].notna()].groupby(["receiver_player_id", "week"]).agg(
            rec=("complete_pass", "sum"),
            rec_yds=("receiving_yards", "sum"),
            rec_tds=("pass_touchdown", "sum"),
        ).reset_index().rename(columns={"receiver_player_id": "player_id"})
        wrec["weekly_ppr"] = wrec["rec"] * 1 + wrec["rec_yds"] * 0.1 + wrec["rec_tds"] * 6

        # Combine all weekly contributions per player per week
        all_w = pd.concat([
            wp[["player_id", "week", "weekly_ppr"]],
            wr[["player_id", "week", "weekly_ppr"]],
            wrec[["player_id", "week", "weekly_ppr"]],
        ])
        weekly = all_w.groupby(["player_id", "week"])["weekly_ppr"].sum().reset_index()
        weekly_stats = weekly.groupby("player_id")["weekly_ppr"].agg(
            ppg="mean",
            weekly_floor="min",
            weekly_ceiling="max",
            consistency="std",
        ).reset_index()
        weekly_stats = weekly_stats.round(1)
        data["weekly_stats"] = weekly_stats

    weekly_stats = data.get("weekly_stats")

    if position and position != "ALL":
        df = df[df["position"] == position]

    # Merge weekly stats
    if weekly_stats is not None:
        df = df.merge(weekly_stats, on="player_id", how="left")

    # Standard (non-PPR) points
    df["fantasy_points_std"] = (
        df["passing_yards"] * 0.04 +
        df["passing_tds"] * 4 +
        df["interceptions"] * -1 +
        df["rushing_yards"] * 0.1 +
        df["rushing_tds"] * 6 +
        df["receiving_yards"] * 0.1 +
        df["receiving_tds"] * 6
    ).round(1)

    df["fantasy_points_half"] = (df["fantasy_points_ppr"] + df["fantasy_points_std"]) / 2
    df["fantasy_points_half"] = df["fantasy_points_half"].round(1)

    valid_sorts = ["fantasy_points_ppr", "fantasy_points_std", "fantasy_points_half", "ppg", "weekly_ceiling", "weekly_floor"]
    if sort not in valid_sorts:
        sort = "fantasy_points_ppr"

    df = df[df[sort].notna()].sort_values(sort, ascending=False).head(limit)
    return {"players": [player_to_dict(r) for _, r in df.iterrows()], "count": len(df)}


@app.get("/api/sos")
def get_strength_of_schedule():
    """
    Defensive rankings by position — how many PPR fantasy pts each team allowed
    per game to each skill position. Rank 1 = most generous (easiest matchup).
    """
    data = load_data()
    if "sos" in data:
        return data["sos"]

    pbp = data.get("pbp")
    if pbp is None:
        raise HTTPException(status_code=503, detail="PBP not loaded")

    reg = pbp[pbp["season_type"] == "REG"]

    # Compute PPR pts scored BY each player AGAINST each defense (defteam)
    # Passing pts scored against defense
    pass_vs = reg[reg["passer_player_id"].notna()].groupby(["defteam", "week"]).agg(
        pass_pts=("passing_yards", lambda x: x.sum() * 0.04),
        pass_tds=("pass_touchdown", "sum"),
        ints=("interception", "sum"),
    ).reset_index()
    pass_vs["pts"] = pass_vs["pass_pts"] + pass_vs["pass_tds"] * 4 + pass_vs["ints"] * -1

    rush_vs = reg[reg["rusher_player_id"].notna() & reg["rush_attempt"].eq(1)].groupby(["defteam", "week"]).agg(
        rush_pts=("rushing_yards", lambda x: x.sum() * 0.1),
        rush_tds=("rush_touchdown", "sum"),
    ).reset_index()
    rush_vs["pts"] = rush_vs["rush_pts"] + rush_vs["rush_tds"] * 6

    rec_vs = reg[reg["receiver_player_id"].notna()].groupby(["defteam", "week", "passer_player_id"]).agg(
        rec=("complete_pass", "sum"),
        rec_yds=("receiving_yards", "sum"),
        rec_tds=("pass_touchdown", "sum"),
    ).reset_index()
    rec_vs["pts"] = rec_vs["rec"] * 1 + rec_vs["rec_yds"] * 0.1 + rec_vs["rec_tds"] * 6

    # We need position-specific: join receiver_player_id → position
    players_df = data["players"][["player_id", "position"]].copy()

    # Receiving pts by position against defense
    rec_full = reg[reg["receiver_player_id"].notna()].merge(
        players_df.rename(columns={"player_id": "receiver_player_id"}),
        on="receiver_player_id", how="left"
    )
    rec_full["rec_pts"] = rec_full["complete_pass"] * 1 + rec_full["receiving_yards"].fillna(0) * 0.1 + rec_full["pass_touchdown"].fillna(0) * 6

    pos_allowed = {}
    for pos in ["QB", "WR", "RB", "TE"]:
        if pos == "QB":
            # QB pts = passing pts given up
            grp = pass_vs.groupby("defteam")["pts"].agg(total="sum", games="count").reset_index()
        else:
            pos_rec = rec_full[rec_full["position"] == pos]
            if pos == "RB":
                # RB = rushing pts + receiving pts
                rush_grp = rush_vs.groupby("defteam")["pts"].agg(rush_total="sum", games="count").reset_index()
                rec_grp = pos_rec.groupby("defteam")["rec_pts"].sum().reset_index().rename(columns={"rec_pts": "rec_total"})
                grp = rush_grp.merge(rec_grp, on="defteam", how="outer").fillna(0)
                grp["total"] = grp["rush_total"] + grp["rec_total"]
            else:
                grp = pos_rec.groupby("defteam")["rec_pts"].agg(total="sum").reset_index()
                # games = weeks the defense played
                games_played = reg.groupby("defteam")["week"].nunique().reset_index().rename(columns={"week": "games"})
                grp = grp.merge(games_played, on="defteam", how="left")

        if "games" not in grp.columns:
            games_played = reg.groupby("defteam")["week"].nunique().reset_index().rename(columns={"week": "games"})
            grp = grp.merge(games_played, on="defteam", how="left")

        grp["pts_per_game"] = (grp["total"] / grp["games"].where(grp["games"] > 0)).round(1)
        grp = grp.sort_values("pts_per_game", ascending=False).reset_index(drop=True)
        grp["rank"] = grp.index + 1  # rank 1 = most pts allowed (easiest)
        pos_allowed[pos] = grp[["defteam", "pts_per_game", "rank"]].to_dict(orient="records")

    result = {"positions": pos_allowed}
    data["sos"] = result
    return result


@app.get("/api/sos/playoff")
def get_playoff_sos():
    """
    For each team, return their weeks 14-17 opponents and the opponent's defensive rank
    per position. Useful for fantasy playoff planning.
    """
    data = load_data()
    sos_data = get_strength_of_schedule()

    schedules = nfl.import_schedules([2025])
    playoff_weeks = schedules[schedules["week"].between(14, 17) & (schedules["game_type"] == "REG")]

    # Build lookup: team -> list of {week, opponent, ranks}
    team_schedule: dict = {}
    for _, game in playoff_weeks.iterrows():
        week = int(game["week"])
        home, away = game["home_team"], game["away_team"]
        for team, opp in [(home, away), (away, home)]:
            if team not in team_schedule:
                team_schedule[team] = []
            opp_ranks = {}
            for pos in ["QB", "WR", "RB", "TE"]:
                rankings = {r["defteam"]: r for r in sos_data["positions"].get(pos, [])}
                r = rankings.get(opp)
                opp_ranks[pos] = {"rank": r["rank"] if r else None, "pts_per_game": r["pts_per_game"] if r else None}
            team_schedule[team].append({"week": week, "opponent": opp, "def_ranks": opp_ranks})

    # Sort each team's games by week
    for team in team_schedule:
        team_schedule[team].sort(key=lambda x: x["week"])

    return {"teams": team_schedule}


@app.get("/api/players/{player_id}/sos")
def get_player_sos(player_id: str):
    """Per-player schedule difficulty: opponent defensive rank vs their position each week."""
    data = load_data()
    pbp = data.get("pbp")
    if pbp is None:
        raise HTTPException(status_code=503, detail="PBP not loaded")

    # Get player position
    players_df = data["players"]
    row = players_df[players_df["player_id"] == player_id]
    if row.empty:
        raise HTTPException(status_code=404, detail="Player not found")
    pos = row.iloc[0]["position"]

    # Load SOS defensive rankings (triggers computation if not cached)
    sos_data = get_strength_of_schedule()
    pos_rankings = {r["defteam"]: r for r in sos_data["positions"].get(pos, [])}

    reg = pbp[pbp["season_type"] == "REG"]

    # Get all weeks and opponents for this player
    if pos == "QB":
        player_plays = reg[reg["passer_player_id"] == player_id][["week", "defteam"]].dropna()
    elif pos == "RB":
        player_plays = pd.concat([
            reg[reg["rusher_player_id"] == player_id][["week", "defteam"]],
            reg[reg["receiver_player_id"] == player_id][["week", "defteam"]],
        ]).dropna()
    else:  # WR, TE
        player_plays = reg[reg["receiver_player_id"] == player_id][["week", "defteam"]].dropna()

    if player_plays.empty:
        return {"weeks": [], "avg_rank": None, "easiest": None, "hardest": None}

    weekly_opp = player_plays.groupby("week")["defteam"].first().reset_index()

    weeks_out = []
    for _, wrow in weekly_opp.sort_values("week").iterrows():
        opp = wrow["defteam"]
        rank_data = pos_rankings.get(opp, {})
        weeks_out.append({
            "week": int(wrow["week"]),
            "opponent": opp,
            "def_rank": rank_data.get("rank"),
            "pts_per_game": rank_data.get("pts_per_game"),
        })

    ranks = [w["def_rank"] for w in weeks_out if w["def_rank"] is not None]
    avg_rank = round(sum(ranks) / len(ranks), 1) if ranks else None

    easiest = min(weeks_out, key=lambda w: w["def_rank"] or 99, default=None)
    hardest = max(weeks_out, key=lambda w: w["def_rank"] or 0, default=None)

    return {
        "position": pos,
        "weeks": weeks_out,
        "avg_rank": avg_rank,
        "easiest": easiest,
        "hardest": hardest,
        "total_weeks": len(weeks_out),
    }


_dynasty_cache: dict = {}

@app.get("/api/dynasty-adp")
def get_dynasty_adp():
    """Dynasty startup rankings from FantasyCalc (overall rank, position rank, dynasty value, tier, trend)."""
    import time
    import httpx

    if _dynasty_cache.get("data") and time.time() - _dynasty_cache.get("ts", 0) < 86400:
        return _dynasty_cache["data"]

    try:
        url = "https://api.fantasycalc.com/values/current?isDynasty=true&numQbs=1"
        resp = httpx.get(url, timeout=10, headers={"User-Agent": "GridIron/1.0"})
        resp.raise_for_status()
        fc_data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FantasyCalc unavailable: {e}")

    data = load_data()
    players_df = data["players"]

    # Build name→player_id lookup — exact normalised full name only, no fuzzy fallback
    def norm_name(n):
        return n.lower().replace("'", "").replace(".", "").replace("-", "").replace(" ", "") if n else ""

    name_map = {norm_name(r["player_display_name"]): r["player_id"]
                for _, r in players_df.iterrows() if r.get("player_display_name")}

    # Team abbreviation harmonisation (FantasyCalc uses LAR, our data uses LA)
    TEAM_FIX = {"LAR": "LA", "JAC": "JAX", "LVR": "LV"}

    results = []
    for entry in fc_data:
        p = entry["player"]
        fc_name = norm_name(p.get("name", ""))
        pid = name_map.get(fc_name)  # exact match only — no fuzzy fallback

        team = TEAM_FIX.get(p.get("maybeTeam", ""), p.get("maybeTeam", ""))
        results.append({
            "player_id": pid,
            "name": p.get("name"),
            "position": p.get("position"),
            "team": team,
            "dynasty_rank": entry.get("overallRank"),
            "dynasty_pos_rank": entry.get("positionRank"),
            "dynasty_value": entry.get("value"),
            "dynasty_tier": entry.get("maybeTier"),
            "dynasty_trend": entry.get("trend30Day"),
            "age": p.get("maybeAge"),
        })

    _dynasty_cache["data"] = {"players": results, "count": len(results)}
    _dynasty_cache["ts"] = time.time()
    return _dynasty_cache["data"]


_redraft_cache: dict = {}

@app.get("/api/redraft-adp")
def get_redraft_adp():
    """Redraft rankings from FantasyCalc (overall rank, position rank, value)."""
    import time
    import httpx

    if _redraft_cache.get("data") and time.time() - _redraft_cache.get("ts", 0) < 86400:
        return _redraft_cache["data"]

    try:
        url = "https://api.fantasycalc.com/values/current?isDynasty=false&numQbs=1"
        resp = httpx.get(url, timeout=10, headers={"User-Agent": "GridIron/1.0"})
        resp.raise_for_status()
        fc_data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FantasyCalc unavailable: {e}")

    data = load_data()
    players_df = data["players"]

    def norm_name(n):
        return n.lower().replace("'", "").replace(".", "").replace("-", "").replace(" ", "") if n else ""

    name_map = {norm_name(r["player_display_name"]): r["player_id"]
                for _, r in players_df.iterrows() if r.get("player_display_name")}

    TEAM_FIX = {"LAR": "LA", "JAC": "JAX", "LVR": "LV"}

    results = []
    for entry in fc_data:
        p = entry["player"]
        fc_name = norm_name(p.get("name", ""))
        pid = name_map.get(fc_name)
        team = TEAM_FIX.get(p.get("maybeTeam", ""), p.get("maybeTeam", ""))
        results.append({
            "player_id": pid,
            "name": p.get("name"),
            "position": p.get("position"),
            "team": team,
            "redraft_rank": entry.get("overallRank"),
            "redraft_pos_rank": entry.get("positionRank"),
            "redraft_value": entry.get("value"),
            "age": p.get("maybeAge"),
        })

    _redraft_cache["data"] = {"players": results, "count": len(results)}
    _redraft_cache["ts"] = time.time()
    return _redraft_cache["data"]


@app.get("/api/value-picks")
def get_value_picks():
    """
    Value picks: players who overperformed their pre-season redraft ADP in 2025.
    Uses a static pre-season ADP snapshot (FantasyPros PPR, scraped ~Sep 1 2025)
    so post-season repricing doesn't contaminate the signal.
    """
    import math, os, json as _json

    # Load pre-season ADP snapshot (static file, not live API)
    adp_file = os.path.join(os.path.dirname(__file__), "data_2025_preseason_adp.json")
    with open(adp_file) as f:
        adp_snapshot = _json.load(f)

    perf_data = load_data()
    players_df = perf_data["players"]

    # Name normalisation for fuzzy matching
    def norm(n):
        return (n or "").lower().replace("'", "").replace(".", "").replace("-", "").replace(" ", "")

    name_to_pid = {norm(r["player_display_name"]): r["player_id"]
                   for _, r in players_df.iterrows() if r.get("player_display_name")}
    headshot_map = {r["player_id"]: r.get("headshot_url") for _, r in players_df.iterrows()}

    ppg_map = {}
    games_map = {}
    team_map = {}
    for _, r in players_df.iterrows():
        pid = r["player_id"]
        games = r.get("games") or 0
        fpts = r.get("fantasy_points_ppr")
        games_map[pid] = games
        team_map[pid] = r.get("recent_team", "")
        if fpts is not None and games > 0:
            ppg_map[pid] = round(float(fpts) / float(games), 2)

    VALID = {"QB", "WR", "RB", "TE"}
    TEAM_FIX = {"LAR": "LA", "JAC": "JAX", "LVR": "LV"}

    from collections import defaultdict
    by_pos = defaultdict(list)
    for entry in adp_snapshot["players"]:
        if entry["position"] not in VALID:
            continue
        pid = name_to_pid.get(norm(entry["name"]))
        if not pid:
            continue
        ppg = ppg_map.get(pid)
        games = games_map.get(pid, 0)
        # Exclude players who were essentially undrafted (overall ADP > 250 ≈ ~20 rounds)
        # and short-season contributors (<8 games) to keep the pool meaningful
        if ppg is None or games < 8 or entry.get("overall_adp", 999) > 250:
            continue
        # Weighted PPG = PPG × (games played / 17) — rewards both efficiency and availability
        weighted_ppg = round(ppg * (games / 17), 2)
        team = TEAM_FIX.get(entry["team"], entry["team"])
        by_pos[entry["position"]].append({
            "player_id": pid,
            "name": entry["name"],
            "position": entry["position"],
            "team": team,
            "redraft_pos_rank": entry["pos_adp_rank"],
            "overall_adp": entry["overall_adp"],
            "ppg": ppg,
            "games": games,
            "weighted_ppg": weighted_ppg,
        })

    results = []
    for pos, group in by_pos.items():
        # Rank by weighted PPG (PPG × games/17) so availability is factored in
        sorted_by_perf = sorted(group, key=lambda x: x["weighted_ppg"], reverse=True)
        for perf_rank, player in enumerate(sorted_by_perf, 1):
            adp_rank = player["redraft_pos_rank"]
            raw_value = adp_rank - perf_rank
            player["performance_rank"] = perf_rank
            player["raw_value"] = raw_value
            results.append(player)

    for pos in VALID:
        pos_players = [r for r in results if r["position"] == pos]
        if not pos_players:
            continue
        vals = [r["raw_value"] for r in pos_players]
        mean = sum(vals) / len(vals)
        std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)) or 1
        for r in pos_players:
            z = (r["raw_value"] - mean) / std
            r["value_score"] = round(min(100, max(0, 50 + z * 15)), 1)

    results.sort(key=lambda x: x.get("value_score", 0), reverse=True)

    headshot_map = {r["player_id"]: r.get("headshot_url") for _, r in players_df.iterrows()}
    for r in results:
        r["headshot_url"] = headshot_map.get(r["player_id"])

    return {"picks": results[:50]}


@app.get("/api/dynasty-value-picks")
def get_dynasty_value_picks():
    """
    Value picks: players who overperformed their dynasty positional rank in 2025.

    Algorithm:
    1. Merge dynasty pos rank (ADP proxy) with actual 2025 PPG.
    2. Within each position, rank players by actual PPG → performance_rank.
    3. value_score = dynasty_pos_rank - performance_rank
       (positive = outperformed their draft slot, e.g. ranked 20th but played like a 5th)
    4. Normalise to a 0-100 "value score" using z-score within position.
    """
    import math

    dynasty_data = get_dynasty_adp()
    perf_data = load_data()
    players_df = perf_data["players"]

    # Build ppg lookup: player_id → ppg (computed from fantasy_points_ppr / games)
    ppg_map = {}
    games_map = {}
    for _, r in players_df.iterrows():
        pid = r["player_id"]
        games = r.get("games") or 0
        fpts = r.get("fantasy_points_ppr")
        games_map[pid] = games
        if fpts is not None and games > 0:
            ppg_map[pid] = round(float(fpts) / float(games), 2)

    VALID = {"QB", "WR", "RB", "TE"}
    entries = [d for d in dynasty_data["players"] if d.get("position") in VALID and d.get("dynasty_pos_rank") and d.get("player_id")]

    # For each position, collect (player, dynasty_pos_rank, ppg) then rank by ppg
    from collections import defaultdict
    by_pos = defaultdict(list)
    for e in entries:
        ppg = ppg_map.get(e["player_id"])
        games = games_map.get(e["player_id"], 0)
        if ppg is None or (games_map.get(e["player_id"]) or 0) < 4:
            continue
        by_pos[e["position"]].append({**e, "ppg": ppg, "games": games})

    results = []
    for pos, group in by_pos.items():
        # Rank by actual PPG (best = rank 1)
        sorted_by_ppg = sorted(group, key=lambda x: x["ppg"], reverse=True)
        for perf_rank, player in enumerate(sorted_by_ppg, 1):
            adp_rank = player["dynasty_pos_rank"]
            raw_value = adp_rank - perf_rank  # positive = overperformed
            player["performance_rank"] = perf_rank
            player["raw_value"] = raw_value
            results.append(player)

    # Normalise raw_value within each position to a 0-100 value_score
    for pos in VALID:
        pos_players = [r for r in results if r["position"] == pos]
        if not pos_players:
            continue
        vals = [r["raw_value"] for r in pos_players]
        mean = sum(vals) / len(vals)
        std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)) or 1
        for r in pos_players:
            z = (r["raw_value"] - mean) / std
            r["value_score"] = round(min(100, max(0, 50 + z * 15)), 1)

    results.sort(key=lambda x: x.get("value_score", 0), reverse=True)

    # Attach headshot and team from players_df
    headshot_map = {r["player_id"]: r.get("headshot_url") for _, r in players_df.iterrows()}
    for r in results:
        r["headshot_url"] = headshot_map.get(r["player_id"])

    return {"picks": results[:50]}


@app.get("/api/value-picks/predictions")
def get_value_picks_predictions(position: str = None):
    """
    ML-predicted 2026 fantasy value picks.

    Returns the top 50 players sorted by predicted_value_score (descending).
    The score is z-score normalized 0-100 per position, where higher = more likely
    to outperform their pre-season ADP in 2026.

    Optional query param: ?position=WR  (QB|WR|RB|TE)
    """
    import os as _os
    import json as _json
    pred_file = _os.path.join(_os.path.dirname(__file__), "ml", "predictions_2026.json")
    if not _os.path.exists(pred_file):
        raise HTTPException(status_code=503, detail="Predictions not generated yet. Run ml/train_pipeline.py.")

    with open(pred_file) as f:
        data = _json.load(f)

    players = data.get("players", [])

    if position and position.upper() != "ALL":
        players = [p for p in players if p.get("position", "").upper() == position.upper()]

    # Already sorted by predicted_value_score desc
    top50 = players[:50]

    # Try to attach headshot_url from current player data
    try:
        cache = load_data()
        players_df = cache["players"]
        headshot_map = {r["player_id"]: r.get("headshot_url") for _, r in players_df.iterrows()}
        name_headshot = {
            (r["player_display_name"] or "").lower().replace("'", "").replace(".", "").replace("-", "").replace(" ", ""): r.get("headshot_url")
            for _, r in players_df.iterrows() if r.get("player_display_name")
        }
        for p in top50:
            pid = p.get("player_id", "")
            name_n = (p.get("name", "") or "").lower().replace("'", "").replace(".", "").replace("-", "").replace(" ", "")
            p["headshot_url"] = headshot_map.get(pid) or name_headshot.get(name_n)
    except Exception:
        pass

    return {
        "generated": data.get("generated"),
        "count": len(top50),
        "predictions": top50,
    }


# ── Sleeper League Integration ───────────────────────────────────────────────

_sleeper_cache: dict = {}

def _norm(n):
    return (n or "").lower().replace("'","").replace(".","").replace("-","").replace(" ","")

def _load_pred_maps():
    """Load ML predictions indexed by player_id and by norm(name)."""
    import json as _json, os as _os
    pred_file = _os.path.join(_os.path.dirname(__file__), "ml", "predictions_2026.json")
    pred_map = {}
    pred_name_map = {}
    try:
        with open(pred_file) as f:
            preds = _json.load(f)["players"]
        pred_map = {p["player_id"]: p for p in preds if p.get("player_id")}
        pred_name_map = {_norm(p["name"]): p for p in preds}
    except Exception:
        pass
    return pred_map, pred_name_map

def _load_dynasty_map():
    """Return dynasty values indexed by norm(name)."""
    try:
        dyn = get_dynasty_adp()
        return {_norm(p["name"]): p for p in dyn["players"]}
    except Exception:
        return {}

def _make_resolve_player(all_players, players_df, stat_map, pred_map, pred_name_map, dynasty_name_map):
    """Factory that returns a resolve_player closure with the given lookups."""
    def resolve_player(sleeper_id: str):
        sp = all_players.get(sleeper_id, {})
        name = sp.get("full_name") or sp.get("search_full_name", "")
        pos  = sp.get("position", "")
        team = sp.get("team", "")
        gsis = sp.get("gsis_id") or ""

        # Match to our stats via gsis_id or name — always resolve to a plain dict
        stats = stat_map.get(gsis)
        if stats is None and name:
            norm_name = _norm(name)
            match = next((r for _, r in players_df.iterrows() if _norm(r.get("player_display_name","")) == norm_name), None)
            stats = dict(match) if match is not None else {}
        elif stats is not None:
            stats = dict(stats)
        else:
            stats = {}

        pred = pred_map.get(gsis) or pred_name_map.get(_norm(name), {})
        dyn  = dynasty_name_map.get(_norm(name), {})

        ppg = None
        weighted_ppg = None
        games = None
        if stats:
            fpts = stats.get("fantasy_points_ppr")
            g    = stats.get("games") or 0
            if fpts and g:
                ppg = round(float(fpts) / float(g), 1)
                weighted_ppg = round(ppg * (g / 17), 1)
            games = int(g)

        return {
            "sleeper_id": sleeper_id,
            "player_id": gsis,
            "name": name or sleeper_id,
            "position": pos,
            "team": team,
            "age": sp.get("age"),
            "years_exp": sp.get("years_exp"),
            "headshot_url": f"https://sleepercdn.com/content/nfl/players/thumb/{sleeper_id}.jpg",
            # 2025 actual stats
            "ppg_2025": ppg,
            "weighted_ppg_2025": weighted_ppg,
            "games_2025": games,
            "fantasy_points_2025": round(float(stats.get("fantasy_points_ppr", 0) or 0), 1) if stats else None,
            # 2026 ML prediction
            "predicted_value_score_2026": pred.get("predicted_value_score"),
            "is_top_dog": pred.get("is_top_dog"),
            "adp_gap_to_teammate": pred.get("adp_gap_to_teammate"),
            # Dynasty values
            "dynasty_value": dyn.get("dynasty_value"),
            "dynasty_rank": dyn.get("dynasty_rank"),
            "dynasty_pos_rank": dyn.get("dynasty_pos_rank"),
            "dynasty_tier": dyn.get("dynasty_tier"),
        }
    return resolve_player


@app.get("/api/sleeper/leagues")
def get_sleeper_leagues(username: str):
    """Fetch NFL leagues for a Sleeper username (tries 2026 first, falls back to 2025)."""
    import time, httpx

    cache_key = f"leagues_{username}"
    if _sleeper_cache.get(cache_key) and time.time() - _sleeper_cache.get(f"{cache_key}_ts", 0) < 3600:
        return _sleeper_cache[cache_key]

    try:
        with httpx.Client(timeout=10) as client:
            user_r = client.get(f"https://api.sleeper.app/v1/user/{username}")
            user_r.raise_for_status()
            user_data = user_r.json()
            user_id = user_data["user_id"]

            leagues_r = client.get(f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/2026")
            leagues = leagues_r.json() or []
            if not leagues:
                leagues_r = client.get(f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/2025")
                leagues = leagues_r.json() or []
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sleeper API unavailable: {e}")

    results = []
    for lg in leagues:
        results.append({
            "league_id": lg.get("league_id"),
            "name": lg.get("name"),
            "season": lg.get("season"),
            "status": lg.get("status"),
            "num_teams": lg.get("total_rosters"),
            "avatar": lg.get("avatar"),
        })

    result = {"leagues": results, "user_id": user_id, "username": username}
    _sleeper_cache[cache_key] = result
    _sleeper_cache[f"{cache_key}_ts"] = time.time()
    return result


@app.get("/api/sleeper/league/{league_id}")
def get_sleeper_league(league_id: str, username: str = ""):
    """Full league data: standings + enriched rosters with stats/dynasty values/ML predictions."""
    import time, httpx

    cache_key = f"league_{league_id}"
    if _sleeper_cache.get(cache_key) and time.time() - _sleeper_cache.get(f"{cache_key}_ts", 0) < 3600:
        cached = _sleeper_cache[cache_key]
        # Re-flag is_me if username provided
        if username:
            _flag_is_me(cached, username)
        return cached

    try:
        with httpx.Client(timeout=15) as client:
            league_r  = client.get(f"https://api.sleeper.app/v1/league/{league_id}")
            rosters_r = client.get(f"https://api.sleeper.app/v1/league/{league_id}/rosters")
            users_r   = client.get(f"https://api.sleeper.app/v1/league/{league_id}/users")
            players_r = client.get("https://api.sleeper.app/v1/players/nfl")

        league_data = league_r.json()
        rosters     = rosters_r.json()
        users       = users_r.json()
        all_players = players_r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sleeper API unavailable: {e}")

    user_map = {
        u["user_id"]: {
            "name": u["display_name"],
            "avatar": u.get("metadata", {}).get("avatar") or u.get("avatar"),
            "username": u.get("display_name", "").lower(),
        }
        for u in users
    }
    # Build username → user_id map for is_me detection
    username_to_uid = {u["display_name"].lower(): u["user_id"] for u in users}

    data = load_data()
    players_df = data["players"]
    stat_map = {str(r["player_id"]): dict(r) for _, r in players_df.iterrows()}

    pred_map, pred_name_map = _load_pred_maps()
    dynasty_name_map = _load_dynasty_map()

    resolve_player = _make_resolve_player(all_players, players_df, stat_map, pred_map, pred_name_map, dynasty_name_map)

    standings = []
    for r in rosters:
        owner_id = r.get("owner_id", "")
        user_info = user_map.get(owner_id, {"name": "Unknown", "avatar": None, "username": ""})
        s = r.get("settings", {})
        players_resolved = [resolve_player(pid) for pid in (r.get("players") or [])]
        taxi_resolved    = [resolve_player(pid) for pid in (r.get("taxi") or [])]

        standings.append({
            "roster_id": r["roster_id"],
            "owner_id": owner_id,
            "display_name": user_info["name"],
            "avatar": user_info["avatar"],
            "wins": s.get("wins", 0),
            "losses": s.get("losses", 0),
            "ties": s.get("ties", 0),
            "fpts": round((s.get("fpts", 0) or 0) + (s.get("fpts_decimal", 0) or 0) / 100, 2),
            "fpts_against": round((s.get("fpts_against", 0) or 0) + (s.get("fpts_against_decimal", 0) or 0) / 100, 2),
            "players": players_resolved,
            "taxi": taxi_resolved,
            "is_me": False,  # will be set below
        })

    standings.sort(key=lambda x: (-x["wins"], -x["fpts"]))

    result = {
        "league_name": league_data.get("name"),
        "season": league_data.get("season"),
        "num_teams": league_data.get("total_rosters"),
        "status": league_data.get("status"),
        "standings": standings,
        "_username_to_uid": username_to_uid,
    }

    if username:
        _flag_is_me(result, username)

    _sleeper_cache[cache_key] = result
    _sleeper_cache[f"{cache_key}_ts"] = time.time()
    return result


def _flag_is_me(league_result: dict, username: str):
    """Set is_me=True on the roster belonging to username."""
    uid_map = league_result.get("_username_to_uid", {})
    my_uid = uid_map.get(username.lower())
    for team in league_result.get("standings", []):
        team["is_me"] = (team["owner_id"] == my_uid) if my_uid else False


@app.get("/api/sleeper/my-team")
def get_my_team():
    """Legacy endpoint — Harvin's roster from 2026 Dynasty Men."""
    league = get_sleeper_league("1312156205287747584", username="HarvinB")
    my_roster = next((s for s in league["standings"] if s["is_me"]), None)
    if not my_roster:
        raise HTTPException(status_code=404, detail="Roster not found")
    return {**my_roster, "league_name": league["league_name"], "season": league["season"]}


@app.get("/api/dynasty/positional-rankings")
def get_dynasty_positional_rankings(position: str = "ALL"):
    """
    Dynasty positional rankings: merge FantasyCalc values + our stats + ML predictions.
    Sorted by dynasty_value descending.
    """
    import time

    cache_key = f"pos_rankings_{position}"
    if _sleeper_cache.get(cache_key) and time.time() - _sleeper_cache.get(f"{cache_key}_ts", 0) < 3600:
        return _sleeper_cache[cache_key]

    dyn_data = get_dynasty_adp()
    dyn_players = dyn_data["players"]

    data = load_data()
    players_df = data["players"]
    stat_map = {str(r["player_id"]): dict(r) for _, r in players_df.iterrows()}
    name_stat_map = {_norm(r["player_display_name"]): dict(r) for _, r in players_df.iterrows() if r.get("player_display_name")}

    pred_map, pred_name_map = _load_pred_maps()

    TIERS = [
        (8000, "Elite"),
        (6000, "S-Tier"),
        (4000, "A-Tier"),
        (2000, "B-Tier"),
        (1000, "C-Tier"),
        (0,    "D-Tier"),
    ]

    def dynasty_tier(value):
        if value is None:
            return "D-Tier"
        for threshold, label in TIERS:
            if value >= threshold:
                return label
        return "D-Tier"

    VALID_POSITIONS = {"QB", "WR", "RB", "TE"}

    results = []
    for i, dp in enumerate(dyn_players):
        pos = dp.get("position", "")
        if pos not in VALID_POSITIONS:
            continue
        if position != "ALL" and pos != position:
            continue

        name = dp.get("name", "")
        pid  = dp.get("player_id") or ""
        dval = dp.get("dynasty_value")

        # Stat lookup
        stats = stat_map.get(pid) or name_stat_map.get(_norm(name), {})
        ppg = None
        weighted_ppg = None
        if stats:
            fpts = stats.get("fantasy_points_ppr")
            g    = stats.get("games") or 0
            if fpts and g:
                ppg = round(float(fpts) / float(g), 1)
                weighted_ppg = round(ppg * (g / 17), 1)

        pred = pred_map.get(pid) or pred_name_map.get(_norm(name), {})

        results.append({
            "player_id": pid,
            "name": name,
            "position": pos,
            "team": dp.get("team"),
            "age": dp.get("age"),
            "dynasty_rank": dp.get("dynasty_rank"),
            "dynasty_pos_rank": dp.get("dynasty_pos_rank"),
            "dynasty_value": dval,
            "dynasty_tier": dynasty_tier(dval),
            "dynasty_trend": dp.get("dynasty_trend"),
            "ppg_2025": ppg,
            "weighted_ppg_2025": weighted_ppg,
            "predicted_value_score_2026": pred.get("predicted_value_score"),
            "is_top_dog": pred.get("is_top_dog"),
            "headshot_url": stats.get("headshot_url") if stats else None,
        })

    results.sort(key=lambda x: (x["dynasty_value"] or 0), reverse=True)

    # Add positional rank within results
    pos_counters: dict = {}
    for r in results:
        p = r["position"]
        pos_counters[p] = pos_counters.get(p, 0) + 1
        r["dynasty_pos_rank"] = pos_counters[p]

    result = {"players": results, "count": len(results)}
    _sleeper_cache[cache_key] = result
    _sleeper_cache[f"{cache_key}_ts"] = time.time()
    return result


@app.get("/api/dynasty/picks")
def get_dynasty_picks():
    """Draft pick values from FantasyCalc dynasty data."""
    import time
    cache_key = "dynasty_picks"
    if _sleeper_cache.get(cache_key) and time.time() - _sleeper_cache.get(f"{cache_key}_ts", 0) < 86400:
        return _sleeper_cache[cache_key]

    dyn_data = get_dynasty_adp.__wrapped__() if hasattr(get_dynasty_adp, '__wrapped__') else None
    # Re-fetch raw FantasyCalc data to get PICK entries (filtered out of dynasty_adp endpoint)
    import httpx
    try:
        resp = httpx.get(
            "https://api.fantasycalc.com/values/current?isDynasty=true&numQbs=1",
            timeout=10, headers={"User-Agent": "GridIron/1.0"}
        )
        resp.raise_for_status()
        fc_data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FantasyCalc unavailable: {e}")

    picks = []
    for entry in fc_data:
        p = entry.get("player", {})
        if p.get("position") != "PICK":
            continue
        name = p.get("name", "")
        picks.append({
            "name": name,
            "dynasty_value": entry.get("value", 0),
            "overall_rank": entry.get("overallRank"),
            "position": "PICK",
        })

    picks.sort(key=lambda x: x.get("overall_rank") or 999)
    result = {"picks": picks}
    _sleeper_cache[cache_key] = result
    _sleeper_cache[f"{cache_key}_ts"] = time.time()
    return result


# ── CB Coverage System ───────────────────────────────────────────────────────

_cb_cache: dict = {}

def _load_cb_data(year: int = 2025):
    """Load all CB data files for a given season."""
    import pandas as pd, time
    key = f"cb_data_{year}"
    if _cb_cache.get(key) and time.time() - _cb_cache.get(f"{key}_ts", 0) < 3600:
        return _cb_cache[key]

    base = os.path.dirname(__file__)
    def safe_read(name):
        p = os.path.join(base, f"data_{year}_{name}.parquet")
        if os.path.exists(p):
            return pd.read_parquet(p)
        return pd.DataFrame()

    data = {
        "cb_stats": safe_read("cb_stats"),
        "team_coverage": safe_read("team_coverage"),
        "route_coverage": safe_read("route_coverage"),
        "cb_depth": safe_read("cb_depth"),
    }
    _cb_cache[key] = data
    _cb_cache[f"{key}_ts"] = time.time()
    return data


@app.get("/api/cb/rankings")
def get_cb_rankings(team: str = "", year: int = 2025):
    """All CB coverage stats, optionally filtered by team."""
    import time
    cache_key = f"cb_rankings_{team}_{year}"
    if _sleeper_cache.get(cache_key) and time.time() - _sleeper_cache.get(f"{cache_key}_ts", 0) < 3600:
        return _sleeper_cache[cache_key]

    data = _load_cb_data(year)
    cb_stats = data["cb_stats"]
    cb_depth = data["cb_depth"]

    if cb_stats.empty:
        return {"cbs": []}

    # Merge depth chart slot
    def _norm(n): return (n or "").lower().replace("'","").replace(".","").replace("-","").replace(" ","")
    if not cb_depth.empty:
        slot_map = {_norm(r["player_name"]): r.get("cb_slot","") for _, r in cb_depth.iterrows()}
    else:
        slot_map = {}

    # Filter by team
    stats = cb_stats.copy()
    if team:
        team_upper = team.upper()
        stats = stats[stats["team"] == team_upper]

    # Require minimum games played
    stats = stats[stats["games"] >= 4].copy()

    result = []
    for _, row in stats.iterrows():
        result.append({
            "name": row.get("pfr_player_name", ""),
            "pfr_id": row.get("pfr_player_id", ""),
            "team": row.get("team", ""),
            "season": int(year),
            "games": int(row.get("games", 0)),
            "targets_per_game": float(row.get("targets_per_game", 0) or 0),
            "comp_pct": float(row.get("comp_pct", 0) or 0),
            "yards_per_target": float(row.get("yards_per_target", 0) or 0),
            "td_per_target": float(row.get("td_per_target", 0) or 0),
            "passer_rating_allowed": float(row.get("avg_passer_rating", 0) or 0),
            "adot": float(row.get("avg_adot", 0) or 0),
            "coverage_quality": float(row.get("coverage_quality", 50) or 50),
            "coverage_grade": row.get("coverage_grade", "—"),
            "cb_slot": slot_map.get(_norm(row.get("pfr_player_name","")), ""),
        })

    result.sort(key=lambda x: x["coverage_quality"], reverse=True)
    out = {"cbs": result, "count": len(result)}
    _sleeper_cache[cache_key] = out
    _sleeper_cache[f"{cache_key}_ts"] = time.time()
    return out


@app.get("/api/cb/team-matchup")
def get_cb_team_matchup(team: str, opponent: str, year: int = 2025):
    """
    Full WR vs CB matchup breakdown for a team playing an opponent.
    Returns:
      - opponent's starting CBs (LCB1, RCB1, slot) with coverage stats
      - opponent's coverage scheme tendencies (man% / zone%)
      - route advantage analysis (which routes work best vs their scheme)
    """
    import time
    cache_key = f"matchup_{team}_{opponent}_{year}"
    if _sleeper_cache.get(cache_key) and time.time() - _sleeper_cache.get(f"{cache_key}_ts", 0) < 3600:
        return _sleeper_cache[cache_key]

    data = _load_cb_data(year)
    cb_stats = data["cb_stats"]
    team_cov = data["team_coverage"]
    route_cov = data["route_coverage"]
    cb_depth = data["cb_depth"]

    def _norm(n): return (n or "").lower().replace("'","").replace(".","").replace("-","").replace(" ","")

    # --- Opponent's CBs ---
    opp_upper = opponent.upper()
    opp_cbs_depth = cb_depth[cb_depth["team"] == opp_upper] if not cb_depth.empty else []

    cb_name_map = {}
    if not cb_stats.empty:
        for _, r in cb_stats.iterrows():
            cb_name_map[_norm(r.get("pfr_player_name",""))] = r

    def enrich_cb(player_name, slot):
        nn = _norm(player_name)
        raw = cb_name_map.get(nn)
        stats = dict(raw) if raw is not None and hasattr(raw, 'to_dict') else (raw or {})
        # Fallback: last name + first initial ("Pat" vs "Patrick")
        if not stats and len(player_name.split()) >= 2:
            parts = player_name.split()
            last = _norm(" ".join(parts[1:]))
            first_init = parts[0][0].lower()
            for key, val in cb_name_map.items():
                if key.endswith(last) and key.startswith(first_init):
                    stats = dict(val) if hasattr(val, 'to_dict') else (val or {})
                    break
        return {
            "name": player_name,
            "slot": slot,
            "team": opp_upper,
            "games": int(stats.get("games", 0) or 0),
            "targets_per_game": float(stats.get("targets_per_game", 0) or 0),
            "comp_pct": float(stats.get("comp_pct", 0) or 0),
            "yards_per_target": float(stats.get("yards_per_target", 0) or 0),
            "passer_rating_allowed": float(stats.get("avg_passer_rating", 95) or 95),
            "coverage_quality": float(stats.get("coverage_quality", 50) or 50),
            "coverage_grade": stats.get("coverage_grade", "—"),
            "has_stats": bool(stats),
        }

    starting_cbs = []
    if not isinstance(opp_cbs_depth, list) and not opp_cbs_depth.empty:
        for _, row in opp_cbs_depth.iterrows():
            starting_cbs.append(enrich_cb(row["player_name"], row.get("cb_slot", "")))
    starting_cbs.sort(key=lambda x: x["coverage_quality"], reverse=True)

    # --- Opponent's coverage scheme ---
    scheme = {}
    if not team_cov.empty:
        opp_row = team_cov[team_cov["defteam"] == opp_upper]
        if not opp_row.empty:
            r = opp_row.iloc[0]
            scheme = {
                "pct_man": float(r.get("pct_man", 0.3)),
                "pct_zone": float(r.get("pct_zone", 0.7)),
                "total_plays": int(r.get("total_plays", 0)),
            }
            # Add per-coverage breakdown
            for col in opp_row.columns:
                if col.startswith("pct_") and col not in ("pct_man", "pct_zone"):
                    scheme[col] = float(r[col] or 0)
    if not scheme:
        scheme = {"pct_man": 0.3, "pct_zone": 0.7, "total_plays": 0}

    is_man_heavy = scheme.get("pct_man", 0) >= 0.4
    scheme["coverage_tendency"] = "Man-heavy" if is_man_heavy else "Zone-heavy"
    scheme["tendency_pct"] = scheme.get("pct_man") if is_man_heavy else scheme.get("pct_zone")

    # --- Route advantage vs scheme ---
    route_advice = []
    if not route_cov.empty:
        man_pct = scheme.get("pct_man", 0.3)

        for route in route_cov["route"].unique():
            r_man = route_cov[(route_cov["route"] == route) & (route_cov["coverage_type"] == "man")]
            r_zone = route_cov[(route_cov["route"] == route) & (route_cov["coverage_type"] == "zone")]

            if r_man.empty or r_zone.empty:
                continue

            man_ypa = float(r_man.iloc[0]["ypa"])
            zone_ypa = float(r_zone.iloc[0]["ypa"])
            man_comp = float(r_man.iloc[0]["comp_pct"])
            zone_comp = float(r_zone.iloc[0]["comp_pct"])

            # Weighted YPA based on opponent's actual coverage distribution
            expected_ypa = man_pct * man_ypa + (1 - man_pct) * zone_ypa
            expected_comp = man_pct * man_comp + (1 - man_pct) * zone_comp

            # Is this route better vs this team's scheme vs average?
            avg_ypa = 0.3 * man_ypa + 0.7 * zone_ypa  # league avg scheme
            route_edge = expected_ypa - avg_ypa

            route_advice.append({
                "route": route,
                "expected_ypa": round(expected_ypa, 2),
                "expected_comp_pct": round(expected_comp, 3),
                "man_ypa": round(man_ypa, 2),
                "zone_ypa": round(zone_ypa, 2),
                "route_edge": round(route_edge, 2),
                "recommendation": (
                    "Target" if route_edge >= 0.2 else
                    "Avoid" if route_edge <= -0.2 else "Neutral"
                ),
            })

        route_advice.sort(key=lambda x: x["route_edge"], reverse=True)

    result = {
        "team": team.upper(),
        "opponent": opp_upper,
        "season": year,
        "starting_cbs": starting_cbs,
        "scheme": scheme,
        "route_advice": route_advice,
        "summary": (
            f"{opp_upper} plays {scheme['coverage_tendency']} ({round(scheme['tendency_pct']*100)}%). "
            f"{'Target deep routes and corners.' if not is_man_heavy else 'Target quick routes (slants, screens) that beat man coverage.'}"
        ),
    }

    _sleeper_cache[cache_key] = result
    _sleeper_cache[f"{cache_key}_ts"] = time.time()
    return result


@app.get("/api/cb/wr-impact")
def get_wr_cb_impact(player_id: str, opponent: str, year: int = 2025):
    """
    Predict CB matchup impact on a specific WR for a given opponent.
    Cross-references WR route tree with opponent CB quality and scheme.
    """
    import time, json as _json
    cache_key = f"wr_impact_{player_id}_{opponent}_{year}"
    if _sleeper_cache.get(cache_key) and time.time() - _sleeper_cache.get(f"{cache_key}_ts", 0) < 3600:
        return _sleeper_cache[cache_key]

    # Get WR's route tree from existing PBP data
    data = load_data()
    players_df = data["players"]
    wr_row = players_df[players_df["player_id"] == player_id]
    if wr_row.empty:
        raise HTTPException(status_code=404, detail="Player not found")

    wr = dict(wr_row.iloc[0])
    wr_name = wr.get("player_display_name", "")
    wr_team = wr.get("recent_team", "")
    wr_pos = wr.get("position", "WR")

    # Get matchup data
    matchup = get_cb_team_matchup(team=wr_team, opponent=opponent, year=year)
    scheme = matchup.get("scheme", {})
    route_advice = matchup.get("route_advice", [])
    cbs = matchup.get("starting_cbs", [])

    # WR baseline stats
    games = float(wr.get("games") or 0)
    fpts = float(wr.get("fantasy_points_ppr") or 0)
    ppg = round(fpts / games, 1) if games > 0 else 0.0
    targets = float(wr.get("targets") or 0)
    tpg = round(targets / games, 1) if games > 0 else 0.0

    # Likely CB matchup: CB1 for outside WR, NB for slot
    # (Simple heuristic — we don't have exact lineup info)
    primary_cb = None
    if cbs:
        # Best CB (highest quality) for WR1 matchup
        primary_cb = cbs[0]

    # Coverage quality impact on WR production
    # League avg CB quality ~50; elite CB = ~75-80, replacement = ~30
    cb_quality = primary_cb["coverage_quality"] if primary_cb else 50
    # Each 10-pt quality above avg reduces WR output ~5%
    cb_impact_pct = (50 - cb_quality) / 10 * 0.05  # positive = boost, negative = penalty
    adjusted_ppg = round(ppg * (1 + cb_impact_pct), 1)

    # Top target routes for this WR
    target_routes = [r for r in route_advice if r["recommendation"] == "Target"][:3]
    avoid_routes = [r for r in route_advice if r["recommendation"] == "Avoid"][:3]

    result = {
        "player_id": player_id,
        "name": wr_name,
        "team": wr_team,
        "position": wr_pos,
        "opponent": opponent.upper(),
        "baseline_ppg": ppg,
        "baseline_tpg": tpg,
        "projected_ppg": adjusted_ppg,
        "cb_impact_pct": round(cb_impact_pct * 100, 1),
        "primary_cb": primary_cb,
        "scheme": scheme,
        "target_routes": target_routes,
        "avoid_routes": avoid_routes,
        "verdict": (
            "Favorable" if cb_impact_pct >= 0.03 else
            "Tough" if cb_impact_pct <= -0.03 else
            "Neutral"
        ),
    }

    _sleeper_cache[cache_key] = result
    _sleeper_cache[f"{cache_key}_ts"] = time.time()
    return result


# ── Static files (React build) ───────────────────────────────────────────────
DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        return FileResponse(os.path.join(DIST, "index.html"))
