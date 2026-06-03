import { useState, useEffect } from 'react'
import { POS_COLORS, LEADERBOARD_METRICS, fmt, fmtInt } from '../utils'
import PlayerDetail from './PlayerDetail'

const POSITIONS = ['QB', 'WR', 'RB', 'TE']

export default function LeaderboardTab() {
  const [pos, setPos] = useState('WR')
  const [metric, setMetric] = useState('receiving_yards')
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(null)
  const [sortDir, setSortDir] = useState('desc')

  const metrics = LEADERBOARD_METRICS[pos] || []

  useEffect(() => {
    const first = metrics[0]?.key
    if (first && !metrics.find(m => m.key === metric)) {
      setMetric(first)
    }
  }, [pos])

  useEffect(() => {
    if (!metric) return
    setLoading(true)
    setSortDir('desc')
    fetch(`/api/leaderboard?position=${pos}&metric=${metric}&limit=25`)
      .then(r => r.json())
      .then(d => {
        setData(d.leaders || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [pos, metric])

  const color = POS_COLORS[pos]
  const metricLabel = metrics.find(m => m.key === metric)?.label || metric

  if (selected) {
    return <PlayerDetail player={selected} onBack={() => setSelected(null)} />
  }

  return (
    <div>
      <div className="section-title">Leaderboards</div>
      <p className="section-subtitle">Top performers by position-specific metrics</p>

      <div className="filters" style={{ marginBottom: 24 }}>
        {POSITIONS.map(p => (
          <button
            key={p}
            className={`filter-btn pos-${p} ${pos === p ? 'active' : ''}`}
            onClick={() => setPos(p)}
          >
            {p}
          </button>
        ))}
        <select
          className="metric-select"
          value={metric}
          onChange={e => setMetric(e.target.value)}
        >
          {metrics.map(m => (
            <option key={m.key} value={m.key}>{m.label}</option>
          ))}
        </select>
      </div>

      {loading
        ? <div className="spinner" />
        : (
          <div className="leaderboard-table">
            <div className="lb-row header">
              <div>#</div>
              <div>Player</div>
              <div
                style={{ textAlign: 'right', cursor: 'pointer', userSelect: 'none', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}
                onClick={() => setSortDir(d => d === 'desc' ? 'asc' : 'desc')}
              >
                {metricLabel}
                <span style={{ fontSize: 12, opacity: 0.7 }}>{sortDir === 'desc' ? '↓' : '↑'}</span>
              </div>
            </div>
            {(sortDir === 'asc' ? [...data].reverse() : data).map((p, i) => {
              const raw = p[metric]
              const display = raw == null ? '—' : metric.includes('pct') || metric === 'target_share' || metric === 'catch_percentage'
                ? fmt(metric === 'target_share' ? raw * 100 : raw) + '%'
                : Number.isInteger(raw) || Math.abs(raw) > 10
                  ? fmtInt(raw)
                  : fmt(raw)
              return (
                <div key={p.player_id} className="lb-row" onClick={() => setSelected(p)}>
                  <div className="lb-rank">{i + 1}</div>
                  <div className="lb-player">
                    {p.headshot_url && (
                      <img src={p.headshot_url} alt={p.player_display_name} onError={e => { e.target.style.display = 'none' }} />
                    )}
                    <div>
                      <div className="lb-player-name">{p.player_display_name}</div>
                      <div className="lb-player-meta">{p.recent_team} · {p.position}</div>
                    </div>
                  </div>
                  <div className="lb-value" style={{ color }}>{display}</div>
                </div>
              )
            })}
          </div>
        )
      }
    </div>
  )
}
