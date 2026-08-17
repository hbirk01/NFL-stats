import { useState, useEffect, useMemo } from 'react'
import { POS_COLORS, fmt } from '../utils'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const NFL_TEAMS = [
  'ARI','ATL','BAL','BUF','CAR','CHI','CIN','CLE',
  'DAL','DEN','DET','GB','HOU','IND','JAX','KC',
  'LA','LAC','LV','MIA','MIN','NE','NO','NYG',
  'NYJ','PHI','PIT','SEA','SF','TB','TEN','WAS',
]

const GRADE_COLOR = {
  'A+': '#22c55e', 'A': '#22c55e', 'A-': '#22c55e',
  'B+': '#86efac', 'B': '#86efac', 'B-': '#86efac',
  'C+': '#fbbf24', 'C': '#fbbf24', 'C-': '#fbbf24',
  'D+': '#f97316', 'D': '#f97316', 'D-': '#f97316',
  'F': '#ef4444',
}

const ROUTE_COLORS = {
  Target: '#22c55e',
  Neutral: '#fbbf24',
  Avoid: '#ef4444',
}

function CoverageGauge({ manPct, zonePct }) {
  const manW = Math.round((manPct || 0) * 100)
  const zoneW = 100 - manW
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
        <span>Zone {zoneW}%</span>
        <span>Man {manW}%</span>
      </div>
      <div style={{ height: 10, borderRadius: 5, overflow: 'hidden', background: 'var(--border)', display: 'flex' }}>
        <div style={{ width: `${zoneW}%`, background: '#3b82f6', transition: 'width 0.5s' }} />
        <div style={{ width: `${manW}%`, background: '#f97316', transition: 'width 0.5s' }} />
      </div>
      <div style={{ display: 'flex', gap: 12, fontSize: 11, marginTop: 5 }}>
        <span style={{ color: '#3b82f6' }}>■ Zone</span>
        <span style={{ color: '#f97316' }}>■ Man</span>
      </div>
    </div>
  )
}

function StatRow({ label, value, sub }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderBottom: '1px solid var(--border)' }}>
      <span style={{ fontSize: 12, color: 'var(--muted)' }}>{label}</span>
      <div style={{ textAlign: 'right' }}>
        <span style={{ fontSize: 14, fontWeight: 600 }}>{value}</span>
        {sub && <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 4 }}>{sub}</span>}
      </div>
    </div>
  )
}

function CBCard({ cb }) {
  if (!cb) return null
  const gradeColor = GRADE_COLOR[cb.coverage_grade] || 'var(--muted)'
  const slotLabel = { LCB: 'Left CB', RCB: 'Right CB', NB: 'Nickel' }[cb.slot] || cb.slot

  return (
    <div style={{ background: 'var(--surface)', borderRadius: 10, padding: 16, border: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 16 }}>{cb.name}</div>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
            {cb.team} · {slotLabel}
          </div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: gradeColor }}>{cb.coverage_grade || '—'}</div>
          <div style={{ fontSize: 10, color: 'var(--muted)' }}>Coverage</div>
        </div>
      </div>

      {cb.has_stats ? (
        <div>
          <StatRow label="Targets/Game" value={fmt(cb.targets_per_game)} />
          <StatRow label="Comp% Allowed" value={fmt(cb.comp_pct * 100) + '%'} />
          <StatRow label="Yards/Target" value={fmt(cb.yards_per_target)} />
          <StatRow label="Passer Rating" value={fmt(cb.passer_rating_allowed, 1)} sub="allowed" />
          <StatRow label="Coverage Score" value={`${fmt(cb.coverage_quality, 0)}/100`} />
          <div style={{ marginTop: 4 }}>
            <StatRow label="Games Played" value={cb.games} />
          </div>
        </div>
      ) : (
        <div style={{ fontSize: 12, color: 'var(--muted)', textAlign: 'center', padding: '12px 0' }}>
          No coverage stats available
        </div>
      )}
    </div>
  )
}

function RouteAdvice({ routes }) {
  if (!routes?.length) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {routes.map(r => {
        const color = ROUTE_COLORS[r.recommendation] || 'var(--muted)'
        const edge = r.route_edge > 0 ? `+${fmt(r.route_edge, 2)}` : fmt(r.route_edge, 2)
        return (
          <div key={r.route} style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: 'var(--surface)', borderRadius: 8, padding: '8px 12px',
            border: `1px solid ${color}33`
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
              <span style={{ fontWeight: 600, fontSize: 13 }}>{r.route}</span>
            </div>
            <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
              <span style={{ color: 'var(--muted)' }}>{fmt(r.expected_ypa, 1)} YPA</span>
              <span style={{ color: 'var(--muted)' }}>{fmt(r.expected_comp_pct * 100, 0)}% Cmp</span>
              <span style={{ color, fontWeight: 700 }}>{edge} edge</span>
              <span style={{ color, fontWeight: 700, minWidth: 48, textAlign: 'right' }}>{r.recommendation}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function PPGDelta({ baseline, projected }) {
  if (baseline == null || projected == null) return null
  const delta = projected - baseline
  const pct = baseline > 0 ? (delta / baseline) * 100 : 0
  const color = delta >= 0.5 ? '#22c55e' : delta <= -0.5 ? '#ef4444' : '#fbbf24'
  const arrow = delta > 0 ? '▲' : delta < 0 ? '▼' : '→'
  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'center', justifyContent: 'center', padding: '20px 0' }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 2 }}>Baseline PPG</div>
        <div style={{ fontSize: 28, fontWeight: 800 }}>{fmt(baseline)}</div>
      </div>
      <div style={{ textAlign: 'center', color }}>
        <div style={{ fontSize: 24 }}>{arrow}</div>
        <div style={{ fontSize: 13, fontWeight: 700 }}>{delta > 0 ? '+' : ''}{fmt(delta)} ({fmt(pct, 0)}%)</div>
      </div>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 2 }}>Projected PPG</div>
        <div style={{ fontSize: 28, fontWeight: 800, color }}>{fmt(projected)}</div>
      </div>
    </div>
  )
}

export default function MatchupTab({ players }) {
  const [search, setSearch] = useState('')
  const [selectedPlayer, setSelectedPlayer] = useState(null)
  const [opponent, setOpponent] = useState('')
  const [impact, setImpact] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Filter to WR and TE only
  const receiverPool = useMemo(() => {
    const pool = (players || []).filter(p => p.position === 'WR' || p.position === 'TE')
    if (!search.trim()) return pool.slice(0, 40)
    const q = search.toLowerCase()
    return pool.filter(p => (p.player_display_name || '').toLowerCase().includes(q)).slice(0, 40)
  }, [players, search])

  useEffect(() => {
    if (!selectedPlayer || !opponent) {
      setImpact(null)
      return
    }
    setLoading(true)
    setError(null)
    fetch(`${API}/api/cb/wr-impact?player_id=${selectedPlayer.player_id}&opponent=${opponent}`)
      .then(r => r.json())
      .then(d => { setImpact(d); setLoading(false) })
      .catch(e => { setError('Failed to load matchup data'); setLoading(false) })
  }, [selectedPlayer, opponent])

  const verdictColor = {
    Favorable: '#22c55e',
    Tough: '#ef4444',
    Neutral: '#fbbf24',
  }

  return (
    <div style={{ padding: '20px 24px', maxWidth: 1100, margin: '0 auto' }}>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 22, fontWeight: 800, marginBottom: 4 }}>WR/TE vs CB Matchup Analyzer</h2>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>
          Pick a receiver and opponent to see which CB they'll likely face, coverage scheme tendencies, and route-by-route advice.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 24, alignItems: 'start' }}>
        {/* Left: Player picker */}
        <div>
          <div style={{ marginBottom: 12 }}>
            <input
              type="text"
              placeholder="Search WR / TE..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{
                width: '100%', padding: '9px 12px', borderRadius: 8,
                border: '1px solid var(--border)', background: 'var(--surface)',
                color: 'var(--text)', fontSize: 14, boxSizing: 'border-box',
              }}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 480, overflowY: 'auto' }}>
            {receiverPool.map(p => {
              const isSelected = selectedPlayer?.player_id === p.player_id
              const color = POS_COLORS[p.position] || 'var(--accent)'
              return (
                <button
                  key={p.player_id}
                  onClick={() => setSelectedPlayer(isSelected ? null : p)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
                    borderRadius: 8, border: `1px solid ${isSelected ? color : 'var(--border)'}`,
                    background: isSelected ? `${color}15` : 'var(--surface)',
                    cursor: 'pointer', textAlign: 'left', transition: 'all 0.15s',
                  }}
                >
                  {p.headshot_url && (
                    <img src={p.headshot_url} alt="" style={{ width: 32, height: 32, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} />
                  )}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 13, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {p.player_display_name}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>{p.recent_team} · {p.position}</div>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--muted)', flexShrink: 0 }}>
                    {fmt(p.fantasy_points_ppr, 0)} PPR
                  </div>
                </button>
              )
            })}
          </div>

          {/* Opponent selector */}
          {selectedPlayer && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>Pick opponent</div>
              <select
                value={opponent}
                onChange={e => setOpponent(e.target.value)}
                style={{
                  width: '100%', padding: '9px 12px', borderRadius: 8,
                  border: '1px solid var(--border)', background: 'var(--surface)',
                  color: 'var(--text)', fontSize: 14,
                }}
              >
                <option value="">— Select Team —</option>
                {NFL_TEAMS.filter(t => t !== selectedPlayer?.recent_team).map(t => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Right: Matchup results */}
        <div>
          {!selectedPlayer && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 300, color: 'var(--muted)', fontSize: 14 }}>
              Select a receiver to begin
            </div>
          )}

          {selectedPlayer && !opponent && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 300, color: 'var(--muted)', fontSize: 14 }}>
              Now pick an opponent team
            </div>
          )}

          {loading && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200, color: 'var(--muted)' }}>
              Loading matchup...
            </div>
          )}

          {error && (
            <div style={{ color: '#ef4444', padding: 16 }}>{error}</div>
          )}

          {impact && !loading && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 800 }}>
                    {impact.name} <span style={{ color: 'var(--muted)', fontWeight: 400 }}>vs</span> {impact.opponent}
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                    {impact.team} receiver facing {impact.opponent} secondary
                  </div>
                </div>
                {impact.verdict && (
                  <div style={{
                    padding: '6px 16px', borderRadius: 20, fontWeight: 700, fontSize: 14,
                    background: `${verdictColor[impact.verdict] || 'var(--muted)'}20`,
                    color: verdictColor[impact.verdict] || 'var(--muted)',
                    border: `1px solid ${verdictColor[impact.verdict] || 'var(--muted)'}40`,
                  }}>
                    {impact.verdict} Matchup
                  </div>
                )}
              </div>

              {/* PPG Projection */}
              <div style={{ background: 'var(--surface)', borderRadius: 10, padding: 16, border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>
                  Fantasy Projection
                </div>
                <PPGDelta baseline={impact.baseline_ppg} projected={impact.projected_ppg} />
                <div style={{ display: 'flex', justifyContent: 'center', gap: 24, fontSize: 12, color: 'var(--muted)' }}>
                  <span>Baseline Tgt/G: <strong style={{ color: 'var(--text)' }}>{fmt(impact.baseline_tpg)}</strong></span>
                  <span>CB Impact: <strong style={{ color: impact.cb_impact_pct >= 0 ? '#22c55e' : '#ef4444' }}>
                    {impact.cb_impact_pct > 0 ? '+' : ''}{fmt(impact.cb_impact_pct, 1)}%
                  </strong></span>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                {/* Primary CB */}
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
                    Primary CB Matchup
                  </div>
                  {impact.primary_cb ? (
                    <CBCard cb={impact.primary_cb} />
                  ) : (
                    <div style={{ background: 'var(--surface)', borderRadius: 10, padding: 16, border: '1px solid var(--border)', color: 'var(--muted)', fontSize: 13 }}>
                      No CB depth chart data for {impact.opponent}
                    </div>
                  )}
                </div>

                {/* Coverage Scheme */}
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
                    Coverage Scheme
                  </div>
                  <div style={{ background: 'var(--surface)', borderRadius: 10, padding: 16, border: '1px solid var(--border)' }}>
                    <div style={{ marginBottom: 14 }}>
                      <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 2 }}>{impact.scheme?.coverage_tendency}</div>
                      <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                        {impact.scheme?.total_plays?.toLocaleString()} coverage snaps tracked
                      </div>
                    </div>
                    <CoverageGauge
                      manPct={impact.scheme?.pct_man}
                      zonePct={impact.scheme?.pct_zone}
                    />

                    {/* Cover type breakdown */}
                    <div style={{ marginTop: 14 }}>
                      {['pct_cover_0', 'pct_cover_1', 'pct_cover_2', 'pct_2_man', 'pct_cover_3', 'pct_cover_4', 'pct_cover_6'].map(key => {
                        const val = impact.scheme?.[key]
                        if (!val || val < 0.02) return null
                        const labels = {
                          pct_cover_0: 'Cover 0 (Blitz Man)',
                          pct_cover_1: 'Cover 1 (Man Free)',
                          pct_cover_2: 'Cover 2 (Tampa)',
                          pct_2_man: 'Cover 2 Man',
                          pct_cover_3: 'Cover 3 (Zone)',
                          pct_cover_4: 'Cover 4 (Quarters)',
                          pct_cover_6: 'Cover 6 (Quarter-Half)',
                        }
                        return (
                          <div key={key} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                            <span style={{ color: 'var(--muted)' }}>{labels[key]}</span>
                            <span style={{ fontWeight: 600 }}>{Math.round(val * 100)}%</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>
              </div>

              {/* Route Advice */}
              {impact.target_routes?.length > 0 || impact.avoid_routes?.length > 0 ? (
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>
                    Route Advice vs {impact.opponent}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
                    Edge = expected YPA vs this scheme minus league-average scheme. Positive = route benefits from their coverage tendencies.
                  </div>
                  <RouteAdvice routes={[
                    ...(impact.target_routes || []),
                    // fill in neutral routes between target and avoid
                    ...(impact.avoid_routes || []),
                  ]} />
                </div>
              ) : null}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
