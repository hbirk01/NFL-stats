import { useState, useEffect } from 'react'
import { POS_COLORS } from '../utils'

// Rank 1 = most pts allowed (easiest), rank 32 = least (hardest)
function rankColor(rank) {
  if (!rank) return 'var(--muted)'
  if (rank <= 8) return 'var(--green)'
  if (rank <= 16) return '#a3e635'
  if (rank <= 24) return '#f5a623'
  return 'var(--red)'
}

function rankLabel(rank) {
  if (!rank) return '—'
  if (rank <= 8) return 'Easy'
  if (rank <= 16) return 'Avg+'
  if (rank <= 24) return 'Avg-'
  return 'Hard'
}

function PlayoffSOSView({ position }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch('/api/sos/playoff')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  if (loading) return <div className="spinner" style={{ margin: '20px auto' }} />
  if (!data) return null

  const pos = position === 'ALL' ? 'WR' : position

  // Build a list of teams with their 4-week avg difficulty rank for the position
  const teams = Object.entries(data.teams).map(([team, games]) => {
    const ranks = games.map(g => g.def_ranks?.[pos]?.rank).filter(Boolean)
    const avgRank = ranks.length ? Math.round(ranks.reduce((a, b) => a + b, 0) / ranks.length) : null
    return { team, games, avgRank }
  }).sort((a, b) => (b.avgRank ?? 0) - (a.avgRank ?? 0)) // hardest first for context; then we sort by easiest
    .sort((a, b) => (a.avgRank ?? 99) - (b.avgRank ?? 99)) // easiest (lowest avg rank = most pts allowed)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
        <div style={{ fontSize: 15, fontWeight: 700 }}>Fantasy Playoffs SOS — Weeks 14–17</div>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>Opponent defensive rank vs {pos} · Rank 1 = easiest matchup</div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 8 }}>
        {teams.map(({ team, games, avgRank }) => {
          const color = rankColor(avgRank)
          return (
            <div
              key={team}
              style={{
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderLeft: `3px solid ${color}`,
                borderRadius: 8,
                padding: '8px 12px',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <div style={{ fontWeight: 700, fontSize: 14 }}>{team}</div>
                <div style={{
                  fontSize: 11, fontWeight: 700, color,
                  background: color + '22', padding: '2px 8px', borderRadius: 4,
                }}>
                  Avg #{avgRank ?? '—'} · {rankLabel(avgRank)}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                {[14, 15, 16, 17].map(wk => {
                  const g = games.find(x => x.week === wk)
                  if (!g) return (
                    <div key={wk} style={{
                      flex: 1, textAlign: 'center', background: 'var(--surface2)',
                      borderRadius: 6, padding: '4px 0', border: '1px solid #ffffff22', opacity: 0.5,
                    }}>
                      <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Wk {wk}</div>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)' }}>BYE</div>
                      <div style={{ fontSize: 9, color: 'var(--muted)' }}>—</div>
                    </div>
                  )
                  const rank = g.def_ranks?.[pos]?.rank
                  const pts = g.def_ranks?.[pos]?.pts_per_game
                  const c = rankColor(rank)
                  return (
                    <div key={wk} style={{
                      flex: 1, textAlign: 'center', background: 'var(--surface2)',
                      borderRadius: 6, padding: '4px 0', border: `1px solid ${c}44`,
                    }}>
                      <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Wk {wk}</div>
                      <div style={{ fontSize: 11, fontWeight: 700 }}>vs {g.opponent}</div>
                      <div style={{ fontSize: 10, color: c, fontWeight: 700 }}>#{rank ?? '—'}</div>
                      {pts != null && <div style={{ fontSize: 9, color: 'var(--muted)' }}>{pts}pts/g</div>}
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
      <div style={{ marginTop: 12, display: 'flex', gap: 16, fontSize: 11, color: 'var(--muted)' }}>
        {[['Easy', 'var(--green)', '1–8'], ['Avg+', '#a3e635', '9–16'], ['Avg-', '#f5a623', '17–24'], ['Hard', 'var(--red)', '25–32']].map(([label, color, range]) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 10, height: 10, background: color, borderRadius: 2 }} />
            <span>{label} ({range})</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function SOSView({ position }) {
  const [view, setView] = useState('season')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch('/api/sos')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const pos = position === 'ALL' ? 'WR' : position
  const rankings = data?.positions?.[pos] || []

  const tabStyle = (active) => ({
    padding: '4px 14px',
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
    border: 'none',
    background: active ? 'var(--accent)' : 'var(--surface)',
    color: active ? '#fff' : 'var(--muted)',
  })

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
        <button style={tabStyle(view === 'season')} onClick={() => setView('season')}>2025 Season</button>
        <button style={tabStyle(view === 'playoff')} onClick={() => setView('playoff')}>🏆 Fantasy Playoffs (Wks 14–17)</button>
      </div>

      {view === 'season' && (
        loading
          ? <div className="spinner" style={{ margin: '20px auto' }} />
          : !rankings.length
            ? <div className="empty">No SOS data available</div>
            : (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
                  <div style={{ fontSize: 15, fontWeight: 700 }}>Defensive Rankings vs {pos}</div>
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>2025 season · PPR pts allowed per game · Rank 1 = easiest</div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 8 }}>
                  {rankings.map((r) => {
                    const color = rankColor(r.rank)
                    return (
                      <div
                        key={r.defteam}
                        style={{
                          background: 'var(--surface)',
                          border: `1px solid var(--border)`,
                          borderLeft: `3px solid ${color}`,
                          borderRadius: 8,
                          padding: '8px 12px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 10,
                        }}
                      >
                        <div style={{ fontSize: 13, color: 'var(--muted)', width: 28, fontWeight: 700 }}>#{r.rank}</div>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontWeight: 700, fontSize: 14 }}>{r.defteam}</div>
                          <div style={{ fontSize: 11, color: 'var(--muted)' }}>{r.pts_per_game} pts/g</div>
                        </div>
                        <div style={{
                          fontSize: 11, fontWeight: 700, color,
                          background: color + '22', padding: '2px 8px', borderRadius: 4,
                        }}>
                          {rankLabel(r.rank)}
                        </div>
                      </div>
                    )
                  })}
                </div>
                <div style={{ marginTop: 12, display: 'flex', gap: 16, fontSize: 11, color: 'var(--muted)' }}>
                  {[['Easy', 'var(--green)', '1–8'], ['Avg+', '#a3e635', '9–16'], ['Avg-', '#f5a623', '17–24'], ['Hard', 'var(--red)', '25–32']].map(([label, color, range]) => (
                    <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <div style={{ width: 10, height: 10, background: color, borderRadius: 2 }} />
                      <span>{label} ({range})</span>
                    </div>
                  ))}
                </div>
              </div>
            )
      )}

      {view === 'playoff' && <PlayoffSOSView position={position} />}
    </div>
  )
}
