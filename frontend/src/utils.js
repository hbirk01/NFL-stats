export const POS_COLORS = {
  QB: 'var(--qb)',
  WR: 'var(--wr)',
  RB: 'var(--rb)',
  TE: 'var(--te)',
}

export const POS_EMOJI = {
  QB: '🏈',
  WR: '⚡',
  RB: '💨',
  TE: '🔒',
}

export function fmt(val, decimals = 1) {
  if (val == null || isNaN(val)) return '—'
  return Number(val).toFixed(decimals)
}

export function fmtInt(val) {
  if (val == null || isNaN(val)) return '—'
  return Math.round(val).toLocaleString()
}

// Position-specific key stats shown on the player card
export function cardStats(p) {
  const pos = p.position
  if (pos === 'QB') return [
    { val: fmtInt(p.passing_yards), lbl: 'Pass Yds' },
    { val: fmt(p.completion_pct) + '%', lbl: 'Cmp%' },
    { val: fmtInt(p.passing_tds), lbl: 'TDs' },
    { val: fmt(p.passing_epa), lbl: 'EPA' },
  ]
  if (pos === 'WR') return [
    { val: fmtInt(p.receiving_yards), lbl: 'Rec Yds' },
    { val: fmtInt(p.targets), lbl: 'Targets' },
    { val: fmt(p.avg_separation) + 'yd', lbl: 'Sep' },
    { val: fmt(p.receiving_epa), lbl: 'EPA' },
  ]
  if (pos === 'RB') return [
    { val: fmtInt(p.rushing_yards), lbl: 'Rush Yds' },
    { val: fmt(p.yards_per_carry), lbl: 'YPC' },
    { val: fmtInt(p.receiving_yards), lbl: 'Rec Yds' },
    { val: fmt(p.rushing_epa), lbl: 'EPA' },
  ]
  if (pos === 'TE') return [
    { val: fmtInt(p.receiving_yards), lbl: 'Rec Yds' },
    { val: fmtInt(p.targets), lbl: 'Targets' },
    { val: fmt(p.avg_separation) + 'yd', lbl: 'Sep' },
    { val: fmt(p.receiving_epa), lbl: 'EPA' },
  ]
  return []
}

// Position-specific stats for the detail page stat grid
export function detailStats(p) {
  const pos = p.position
  if (pos === 'QB') return [
    { val: fmtInt(p.passing_yards), lbl: 'Pass Yards' },
    { val: fmt(p.completion_pct) + '%', lbl: 'Comp %' },
    { val: fmtInt(p.passing_tds), lbl: 'TDs' },
    { val: fmtInt(p.interceptions), lbl: 'INTs' },
    { val: fmt(p.passing_epa), lbl: 'Pass EPA' },
    { val: fmt(p.completion_percentage_above_expectation) + '%', lbl: 'CPOE' },
    { val: fmt(p.avg_time_to_throw) + 's', lbl: 'Time/Throw' },
    { val: fmt(p.avg_completed_air_yards) + 'yd', lbl: 'CAY' },
    { val: fmt(p.qb_adot) + 'yd', lbl: 'aDOT' },
    { val: fmt(p.td_int_ratio), lbl: 'TD/INT' },
    { val: fmt(p.deep_comp_pct) + '%', lbl: 'Deep Cmp%' },
    { val: fmt(p.short_comp_pct) + '%', lbl: 'Short Cmp%' },
    { val: fmt(p.scramble_rate) + '%', lbl: 'Scramble%' },
    { val: fmtInt(p.rz_attempts), lbl: 'RZ Att.' },
    { val: fmt(p.rz_td_rate) + '%', lbl: 'RZ TD%' },
    { val: fmtInt(p.attempts), lbl: 'Attempts' },
  ]
  if (pos === 'WR') return [
    { val: fmtInt(p.receiving_yards), lbl: 'Rec Yards' },
    { val: fmtInt(p.receptions), lbl: 'Receptions' },
    { val: fmtInt(p.targets), lbl: 'Targets' },
    { val: fmt(p.receiving_tds), lbl: 'TDs' },
    { val: fmt(p.receiving_epa), lbl: 'Rec EPA' },
    { val: fmt(p.avg_separation) + 'yd', lbl: 'Separation' },
    { val: fmt(p.avg_cushion) + 'yd', lbl: 'Cushion' },
    { val: fmt(p.avg_yac_above_expectation) + 'yd', lbl: 'YAC+' },
    { val: fmt(p.adot) + 'yd', lbl: 'aDOT' },
    { val: fmt(p.air_yards_share) + '%', lbl: 'AY Share' },
    { val: fmt(p.target_share ? p.target_share * 100 : null) + '%', lbl: 'Tgt Share' },
    { val: fmt(p.wopr), lbl: 'WOPR' },
    { val: fmtInt(p.rz_targets), lbl: 'RZ Tgts' },
    { val: fmtInt(p.endzone_targets), lbl: 'EZ Tgts' },
    { val: fmt(p.first_down_rate_rec) + '%', lbl: '1D Rate' },
    { val: fmt(p.yards_per_target), lbl: 'YPT' },
  ]
  if (pos === 'RB') return [
    { val: fmtInt(p.rushing_yards), lbl: 'Rush Yards' },
    { val: fmtInt(p.carries), lbl: 'Carries' },
    { val: fmt(p.yards_per_carry), lbl: 'YPC' },
    { val: fmtInt(p.rushing_tds), lbl: 'Rush TDs' },
    { val: fmt(p.rushing_epa), lbl: 'Rush EPA' },
    { val: fmt(p.rush_yards_over_expected_per_att), lbl: 'RYOE/Att' },
    { val: fmt(p.efficiency), lbl: 'NGS Eff.' },
    { val: fmt(p.stuffed_rate) + '%', lbl: 'Stuffed%' },
    { val: fmt(p.ten_plus_rate) + '%', lbl: '10+ Yd%' },
    { val: fmtInt(p.rz_carries), lbl: 'RZ Carries' },
    { val: fmt(p.first_down_rate_rush) + '%', lbl: '1D Rate' },
    { val: fmtInt(p.receiving_yards), lbl: 'Rec Yards' },
    { val: fmtInt(p.targets), lbl: 'Targets' },
    { val: fmt(p.receiving_epa), lbl: 'Rec EPA' },
  ]
  if (pos === 'TE') return [
    { val: fmtInt(p.receiving_yards), lbl: 'Rec Yards' },
    { val: fmtInt(p.receptions), lbl: 'Receptions' },
    { val: fmtInt(p.targets), lbl: 'Targets' },
    { val: fmtInt(p.receiving_tds), lbl: 'TDs' },
    { val: fmt(p.receiving_epa), lbl: 'Rec EPA' },
    { val: fmt(p.avg_separation) + 'yd', lbl: 'Separation' },
    { val: fmt(p.yac_per_rec), lbl: 'YAC/Rec' },
    { val: fmt(p.air_yards_per_rec), lbl: 'AY/Rec' },
    { val: fmt(p.avg_yac_above_expectation) + 'yd', lbl: 'YAC+' },
    { val: fmt(p.target_share != null ? p.target_share * 100 : null) + '%', lbl: 'Tgt Share' },
    { val: fmt(p.wopr), lbl: 'WOPR' },
    { val: fmt(p.adot) + 'yd', lbl: 'aDOT' },
    { val: fmtInt(p.rz_targets), lbl: 'RZ Tgts' },
    { val: fmt(p.first_down_rate_rec) + '%', lbl: '1D Rate' },
  ]
  return []
}

// Leaderboard metric options per position
export const LEADERBOARD_METRICS = {
  QB: [
    { key: 'passing_yards', label: 'Passing Yards' },
    { key: 'passing_tds', label: 'Passing TDs' },
    { key: 'passing_epa', label: 'Pass EPA' },
    { key: 'completion_percentage_above_expectation', label: 'CPOE' },
    { key: 'completion_pct', label: 'Completion %' },
    { key: 'qb_adot', label: 'aDOT' },
    { key: 'deep_comp_pct', label: 'Deep Ball Comp%' },
    { key: 'scramble_rate', label: 'Scramble Rate' },
  ],
  WR: [
    { key: 'receiving_yards', label: 'Receiving Yards' },
    { key: 'receiving_epa', label: 'Rec EPA' },
    { key: 'avg_separation', label: 'Avg Separation' },
    { key: 'avg_yac_above_expectation', label: 'YAC Above Exp' },
    { key: 'wopr', label: 'WOPR' },
    { key: 'target_share', label: 'Target Share' },
    { key: 'air_yards_share', label: 'Air Yards Share' },
    { key: 'adot', label: 'aDOT' },
    { key: 'rz_targets', label: 'Red Zone Targets' },
  ],
  RB: [
    { key: 'rushing_yards', label: 'Rushing Yards' },
    { key: 'rushing_epa', label: 'Rush EPA' },
    { key: 'yards_per_carry', label: 'Yards Per Carry' },
    { key: 'rush_yards_over_expected_per_att', label: 'RYOE/Att' },
    { key: 'efficiency', label: 'NGS Efficiency' },
    { key: 'rz_carries', label: 'Red Zone Carries' },
    { key: 'stuffed_rate', label: 'Stuffed Rate %' },
    { key: 'ten_plus_rate', label: '10+ Yard Run %' },
  ],
  TE: [
    { key: 'receiving_yards', label: 'Receiving Yards' },
    { key: 'receiving_epa', label: 'Rec EPA' },
    { key: 'avg_separation', label: 'Avg Separation' },
    { key: 'receiving_tds', label: 'TDs' },
    { key: 'avg_yac_above_expectation', label: 'YAC Above Exp' },
    { key: 'rz_targets', label: 'Red Zone Targets' },
    { key: 'air_yards_share', label: 'Air Yards Share' },
  ],
}
