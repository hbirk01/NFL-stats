import { useState, useEffect } from 'react'

// rank 1 = most pts allowed (easiest), rank 32 = hardest
function rankColor(rank) {
  if (!rank) return 'var(--muted)'
  if (rank <= 8)  return 'var(--green)'
  if (rank <= 16) return '#a3e635'
  if (rank <= 24) return '#f5a623'
  return 'var(--red)'
}

function rankLabel(rank) {
  if (!rank) return '?'
  if (rank <= 8)  return 'Easy'
  if (rank <= 16) return 'Avg+'
  if (rank <= 24) return 'Avg-'
  return 'Hard'
}

function difficultyScore(avgRank) {
  // avgRank 1 = easiest, 32 = hardest
  // Convert to 0-100 where 100 = hardest
  return Math.round(((avgRank - 1) / 31) * 100)
}

export default function PlayerSOS({ playerId, position }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetch(`/api/players/${playerId}/sos`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [playerId])

  if (loading) return null
  if (!data || !data.avg_rank) return null

  const { avg_rank, opponents, games } = data
  const difficulty = difficultyScore(avg_rank)
  const color = rankColor(avg_rank)
  const label = rankLabel(avg_rank)

  // Sort opponents: easiest first for easy schedule, hardest first for hard schedule
  const sorted = [...opponents].sort((a, b) => (b.def_rank ?? 0) - (a.def_rank ?? 0))
  const hardest = sorted.slice(0, 3)
  const easiest = [...opponents].sort((a, b) => (a.def_rank ?? 99) - (b.def_rank ?? 99)).slice(0, 3)

  return (
    <div className="chart-wrap" style={{ marginBottom: 20 }}>
      <div
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
        onClick={() => setExpanded(e => !e)}
      >
        <h4 style={{ margin: 0 }}>Strength of Schedule</h4>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>{expanded ? '▲ hide' : '▼ expand'}</span>
      </div>

      {/* Summary bar */}
      <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
            <span>Easiest</span>
            <span>Hardest</span>
          </div>
          <div style={{ height: 8, background: 'var(--border)', borderRadius: 4, overflow: 'hidden', position: 'relative' }}>
            <div style={{
              position: 'absolute', left: 0, top: 0, height: '100%',
              width: '100%',
              background: 'linear-gradient(to right, var(--green), #a3e635, #f5a623, var(--red))',
              borderRadius: 4,
              opacity: 0.3,
            }} />
            <div style={{
              position: 'absolute',
              left: `${difficulty}%`,
              top: '50%',
              transform: 'translate(-50%, -50%)',
              width: 14, height: 14,
              background: color,
              borderRadius: '50%',
              border: '2px solid var(--surface)',
              boxShadow: `0 0 6px ${color}88`,
            }} />
          </div>
        </div>
        <div style={{ textAlign: 'right', minWidth: 100 }}>
          <div style={{ fontSize: 18, fontWeight: 800, color }}>#{avg_rank} avg</div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>{label} schedule · {games}G</div>
        </div>
      </div>

      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6 }}>
        Avg opponent defensive rank vs {position} · Rank 1 = most pts allowed (easiest)
      </div>

      {/* Expanded: full week-by-week grid */}
      {expanded && (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', gap: 16, marginBottom: 14 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--red)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>Toughest Matchups</div>
              {hardest.map(o => (
                <div key={o.week} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 8px', background: 'var(--surface2)', borderRadius: 6, marginBottom: 4 }}>
                  <span style={{ fontSize: 12 }}>Wk {o.week} <b>{o.opponent}</b></span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: rankColor(o.def_rank) }}>#{o.def_rank} · {o.pts_per_game}pts/g</span>
                </div>
              ))}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--green)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>Easiest Matchups</div>
              {easiest.map(o => (
                <div key={o.week} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 8px', background: 'var(--surface2)', borderRadius: 6, marginBottom: 4 }}>
                  <span style={{ fontSize: 12 }}>Wk {o.week} <b>{o.opponent}</b></span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: rankColor(o.def_rank) }}>#{o.def_rank} · {o.pts_per_game}pts/g</span>
                </div>
              ))}
            </div>
          </div>

          {/* Full schedule grid */}
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5 }}>Full Schedule</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {opponents.map(o => {
              const c = rankColor(o.def_rank)
              return (
                <div
                  key={o.week}
                  title={`Wk ${o.week} vs ${o.opponent}: #${o.def_rank} (${o.pts_per_game} pts/g)`}
                  style={{
                    background: c + '22',
                    border: `1px solid ${c}55`,
                    borderRadius: 5,
                    padding: '3px 7px',
                    fontSize: 11,
                    color: c,
                    fontWeight: 600,
                    cursor: 'default',
                  }}
                >
                  {o.opponent}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
