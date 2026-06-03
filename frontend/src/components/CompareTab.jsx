import { useState, useMemo } from 'react'
import { POS_COLORS, POS_EMOJI, fmt, fmtInt } from '../utils'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer, Legend, Tooltip,
} from 'recharts'
import PlayerDetail from './PlayerDetail'

const RADAR_COLORS = ['var(--wr)', 'var(--rb)', 'var(--qb)', 'var(--te)']

// Universal radar axes — normalized per stat
function norm(val, min, max) {
  if (val == null || isNaN(val)) return 30
  return Math.round(Math.min(100, Math.max(0, ((val - min) / (max - min)) * 100)))
}

function radarCompare(p) {
  const pos = p.position
  let volume, efficiency, epa, explosiveness, usage, receiving
  if (pos === 'QB') {
    volume       = norm(p.passing_yards, 1000, 5000)
    efficiency   = norm(p.completion_pct, 55, 75)
    epa          = norm(p.passing_epa, -50, 400)
    explosiveness= norm(p.passing_tds / Math.max(p.attempts, 1) * 100, 2, 9)
    usage        = norm(p.attempts, 200, 700)
    receiving    = norm(p.rushing_yards, 0, 800)
  } else if (pos === 'WR' || pos === 'TE') {
    volume       = norm(p.receiving_yards, 100, 1800)
    efficiency   = norm(p.yards_per_target, 4, 14)
    epa          = norm(p.receiving_epa, -10, 80)
    explosiveness= norm(p.avg_separation, 1, 5)
    usage        = norm(p.target_share, 0.04, 0.35)
    receiving    = norm(p.wopr, 0.05, 0.7)
  } else if (pos === 'RB') {
    volume       = norm(p.rushing_yards, 100, 1800)
    efficiency   = norm(p.yards_per_carry, 2.5, 6)
    epa          = norm(p.rushing_epa, -60, 60)
    explosiveness= norm(p.rush_yards_over_expected_per_att, -1.5, 2)
    usage        = norm(p.carries, 50, 350)
    receiving    = norm(p.receiving_yards, 0, 800)
  } else {
    volume = efficiency = epa = explosiveness = usage = receiving = 50
  }
  return [
    { axis: 'Volume',      score: volume },
    { axis: 'Efficiency',  score: efficiency },
    { axis: 'EPA',         score: epa },
    { axis: 'Explosiveness', score: explosiveness },
    { axis: 'Usage',       score: usage },
    { axis: 'Receiving',   score: receiving },
  ]
}

function compareStats(p) {
  const pos = p.position
  if (pos === 'QB') return [
    { lbl: 'Pass Yards',  val: fmtInt(p.passing_yards) },
    { lbl: 'TDs',         val: fmtInt(p.passing_tds) },
    { lbl: 'INTs',        val: fmtInt(p.interceptions) },
    { lbl: 'Comp %',      val: fmt(p.completion_pct) + '%' },
    { lbl: 'CPOE',        val: fmt(p.completion_percentage_above_expectation) + '%' },
    { lbl: 'Pass EPA',    val: fmt(p.passing_epa) },
    { lbl: 'Rush Yds',    val: fmtInt(p.rushing_yards) },
    { lbl: 'PPR Pts',     val: fmt(p.fantasy_points_ppr) },
  ]
  if (pos === 'WR' || pos === 'TE') return [
    { lbl: 'Rec Yards',   val: fmtInt(p.receiving_yards) },
    { lbl: 'Receptions',  val: fmtInt(p.receptions) },
    { lbl: 'Targets',     val: fmtInt(p.targets) },
    { lbl: 'TDs',         val: fmtInt(p.receiving_tds) },
    { lbl: 'Rec EPA',     val: fmt(p.receiving_epa) },
    { lbl: 'Separation',  val: fmt(p.avg_separation) + 'yd' },
    { lbl: 'WOPR',        val: fmt(p.wopr) },
    { lbl: 'PPR Pts',     val: fmt(p.fantasy_points_ppr) },
  ]
  if (pos === 'RB') return [
    { lbl: 'Rush Yards',  val: fmtInt(p.rushing_yards) },
    { lbl: 'Carries',     val: fmtInt(p.carries) },
    { lbl: 'YPC',         val: fmt(p.yards_per_carry) },
    { lbl: 'Rush TDs',    val: fmtInt(p.rushing_tds) },
    { lbl: 'Rush EPA',    val: fmt(p.rushing_epa) },
    { lbl: 'Rec Yards',   val: fmtInt(p.receiving_yards) },
    { lbl: 'RYOE/Att',    val: fmt(p.rush_yards_over_expected_per_att) },
    { lbl: 'PPR Pts',     val: fmt(p.fantasy_points_ppr) },
  ]
  return []
}

// Stats where lower = better
const LOWER_IS_BETTER = new Set(['INTs'])

// Find the best raw value per stat row across all players (for highlighting)
function getBestPerStat(players) {
  const rawExtract = (p, lbl) => {
    const val = compareStats(p).find(s => s.lbl === lbl)?.val ?? ''
    return parseFloat(val.toString().replace(/[^0-9.\-]/g, ''))
  }
  const allLabels = [...new Set(players.flatMap(p => compareStats(p).map(s => s.lbl)))]
  const best = {}
  for (const lbl of allLabels) {
    const vals = players.map(p => rawExtract(p, lbl)).filter(v => !isNaN(v))
    best[lbl] = LOWER_IS_BETTER.has(lbl) ? Math.min(...vals) : Math.max(...vals)
  }
  return (player, lbl) => {
    const val = rawExtract(player, lbl)
    if (isNaN(val)) return false
    // For lower-is-better stats, don't highlight 0 (means no data)
    if (LOWER_IS_BETTER.has(lbl) && val === 0) return false
    return Math.abs(val - best[lbl]) < 0.01
  }
}

function PlayerChip({ player, onRemove }) {
  const color = POS_COLORS[player.position] || 'var(--accent)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--surface2)', border: `1px solid ${color}44`, borderRadius: 20, padding: '4px 10px 4px 6px' }}>
      {player.headshot_url
        ? <img src={player.headshot_url} alt="" style={{ width: 24, height: 24, borderRadius: '50%', objectFit: 'cover' }} onError={e => { e.target.style.display = 'none' }} />
        : <span style={{ fontSize: 14 }}>{POS_EMOJI[player.position]}</span>
      }
      <span style={{ fontSize: 13, fontWeight: 600 }}>{player.player_display_name}</span>
      <span style={{ fontSize: 11, color: 'var(--muted)' }}>{player.recent_team}</span>
      <button onClick={() => onRemove(player.player_id)} style={{ background: 'none', border: 'none', color: 'var(--muted)', cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: 0, marginLeft: 2 }}>×</button>
    </div>
  )
}

export default function CompareTab({ players: allPlayers }) {
  const [selected, setSelected] = useState([])
  const [search, setSearch] = useState('')
  const [viewingPlayer, setViewingPlayer] = useState(null)

  const suggestions = useMemo(() => {
    if (!search.trim() || search.length < 2) return []
    const q = search.toLowerCase()
    const selectedIds = new Set(selected.map(p => p.player_id))
    return allPlayers
      .filter(p => p.player_display_name?.toLowerCase().includes(q) && !selectedIds.has(p.player_id))
      .slice(0, 8)
  }, [search, allPlayers, selected])

  const addPlayer = (player) => {
    if (selected.length >= 4) return
    setSelected(prev => [...prev, player])
    setSearch('')
  }

  const removePlayer = (id) => setSelected(prev => prev.filter(p => p.player_id !== id))

  // Merge radar data for all selected players
  const radarData = useMemo(() => {
    if (!selected.length) return []
    const axes = ['Volume', 'Efficiency', 'EPA', 'Explosiveness', 'Usage', 'Receiving']
    return axes.map(axis => {
      const entry = { axis }
      selected.forEach((p, i) => {
        const rd = radarCompare(p)
        entry[`p${i}`] = rd.find(r => r.axis === axis)?.score ?? 50
      })
      return entry
    })
  }, [selected])

  const isBest = useMemo(() => selected.length > 1 ? getBestPerStat(selected) : () => false, [selected])

  if (viewingPlayer) {
    return <PlayerDetail player={viewingPlayer} onBack={() => setViewingPlayer(null)} />
  }

  return (
    <div>
      <div className="section-title">Player Comparison</div>
      <p className="section-subtitle">Compare up to 4 players side-by-side with overlaid skill profiles</p>

      {/* Search */}
      <div style={{ position: 'relative', marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: selected.length ? 10 : 0 }}>
          {selected.map(p => <PlayerChip key={p.player_id} player={p} onRemove={removePlayer} />)}
        </div>
        {selected.length < 4 && (
          <div style={{ position: 'relative', display: 'inline-block' }}>
            <input
              className="search-input"
              placeholder={selected.length === 0 ? 'Search a player to compare…' : 'Add another player…'}
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ width: 260 }}
            />
            {suggestions.length > 0 && (
              <div style={{ position: 'absolute', top: '100%', left: 0, zIndex: 200, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', width: 280, marginTop: 4, boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }}>
                {suggestions.map(p => {
                  const color = POS_COLORS[p.position] || 'var(--accent)'
                  return (
                    <div
                      key={p.player_id}
                      onClick={() => addPlayer(p)}
                      style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', cursor: 'pointer', borderBottom: '1px solid var(--border)' }}
                      onMouseEnter={e => e.currentTarget.style.background = 'var(--surface2)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                    >
                      {p.headshot_url
                        ? <img src={p.headshot_url} alt="" style={{ width: 28, height: 28, borderRadius: '50%', objectFit: 'cover' }} onError={e => { e.target.style.display = 'none' }} />
                        : <span style={{ fontSize: 16 }}>{POS_EMOJI[p.position]}</span>
                      }
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 13 }}>{p.player_display_name}</div>
                        <div style={{ fontSize: 11, color: 'var(--muted)' }}>{p.recent_team} · {p.position}</div>
                      </div>
                      <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 700, color, background: color + '22', padding: '2px 6px', borderRadius: 4 }}>{p.position}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {selected.length === 0 && (
        <div className="empty" style={{ paddingTop: 40 }}>
          Search for a player above to start comparing
        </div>
      )}

      {selected.length >= 1 && (
        <>
          {/* Radar overlay */}
          <div className="chart-wrap" style={{ marginBottom: 24 }}>
            <h4>Skill Profile Comparison</h4>
            <ResponsiveContainer width="100%" height={280}>
              <RadarChart data={radarData}>
                <PolarGrid stroke="var(--border)" />
                <PolarAngleAxis dataKey="axis" tick={{ fill: 'var(--muted)', fontSize: 12 }} />
                <Tooltip
                  contentStyle={{ background: 'var(--surface2)', border: '1px solid var(--border)', fontSize: 12 }}
                  formatter={(val, name) => {
                    const idx = parseInt(name.replace('p', ''))
                    return [val, selected[idx]?.player_display_name]
                  }}
                />
                {selected.map((p, i) => (
                  <Radar
                    key={p.player_id}
                    name={`p${i}`}
                    dataKey={`p${i}`}
                    stroke={RADAR_COLORS[i]}
                    fill={RADAR_COLORS[i]}
                    fillOpacity={0.12}
                    strokeWidth={2}
                  />
                ))}
                <Legend
                  formatter={(value) => {
                    const idx = parseInt(value.replace('p', ''))
                    return selected[idx]?.player_display_name || value
                  }}
                  wrapperStyle={{ fontSize: 12 }}
                />
              </RadarChart>
            </ResponsiveContainer>
          </div>

          {/* Side-by-side stat table */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
            {/* Player headers */}
            <div style={{ display: 'grid', gridTemplateColumns: `160px repeat(${selected.length}, 1fr)`, borderBottom: '2px solid var(--border)' }}>
              <div style={{ padding: '12px 16px', fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>Stat</div>
              {selected.map((p, i) => {
                const color = POS_COLORS[p.position] || 'var(--accent)'
                return (
                  <div
                    key={p.player_id}
                    style={{ padding: '12px 16px', borderLeft: '1px solid var(--border)', cursor: 'pointer' }}
                    onClick={() => setViewingPlayer(p)}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      {p.headshot_url && (
                        <img src={p.headshot_url} alt="" style={{ width: 32, height: 32, borderRadius: '50%', objectFit: 'cover' }} onError={e => { e.target.style.display = 'none' }} />
                      )}
                      <div>
                        <div style={{ fontWeight: 700, fontSize: 13, color: RADAR_COLORS[i] }}>{p.player_display_name}</div>
                        <div style={{ fontSize: 11, color: 'var(--muted)' }}>{p.recent_team} · <span style={{ color }}>{p.position}</span></div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Stat rows — each player shows their own position stats */}
            {(() => {
              // Collect all unique stat labels across all players
              const allStats = new Map()
              selected.forEach(p => {
                compareStats(p).forEach(s => {
                  if (!allStats.has(s.lbl)) allStats.set(s.lbl, new Map())
                  allStats.get(s.lbl).set(p.player_id, s.val)
                })
              })
              return Array.from(allStats.entries()).map(([lbl, valMap], rowIdx) => (
                <div
                  key={lbl}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: `160px repeat(${selected.length}, 1fr)`,
                    borderBottom: '1px solid var(--border)',
                    background: rowIdx % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)',
                  }}
                >
                  <div style={{ padding: '9px 16px', fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, display: 'flex', alignItems: 'center' }}>{lbl}</div>
                  {selected.map((p, i) => {
                    const val = valMap.get(p.player_id) ?? '—'
                    const best = isBest(p, lbl)
                    const color = POS_COLORS[p.position] || 'var(--accent)'
                    return (
                      <div
                        key={p.player_id}
                        style={{
                          padding: '9px 16px',
                          borderLeft: '1px solid var(--border)',
                          fontWeight: best ? 700 : 400,
                          color: best ? color : 'var(--text)',
                          fontSize: 14,
                          display: 'flex',
                          alignItems: 'center',
                        }}
                      >
                        {val}
                        {best && <span style={{ marginLeft: 4, fontSize: 10 }}>▲</span>}
                      </div>
                    )
                  })}
                </div>
              ))
            })()}
          </div>
        </>
      )}
    </div>
  )
}
