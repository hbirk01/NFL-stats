import { useState, useEffect, useMemo } from 'react'
import { POS_COLORS } from '../utils'
import PlayerDetail from './PlayerDetail'

const POSITIONS = ['ALL', 'QB', 'WR', 'RB', 'TE']
const AGE_BANDS = ['All Ages', 'Under 24', '24-27', '28+']
const VALID_POSITIONS = new Set(['QB', 'WR', 'RB', 'TE'])
const VIEWS = ['Rankings', 'Value Picks']

function dynastyValueBar(value) {
  const max = 12000
  const pct = Math.min(100, (value / max) * 100)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: `linear-gradient(to right, var(--wr), var(--green))`, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 11, color: 'var(--muted)', width: 40, textAlign: 'right' }}>{value.toLocaleString()}</span>
    </div>
  )
}

function trendBadge(trend) {
  if (!trend) return null
  const up = trend > 0
  return (
    <span style={{ fontSize: 10, fontWeight: 700, color: up ? 'var(--green)' : 'var(--red)', marginLeft: 4 }}>
      {up ? '▲' : '▼'} {Math.abs(trend)}
    </span>
  )
}

const PPG_THRESHOLD = { QB: 13, WR: 9, RB: 7, TE: 7, ALL: 8 }

function ValuePicksView({ onSelect }) {
  const [picks, setPicks] = useState([])
  const [loading, setLoading] = useState(true)
  const [pos, setPos] = useState('ALL')
  const [startersOnly, setStartersOnly] = useState(false)

  useEffect(() => {
    fetch('/api/dynasty-value-picks')
      .then(r => r.json())
      .then(d => { setPicks(d.picks || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const filtered = picks
    .filter(p => pos === 'ALL' || p.position === pos)
    .filter(p => !startersOnly || (p.ppg != null && p.ppg >= (PPG_THRESHOLD[p.position] ?? 10)))

  if (loading) return <div className="spinner" />

  return (
    <div>
      <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16 }}>
        Players who outperformed their dynasty positional ADP in 2025 — ranked by value score.
        <span style={{ fontSize: 11, display: 'block', marginTop: 3 }}>
          Pre-season dynasty rank → actual 2025 PPG rank within position. Bigger jump = bigger steal.
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
        <span style={{ color: 'var(--muted)', fontSize: 12, marginLeft: 'auto' }}>{filtered.length} players</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {filtered.map((p, i) => {
          const color = POS_COLORS[p.position] || 'var(--accent)'
          const score = p.value_score ?? 0
          const scoreColor = score >= 65 ? 'var(--green)' : score >= 50 ? '#a3e635' : score >= 35 ? '#f5a623' : 'var(--red)'
          const rankDiff = (p.dynasty_pos_rank ?? 0) - (p.performance_rank ?? 0)

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
              {/* Rank number */}
              <div style={{ fontWeight: 800, fontSize: 15, color: 'var(--muted)', textAlign: 'center' }}>{i + 1}</div>

              {/* Player identity */}
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

              {/* ADP → Performance rank journey */}
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, minWidth: 160 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {/* Old ADP */}
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>Dynasty ADP</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--muted)' }}>{p.position}{p.dynasty_pos_rank ?? '—'}</div>
                  </div>

                  {/* Arrow with rank jump */}
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                    <div style={{ fontSize: 10, fontWeight: 800, color: rankDiff > 0 ? 'var(--green)' : 'var(--red)' }}>
                      {rankDiff > 0 ? `▲ ${rankDiff}` : `▼ ${Math.abs(rankDiff)}`}
                    </div>
                    <div style={{ fontSize: 18, color: rankDiff > 0 ? 'var(--green)' : 'var(--muted)' }}>→</div>
                  </div>

                  {/* New performance rank */}
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>Actual Rank</div>
                    <div style={{ fontSize: 16, fontWeight: 800, color: rankDiff > 0 ? 'var(--green)' : 'var(--text)' }}>{p.position}{p.performance_rank ?? '—'}</div>
                  </div>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                  {p.ppg != null ? <><b style={{ color: 'var(--text)' }}>{p.ppg.toFixed(1)}</b> PPG</> : '—'}
                </div>
              </div>

              {/* Value score */}
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
            <span>{label} ({range})</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function DynastyTab() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [pos, setPos] = useState('ALL')
  const [age, setAge] = useState('All Ages')
  const [sort, setSort] = useState('dynasty_rank')
  const [selected, setSelected] = useState(null)
  const [view, setView] = useState('Rankings')
  // We also need the full player data for clicking through to PlayerDetail
  const [playerMap, setPlayerMap] = useState({})

  useEffect(() => {
    setLoading(true)
    Promise.all([
      fetch('/api/dynasty-adp').then(r => r.json()),
      fetch('/api/players?limit=300').then(r => r.json()),
    ]).then(([dynData, playerData]) => {
      setData(dynData.players || [])
      const map = {}
      for (const p of playerData.players || []) map[p.player_id] = p
      setPlayerMap(map)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    // Always strip out draft picks (position === 'PICK') and unrecognised positions
    let list = data.filter(d => d.dynasty_rank != null && VALID_POSITIONS.has(d.position))
    if (pos !== 'ALL') list = list.filter(d => d.position === pos)
    if (age === 'Under 24') list = list.filter(d => d.age != null && d.age < 24)
    else if (age === '24-27') list = list.filter(d => d.age != null && d.age >= 24 && d.age < 28)
    else if (age === '28+') list = list.filter(d => d.age != null && d.age >= 28)
    // dynasty_value: higher = better → descending. ranks: lower = better → ascending.
    if (sort === 'dynasty_value') {
      list = [...list].sort((a, b) => (b[sort] ?? 0) - (a[sort] ?? 0))
    } else {
      list = [...list].sort((a, b) => (a[sort] ?? 9999) - (b[sort] ?? 9999))
    }
    return list
  }, [data, pos, age, sort])

  if (selected) {
    return <PlayerDetail player={selected} onBack={() => setSelected(null)} />
  }

  const rankingsView = (
    <div>
      <div className="filters" style={{ marginBottom: 20 }}>
        {POSITIONS.map(p => (
          <button key={p} className={`filter-btn pos-${p} ${pos === p ? 'active' : ''}`} onClick={() => setPos(p)}>{p}</button>
        ))}
        <select className="metric-select" value={age} onChange={e => setAge(e.target.value)}>
          {AGE_BANDS.map(b => <option key={b} value={b}>{b}</option>)}
        </select>
        <select className="metric-select" value={sort} onChange={e => setSort(e.target.value)}>
          <option value="dynasty_rank">Overall Rank</option>
          <option value="dynasty_pos_rank">Position Rank</option>
          <option value="dynasty_value">Dynasty Value ↓</option>
        </select>
        <span style={{ color: 'var(--muted)', fontSize: 12, marginLeft: 'auto' }}>{filtered.length} players</span>
      </div>
      {loading ? <div className="spinner" /> : (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '52px 48px 1fr 90px 90px 130px', alignItems: 'center', padding: '10px 16px', borderBottom: '2px solid var(--border)', fontSize: 11, color: 'var(--muted)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5 }}>
            <div>Rank</div><div>Pos</div><div>Player</div>
            <div style={{ textAlign: 'center' }}>Age</div>
            <div style={{ textAlign: 'center' }}>Pos Rank</div>
            <div>Dynasty Value</div>
          </div>
          {filtered.map((d, i) => {
            const color = POS_COLORS[d.position] || 'var(--accent)'
            const fullPlayer = d.player_id ? playerMap[d.player_id] : null
            return (
              <div key={d.dynasty_rank} style={{ display: 'grid', gridTemplateColumns: '52px 48px 1fr 90px 90px 130px', alignItems: 'center', padding: '10px 16px', borderBottom: '1px solid var(--border)', cursor: fullPlayer ? 'pointer' : 'default', transition: 'background 0.1s', background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)' }} onMouseEnter={e => { if (fullPlayer) e.currentTarget.style.background = 'var(--surface2)' }} onMouseLeave={e => { e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)' }} onClick={() => fullPlayer && setSelected(fullPlayer)}>
                <div style={{ fontWeight: 700, fontSize: 15 }}>#{d.dynasty_rank}</div>
                <div><span style={{ fontSize: 11, fontWeight: 700, color, background: color + '22', padding: '2px 6px', borderRadius: 4 }}>{d.position}</span></div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {fullPlayer?.headshot_url && <img src={fullPlayer.headshot_url} alt="" style={{ width: 32, height: 32, borderRadius: '50%', objectFit: 'cover' }} onError={e => e.target.style.display = 'none'} />}
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>{d.name}{trendBadge(d.dynasty_trend)}</div>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>{d.team}</div>
                  </div>
                </div>
                <div style={{ textAlign: 'center', fontSize: 13 }}>{d.age ? d.age.toFixed(1) : '—'}</div>
                <div style={{ textAlign: 'center', fontSize: 13, color: 'var(--muted)' }}>
                  {d.position} {d.dynasty_pos_rank}
                  {d.dynasty_tier && <span style={{ marginLeft: 4, fontSize: 10, background: 'var(--surface2)', padding: '1px 5px', borderRadius: 3 }}>T{d.dynasty_tier}</span>}
                </div>
                <div style={{ paddingRight: 8 }}>{d.dynasty_value ? dynastyValueBar(d.dynasty_value) : '—'}</div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 4 }}>
        <div className="section-title" style={{ marginBottom: 0 }}>Dynasty</div>
        <div style={{ display: 'flex', background: 'var(--surface2)', borderRadius: 6, overflow: 'hidden', border: '1px solid var(--border)' }}>
          {VIEWS.map(v => (
            <button key={v} onClick={() => setView(v)} style={{ background: view === v ? 'var(--accent)' : 'none', border: 'none', color: view === v ? '#fff' : 'var(--muted)', padding: '5px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
              {v}
            </button>
          ))}
        </div>
      </div>
      <p className="section-subtitle">
        {view === 'Rankings' ? 'Startup ADP & trade values · sourced from FantasyCalc · updated daily' : '2025 biggest value picks · ADP rank vs actual PPG performance'}
      </p>
      {view === 'Rankings' ? rankingsView : <ValuePicksView onSelect={p => { const full = playerMap[p.player_id]; if (full) setSelected(full) }} />}
    </div>
  )
}

