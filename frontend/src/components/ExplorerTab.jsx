import { useState, useMemo } from 'react'
import PlayerCard from './PlayerCard'
import PlayerDetail from './PlayerDetail'
import { POS_COLORS } from '../utils'

const POSITIONS = ['ALL', 'QB', 'WR', 'RB', 'TE']

export default function ExplorerTab({ players, loading }) {
  const [pos, setPos] = useState('ALL')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(null)

  const filtered = useMemo(() => {
    let list = players
    if (pos !== 'ALL') list = list.filter(p => p.position === pos)
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(p =>
        p.player_display_name?.toLowerCase().includes(q) ||
        p.recent_team?.toLowerCase().includes(q)
      )
    }
    return list
  }, [players, pos, search])

  if (selected) {
    return <PlayerDetail player={selected} onBack={() => setSelected(null)} />
  }

  return (
    <div>
      <div className="section-title">Player Explorer</div>
      <p className="section-subtitle">2025 NFL season · {players.length} contributors · click any player for AI scouting report</p>

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
        <input
          className="search-input"
          placeholder="Search player or team…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <span style={{ color: 'var(--muted)', fontSize: 12, marginLeft: 'auto' }}>
          {filtered.length} players
        </span>
      </div>

      {loading
        ? <div className="spinner" />
        : filtered.length === 0
          ? <div className="empty">No players found</div>
          : (
            <div className="player-grid">
              {filtered.map(p => (
                <PlayerCard key={p.player_id} player={p} onClick={setSelected} />
              ))}
            </div>
          )
      }
    </div>
  )
}
