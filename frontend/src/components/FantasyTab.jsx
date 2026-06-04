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

const VIEWS = ['Rankings', 'Value Picks', 'Strength of Schedule']

const PPG_THRESHOLD = { QB: 13, WR: 9, RB: 7, TE: 7, ALL: 8 }

function rankColor(rank) {
  if (!rank) return 'var(--muted)'
  if (rank <= 8) return 'var(--green)'
  if (rank <= 16) return '#a3e635'
  if (rank <= 24) return '#f5a623'
  return 'var(--red)'
}

function ValuePicksView({ onSelect }) {
  const [picks, setPicks] = useState([])
  const [loading, setLoading] = useState(true)
  const [pos, setPos] = useState('ALL')
  const [startersOnly, setStartersOnly] = useState(false)
  const [minGames, setMinGames] = useState(8)

  useEffect(() => {
    fetch('/api/value-picks')
      .then(r => r.json())
      .then(d => { setPicks(d.picks || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const filtered = picks
    .filter(p => pos === 'ALL' || p.position === pos)
    .filter(p => !startersOnly || (
      p.ppg != null && p.ppg >= (PPG_THRESHOLD[p.position] ?? 8) &&
      (p.games ?? 0) >= minGames
    ))

  if (loading) return <div className="spinner" />

  return (
    <div>
      <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16 }}>
        Players who outperformed their redraft ADP in 2025 — ranked by value score.
        <span style={{ fontSize: 11, display: 'block', marginTop: 3 }}>
          Pre-season redraft rank → actual 2025 PPG rank within position. Bigger jump = bigger steal.
        </span>
      </p>
      <div className="filters" style={{ marginBottom: 16 }}>
        {POSITIONS.map(p => (
          <button key={p} className={`filter-btn pos-${p} ${pos === p ? 'active' : ''}`} onClick={() => setPos(p)}>{p}</button>
        ))}
        <button
          onClick={() => setStartersOnly(s => !s)}
          style={{
            marginLeft: 8,
            padding: '4px 10px',
            borderRadius: 6,
            border: `1px solid ${startersOnly ? 'var(--accent)' : 'var(--border)'}`,
            background: startersOnly ? 'var(--accent)22' : 'transparent',
            color: startersOnly ? 'var(--accent)' : 'var(--muted)',
            fontSize: 11,
            fontWeight: 700,
            cursor: 'pointer',
            whiteSpace: 'nowrap',
          }}
        >
          ⚡ Starters Only
        </button>
        {startersOnly && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 6 }}>
            <span style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>Min games:</span>
            <input
              type="number"
              min={1}
              max={17}
              value={minGames}
              onChange={e => setMinGames(Math.max(1, Math.min(17, Number(e.target.value))))}
              style={{
                width: 44,
                padding: '2px 6px',
                borderRadius: 5,
                border: '1px solid var(--border)',
                background: 'var(--surface2)',
                color: 'var(--text)',
                fontSize: 12,
                fontWeight: 700,
                textAlign: 'center',
              }}
            />
            <span style={{ fontSize: 10, color: 'var(--muted)' }}>/ 17</span>
          </div>
        )}
        <span style={{ color: 'var(--muted)', fontSize: 12, marginLeft: 'auto' }}>{filtered.length} players</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {filtered.map((p, i) => {
          const color = POS_COLORS[p.position] || 'var(--accent)'
          const score = p.value_score ?? 0
          const scoreColor = score >= 65 ? 'var(--green)' : score >= 50 ? '#a3e635' : score >= 35 ? '#f5a623' : 'var(--red)'
          const rankDiff = (p.redraft_pos_rank ?? 0) - (p.performance_rank ?? 0)
          return (
            <div
              key={p.player_id || i}
              onClick={() => onSelect && onSelect(p)}
              style={{
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderLeft: `3px solid ${scoreColor}`,
                borderRadius: 10,
                padding: '12px 16px',
                cursor: 'pointer',
                display: 'grid',
                gridTemplateColumns: '32px 1fr auto auto',
                alignItems: 'center',
                gap: 12,
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--surface2)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'var(--surface)' }}
            >
              <div style={{ fontWeight: 800, fontSize: 15, color: 'var(--muted)', textAlign: 'center' }}>{i + 1}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                {p.headshot_url
                  ? <img src={p.headshot_url} alt="" style={{ width: 40, height: 40, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} onError={e => e.target.style.display = 'none'} />
                  : <div style={{ width: 40, height: 40, borderRadius: '50%', background: color + '22', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, color }}>{p.position?.[0]}</div>
                }
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.name}</div>
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                    <span style={{ fontWeight: 700, color, background: color + '22', padding: '1px 5px', borderRadius: 3, marginRight: 5 }}>{p.position}</span>
                    {p.team}
                  </div>
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, minWidth: 160 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>Redraft ADP</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--muted)' }}>{p.position}{p.redraft_pos_rank ?? '—'}</div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                    <div style={{ fontSize: 10, fontWeight: 800, color: rankDiff > 0 ? 'var(--green)' : 'var(--red)' }}>
                      {rankDiff > 0 ? `▲ ${rankDiff}` : `▼ ${Math.abs(rankDiff)}`}
                    </div>
                    <div style={{ fontSize: 18, color: rankDiff > 0 ? 'var(--green)' : 'var(--muted)' }}>→</div>
                  </div>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>Actual Rank</div>
                    <div style={{ fontSize: 16, fontWeight: 800, color: rankDiff > 0 ? 'var(--green)' : 'var(--text)' }}>{p.position}{p.performance_rank ?? '—'}</div>
                  </div>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                  {p.ppg != null ? <><b style={{ color: 'var(--text)' }}>{p.ppg.toFixed(1)}</b> PPG</> : '—'}
                  {p.games != null && (
                    <span style={{ marginLeft: 6, color: p.games < 8 ? 'var(--red)' : 'var(--muted)' }}>
                      · <b style={{ color: p.games < 8 ? 'var(--red)' : 'var(--text)' }}>{p.games}</b>G
                    </span>
                  )}
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, minWidth: 64 }}>
                <div style={{ fontSize: 22, fontWeight: 900, color: scoreColor, lineHeight: 1 }}>{score}</div>
                <div style={{ width: 48, height: 5, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{ width: `${score}%`, height: '100%', background: scoreColor, borderRadius: 3 }} />
                </div>
                <div style={{ fontSize: 9, fontWeight: 700, color: scoreColor, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  {score >= 65 ? 'Elite' : score >= 50 ? 'Good' : score >= 35 ? 'Neutral' : 'Bust'}
                </div>
              </div>
            </div>
          )
        })}
      </div>
      <div style={{ marginTop: 14, display: 'flex', gap: 16, fontSize: 11, color: 'var(--muted)' }}>
        {[['Elite Value', 'var(--green)', '65–100'], ['Good', '#a3e635', '50–64'], ['Neutral', '#f5a623', '35–49'], ['Bust', 'var(--red)', '0–34']].map(([label, color, range]) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 10, height: 10, background: color, borderRadius: 2 }} />
            <span>{label} <span style={{ opacity: 0.6 }}>({range})</span></span>
          </div>
        ))}
      </div>
    </div>
  )
}

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

      {view === 'Value Picks' && (
        <ValuePicksView onSelect={p => setSelected(p)} />
      )}

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
