import { useState, useEffect, useMemo } from 'react'
import { POS_COLORS } from '../utils'
import PlayerDetail from './PlayerDetail'

const POSITIONS = ['ALL', 'QB', 'WR', 'RB', 'TE']
const AGE_BANDS = ['All Ages', 'Under 24', '24-27', '28+']
const VALID_POSITIONS = new Set(['QB', 'WR', 'RB', 'TE'])
const VIEWS = ['Rankings']

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
      <p className="section-subtitle">Startup ADP & trade values · sourced from FantasyCalc · updated daily</p>
      {rankingsView}
    </div>
  )
}

