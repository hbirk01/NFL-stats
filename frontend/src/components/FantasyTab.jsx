import { useState, useEffect, useMemo } from 'react'
import { POS_COLORS } from '../utils'
import PlayerDetail from './PlayerDetail'
import SOSView from './SOSView'

const POSITIONS = ['ALL', 'QB', 'WR', 'RB', 'TE']

const SORT_OPTIONS = [
  { key: 'fantasy_points_ppr', label: 'PPR Pts' },
  { key: 'fantasy_points_std', label: 'Std Pts' },
  { key: 'fantasy_points_half', label: 'Half-PPR' },
  { key: 'ppg', label: 'Pts/Game' },
  { key: 'weekly_ceiling', label: 'Ceiling' },
  { key: 'weekly_floor', label: 'Floor' },
]

function fmt(v, dec = 1) {
  if (v == null || isNaN(v)) return '—'
  return Number(v).toFixed(dec)
}

function ConsistencyBar({ floor, ceiling, avg }) {
  if (floor == null || ceiling == null) return null
  const range = ceiling - floor || 1
  const avgPct = Math.min(100, Math.max(0, ((avg - floor) / range) * 100))
  return (
    <div style={{ position: 'relative', height: 6, background: 'var(--border)', borderRadius: 3, width: '100%', marginTop: 4 }}>
      <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: '100%', background: 'linear-gradient(to right, var(--red), var(--green))', borderRadius: 3, opacity: 0.35 }} />
      <div style={{ position: 'absolute', left: `${avgPct}%`, top: -2, width: 10, height: 10, borderRadius: '50%', background: 'var(--text)', transform: 'translateX(-50%)', border: '2px solid var(--surface)' }} />
    </div>
  )
}

function FantasyCard({ player, rank, sort, onClick }) {
  const pos = player.position
  const color = POS_COLORS[pos] || 'var(--accent)'

  const oppStats = useMemo(() => {
    if (pos === 'QB') return [
      { val: fmt(player.passing_yards, 0), lbl: 'Pass Yds' },
      { val: fmt(player.passing_tds, 0), lbl: 'Pass TDs' },
      { val: fmt(player.completion_percentage_above_expectation) + '%', lbl: 'CPOE' },
    ]
    if (pos === 'WR' || pos === 'TE') return [
      { val: fmt(player.target_share ? player.target_share * 100 : null) + '%', lbl: 'Tgt Share' },
      { val: fmt(player.wopr), lbl: 'WOPR' },
      { val: fmt(player.avg_separation) + 'yd', lbl: 'Sep.' },
    ]
    if (pos === 'RB') return [
      { val: fmt(player.carries, 0), lbl: 'Carries' },
      { val: fmt(player.yards_per_carry), lbl: 'YPC' },
      { val: fmt(player.rush_yards_over_expected_per_att), lbl: 'RYOE' },
    ]
    return []
  }, [player])

  return (
    <div
      className="player-card"
      style={{ '--pos-color': color, cursor: 'pointer' }}
      onClick={() => onClick(player)}
    >
      <div className="card-header">
        <div style={{ width: 28, color: 'var(--muted)', fontSize: 13, fontWeight: 700, flexShrink: 0 }}>#{rank}</div>
        {player.headshot_url
          ? <img className="headshot" src={player.headshot_url} alt={player.player_display_name} onError={e => { e.target.style.display = 'none' }} />
          : <div className="headshot-placeholder" style={{ fontSize: 16 }}>🏈</div>
        }
        <div>
          <div className="card-name">{player.player_display_name}</div>
          <div className="card-meta">{player.recent_team} · {player.position}</div>
        </div>
        <div className="pos-badge" style={{ background: color + '22', color, marginLeft: 'auto' }}>{pos}</div>
      </div>

      {/* Fantasy point totals */}
      <div className="stat-row">
        {[
          { val: fmt(player.fantasy_points_ppr, 1), lbl: 'PPR' },
          { val: fmt(player.fantasy_points_std, 1), lbl: 'STD' },
          { val: fmt(player.ppg, 1), lbl: 'PPG' },
        ].map(s => (
          <div key={s.lbl} className="stat-chip" style={sort.includes(s.lbl.toLowerCase()) || (s.lbl === 'PPR' && sort === 'fantasy_points_ppr') ? { border: `1px solid ${color}44` } : {}}>
            <span className="val">{s.val}</span>
            <span className="lbl">{s.lbl}</span>
          </div>
        ))}
        <div className="stat-chip">
          <span className="val" style={{ color: 'var(--red)', fontSize: 11 }}>{fmt(player.weekly_floor, 1)}</span>
          <span className="lbl">Floor</span>
        </div>
        <div className="stat-chip">
          <span className="val" style={{ color: 'var(--green)', fontSize: 11 }}>{fmt(player.weekly_ceiling, 1)}</span>
          <span className="lbl">Ceil.</span>
        </div>
      </div>

      {/* Consistency bar */}
      <div style={{ marginTop: 8, padding: '0 2px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>
          <span>Floor {fmt(player.weekly_floor, 1)}</span>
          <span style={{ color: 'var(--muted)' }}>Avg {fmt(player.ppg, 1)}</span>
          <span>Ceil. {fmt(player.weekly_ceiling, 1)}</span>
        </div>
        <ConsistencyBar floor={player.weekly_floor} ceiling={player.weekly_ceiling} avg={player.ppg} />
      </div>

      {/* Opportunity metrics */}
      {oppStats.length > 0 && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border)', display: 'flex', gap: 8 }}>
          {oppStats.map(s => (
            <div key={s.lbl} style={{ fontSize: 11, color: 'var(--muted)' }}>
              {s.lbl}: <b style={{ color: 'var(--text)' }}>{s.val}</b>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const VIEWS = ['Rankings', 'Strength of Schedule']

export default function FantasyTab() {
  const [pos, setPos] = useState('ALL')
  const [sort, setSort] = useState('fantasy_points_ppr')
  const [sortDir, setSortDir] = useState('desc')
  const [players, setPlayers] = useState([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)
  const [view, setView] = useState('Rankings')

  useEffect(() => {
    setLoading(true)
    fetch(`/api/fantasy?position=${pos}&sort=${sort}&limit=300`)
      .then(r => r.json())
      .then(d => { setPlayers(d.players || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [pos, sort])

  function handleSort(key) {
    if (key === sort) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    } else {
      setSort(key)
      setSortDir('desc')
    }
  }

  if (selected) {
    return <PlayerDetail player={selected} onBack={() => setSelected(null)} />
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 4 }}>
        <div className="section-title" style={{ marginBottom: 0 }}>Fantasy</div>
        <div style={{ display: 'flex', background: 'var(--surface2)', borderRadius: 6, overflow: 'hidden', border: '1px solid var(--border)' }}>
          {VIEWS.map(v => (
            <button
              key={v}
              onClick={() => setView(v)}
              style={{
                background: view === v ? 'var(--accent)' : 'none',
                border: 'none',
                color: view === v ? '#fff' : 'var(--muted)',
                padding: '5px 14px',
                fontSize: 12,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {v}
            </button>
          ))}
        </div>
      </div>
      <p className="section-subtitle">2025 season · floor/ceiling based on single-game PPR scores</p>

      {view === 'Strength of Schedule' && (
        <>
          <div className="filters" style={{ marginBottom: 16 }}>
            {['QB', 'WR', 'RB', 'TE'].map(p => (
              <button key={p} className={`filter-btn pos-${p} ${pos === p || (pos === 'ALL' && p === 'WR') ? 'active' : ''}`} onClick={() => setPos(p)}>{p}</button>
            ))}
          </div>
          <SOSView position={pos} />
        </>
      )}

      {view === 'Rankings' && (
        <>
          <div className="filters">
            {POSITIONS.map(p => (
              <button
                key={p}
                className={`filter-btn pos-${p} ${pos === p ? 'active' : ''}`}
                onClick={() => setPos(p)}
              >
                {p}
              </button>
            ))}
            <span style={{ color: 'var(--muted)', fontSize: 12, marginLeft: 'auto' }}>{players.length} players</span>
          </div>

          <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11, color: 'var(--muted)', alignSelf: 'center', marginRight: 4 }}>Sort:</span>
            {SORT_OPTIONS.map(o => {
              const active = sort === o.key
              return (
                <button
                  key={o.key}
                  onClick={() => handleSort(o.key)}
                  style={{
                    padding: '4px 10px',
                    borderRadius: 6,
                    fontSize: 11,
                    fontWeight: 600,
                    cursor: 'pointer',
                    border: active ? '1px solid var(--accent)' : '1px solid var(--border)',
                    background: active ? 'var(--accent)22' : 'var(--surface)',
                    color: active ? 'var(--accent)' : 'var(--muted)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  {o.label}
                  {active && <span style={{ fontSize: 10 }}>{sortDir === 'desc' ? '↓' : '↑'}</span>}
                </button>
              )
            })}
          </div>

          {loading
            ? <div className="spinner" />
            : players.length === 0
              ? <div className="empty">No data</div>
              : (
                <div className="player-grid">
                  {(sortDir === 'asc' ? [...players].reverse() : players).map((p, i) => (
                    <FantasyCard key={p.player_id} player={p} rank={i + 1} sort={sort} onClick={setSelected} />
                  ))}
                </div>
              )
          }
        </>
      )}
    </div>
  )
}
