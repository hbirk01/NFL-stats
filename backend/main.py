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


# ── Static files (React build) ───────────────────────────────────────────────
DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        return FileResponse(os.path.join(DIST, "index.html"))
