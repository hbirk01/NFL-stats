import { useState, useEffect, useMemo } from 'react'
import { POS_COLORS } from '../utils'
import PlayerDetail from './PlayerDetail'

// ─── Constants ───────────────────────────────────────────────────────────────
const POSITIONS = ['ALL', 'QB', 'WR', 'RB', 'TE']
const AGE_BANDS = ['All Ages', 'Under 24', '24-27', '28+']
const VALID_POSITIONS = new Set(['QB', 'WR', 'RB', 'TE'])
const VIEWS = ['Rankings', 'My Leagues', 'Trade Analyzer', 'Positional Rankings']

const TIER_COLORS = {
  'Elite':  '#f59e0b',
  'S-Tier': '#8b5cf6',
  'A-Tier': '#3b82f6',
  'B-Tier': '#10b981',
  'C-Tier': '#6b7280',
  'D-Tier': '#374151',
}

// ─── Shared helpers ───────────────────────────────────────────────────────────
function dynastyValueBar(value, maxVal = 10000) {
  const pct = Math.min(100, ((value || 0) / maxVal) * 100)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: 'linear-gradient(to right, var(--wr), var(--green))', borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 11, color: 'var(--muted)', width: 44, textAlign: 'right' }}>{(value || 0).toLocaleString()}</span>
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

function tierBadge(tier) {
  if (!tier) return null
  const color = TIER_COLORS[tier] || '#6b7280'
  return (
    <span style={{ fontSize: 10, fontWeight: 700, color, background: color + '22', padding: '2px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}>
      {tier}
    </span>
  )
}

function posBadge(pos) {
  const color = POS_COLORS[pos] || 'var(--accent)'
  return (
    <span style={{ fontSize: 11, fontWeight: 700, color, background: color + '22', padding: '2px 6px', borderRadius: 4 }}>
      {pos}
    </span>
  )
}

// ─── Rankings View (unchanged) ────────────────────────────────────────────────
function RankingsView({ data, loading, playerMap }) {
  const [pos, setPos] = useState('ALL')
  const [age, setAge] = useState('All Ages')
  const [sort, setSort] = useState('dynasty_rank')
  const [selected, setSelected] = useState(null)

  const filtered = useMemo(() => {
    let list = data.filter(d => d.dynasty_rank != null && VALID_POSITIONS.has(d.position))
    if (pos !== 'ALL') list = list.filter(d => d.position === pos)
    if (age === 'Under 24') list = list.filter(d => d.age != null && d.age < 24)
    else if (age === '24-27') list = list.filter(d => d.age != null && d.age >= 24 && d.age < 28)
    else if (age === '28+') list = list.filter(d => d.age != null && d.age >= 28)
    if (sort === 'dynasty_value') {
      list = [...list].sort((a, b) => (b[sort] ?? 0) - (a[sort] ?? 0))
    } else {
      list = [...list].sort((a, b) => (a[sort] ?? 9999) - (b[sort] ?? 9999))
    }
    return list
  }, [data, pos, age, sort])

  if (selected) return <PlayerDetail player={selected} onBack={() => setSelected(null)} />

  return (
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
              <div key={d.dynasty_rank} style={{ display: 'grid', gridTemplateColumns: '52px 48px 1fr 90px 90px 130px', alignItems: 'center', padding: '10px 16px', borderBottom: '1px solid var(--border)', cursor: fullPlayer ? 'pointer' : 'default', transition: 'background 0.1s', background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)' }}
                onMouseEnter={e => { if (fullPlayer) e.currentTarget.style.background = 'var(--surface2)' }}
                onMouseLeave={e => { e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)' }}
                onClick={() => fullPlayer && setSelected(fullPlayer)}>
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
}

// ─── My Leagues View ──────────────────────────────────────────────────────────
function MyLeaguesView() {
  const [username, setUsername] = useState(() => localStorage.getItem('gridiron_sleeper_username') || '')
  const [inputUsername, setInputUsername] = useState('')
  const [leagues, setLeagues] = useState([])
  const [leaguesLoading, setLeaguesLoading] = useState(false)
  const [leaguesError, setLeaguesError] = useState('')
  const [selectedLeague, setSelectedLeague] = useState(null)
  const [leagueData, setLeagueData] = useState(null)
  const [leagueLoading, setLeagueLoading] = useState(false)
  const [subTab, setSubTab] = useState('roster') // 'roster' | 'standings' | 'power'

  // Fetch leagues when username changes
  useEffect(() => {
    if (!username) return
    setLeaguesLoading(true)
    setLeaguesError('')
    fetch(`/api/sleeper/leagues?username=${encodeURIComponent(username)}`)
      .then(r => {
        if (!r.ok) throw new Error('User not found')
        return r.json()
      })
      .then(d => { setLeagues(d.leagues || []); setLeaguesLoading(false) })
      .catch(e => { setLeaguesError(e.message); setLeaguesLoading(false) })
  }, [username])

  // Fetch league detail when selected
  useEffect(() => {
    if (!selectedLeague) return
    setLeagueLoading(true)
    fetch(`/api/sleeper/league/${selectedLeague.league_id}?username=${encodeURIComponent(username)}`)
      .then(r => r.json())
      .then(d => { setLeagueData(d); setLeagueLoading(false) })
      .catch(() => setLeagueLoading(false))
  }, [selectedLeague])

  function handleConnect() {
    const trimmed = inputUsername.trim()
    if (!trimmed) return
    localStorage.setItem('gridiron_sleeper_username', trimmed)
    setUsername(trimmed)
    setSelectedLeague(null)
    setLeagueData(null)
  }

  function handleDisconnect() {
    localStorage.removeItem('gridiron_sleeper_username')
    setUsername('')
    setInputUsername('')
    setLeagues([])
    setSelectedLeague(null)
    setLeagueData(null)
  }

  // ── No username ──
  if (!username) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 300, gap: 16 }}>
        <div style={{ fontSize: 36 }}>🏆</div>
        <div style={{ fontSize: 20, fontWeight: 700 }}>Connect your Sleeper account</div>
        <div style={{ color: 'var(--muted)', fontSize: 14 }}>Enter your Sleeper username to view your leagues</div>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <input
            value={inputUsername}
            onChange={e => setInputUsername(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleConnect()}
            placeholder="Sleeper username"
            style={{ padding: '10px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface2)', color: 'var(--text)', fontSize: 14, width: 220, outline: 'none' }}
          />
          <button onClick={handleConnect} style={{ padding: '10px 20px', borderRadius: 8, background: 'var(--accent)', border: 'none', color: '#fff', fontWeight: 700, cursor: 'pointer', fontSize: 14 }}>
            Connect
          </button>
        </div>
      </div>
    )
  }

  // ── League detail ──
  if (selectedLeague && leagueData) {
    return <LeagueDetail league={leagueData} selectedLeague={selectedLeague} username={username} subTab={subTab} setSubTab={setSubTab} onBack={() => { setSelectedLeague(null); setLeagueData(null) }} />
  }

  // ── League list ──
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <div style={{ fontWeight: 700, fontSize: 16 }}>@{username}'s Leagues</div>
        <button onClick={handleDisconnect} style={{ fontSize: 12, color: 'var(--muted)', background: 'none', border: '1px solid var(--border)', borderRadius: 6, padding: '3px 10px', cursor: 'pointer' }}>
          Disconnect
        </button>
        {leagueLoading && <div className="spinner" style={{ width: 16, height: 16 }} />}
      </div>

      {leaguesLoading && <div className="spinner" />}
      {leaguesError && <div style={{ color: 'var(--red)', padding: 20 }}>Error: {leaguesError}. Check your username and try again.</div>}

      {!leaguesLoading && leagues.length === 0 && !leaguesError && (
        <div style={{ color: 'var(--muted)', padding: 40, textAlign: 'center' }}>No leagues found for this user.</div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
        {leagues.map(lg => (
          <div key={lg.league_id} onClick={() => { setSelectedLeague(lg); setSubTab('roster') }}
            style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 20, cursor: 'pointer', transition: 'border-color 0.15s, transform 0.1s' }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.transform = 'translateY(-2px)' }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.transform = 'translateY(0)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
              {lg.avatar
                ? <img src={`https://sleepercdn.com/avatars/thumbs/${lg.avatar}`} alt="" style={{ width: 44, height: 44, borderRadius: 10, objectFit: 'cover', flexShrink: 0 }} onError={e => e.target.style.display = 'none'} />
                : <div style={{ width: 44, height: 44, borderRadius: 10, background: 'var(--surface2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20 }}>🏈</div>
              }
              <div>
                <div style={{ fontWeight: 700, fontSize: 15 }}>{lg.name}</div>
                <div style={{ fontSize: 12, color: 'var(--muted)' }}>Season {lg.season} · {lg.num_teams} teams</div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{
                fontSize: 11, fontWeight: 700, padding: '3px 8px', borderRadius: 4,
                background: lg.status === 'in_season' ? 'var(--green)22' : lg.status === 'pre_draft' ? 'var(--accent)22' : 'var(--surface2)',
                color: lg.status === 'in_season' ? 'var(--green)' : lg.status === 'pre_draft' ? 'var(--accent)' : 'var(--muted)',
              }}>
                {lg.status || 'off_season'}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function dynastyGrade(value) {
  if (!value) return { grade: '—', color: 'var(--muted)' }
  if (value >= 8000) return { grade: 'A+', color: '#f59e0b' }
  if (value >= 6000) return { grade: 'A',  color: '#8b5cf6' }
  if (value >= 4000) return { grade: 'B+', color: '#3b82f6' }
  if (value >= 2500) return { grade: 'B',  color: '#10b981' }
  if (value >= 1500) return { grade: 'C+', color: '#6b7280' }
  if (value >= 800)  return { grade: 'C',  color: '#6b7280' }
  if (value >= 300)  return { grade: 'D',  color: '#374151' }
  return { grade: 'F', color: 'var(--red)' }
}

function NeedsAnalysis({ myTeam, standings }) {
  if (!myTeam || !standings?.length) return null

  const positions = ['QB', 'WR', 'RB', 'TE']
  // Compute average dynasty value per position across all teams
  const leagueAvg = {}
  for (const pos of positions) {
    const allTeamValues = standings.map(team => {
      const posPlayers = (team.players || []).filter(p => p.position === pos)
      return posPlayers.reduce((s, p) => s + (p.dynasty_value || 0), 0) / Math.max(posPlayers.length, 1)
    })
    leagueAvg[pos] = allTeamValues.reduce((s, v) => s + v, 0) / allTeamValues.length
  }

  const myStrengths = []
  const myWeaknesses = []

  for (const pos of positions) {
    const myPlayers = (myTeam.players || []).filter(p => p.position === pos)
    const myAvg = myPlayers.reduce((s, p) => s + (p.dynasty_value || 0), 0) / Math.max(myPlayers.length, 1)
    const diff = myAvg - leagueAvg[pos]
    const pct = leagueAvg[pos] > 0 ? Math.round((diff / leagueAvg[pos]) * 100) : 0
    const item = { pos, myAvg: Math.round(myAvg), leagueAvg: Math.round(leagueAvg[pos]), pct, players: myPlayers.length }
    if (pct >= 10) myStrengths.push(item)
    else if (pct <= -10) myWeaknesses.push(item)
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--green)', borderRadius: 12, padding: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--green)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 12 }}>✅ Strengths</div>
        {myStrengths.length === 0
          ? <div style={{ color: 'var(--muted)', fontSize: 13 }}>No dominant positional strengths</div>
          : myStrengths.map(s => (
            <div key={s.pos} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {posBadge(s.pos)}
                <span style={{ fontSize: 13 }}>{s.players} players</span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--green)' }}>+{s.pct}% vs league</span>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>{s.myAvg.toLocaleString()} avg val</div>
              </div>
            </div>
          ))}
      </div>

      <div style={{ background: 'var(--surface)', border: '1px solid var(--red)', borderRadius: 12, padding: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--red)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 12 }}>⚠️ Needs</div>
        {myWeaknesses.length === 0
          ? <div style={{ color: 'var(--muted)', fontSize: 13 }}>No clear positional weaknesses</div>
          : myWeaknesses.map(s => (
            <div key={s.pos} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {posBadge(s.pos)}
                <span style={{ fontSize: 13 }}>{s.players} players</span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--red)' }}>{s.pct}% vs league</span>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>{s.myAvg.toLocaleString()} avg val</div>
              </div>
            </div>
          ))}
      </div>

      {/* Roster value vs league */}
      <div style={{ gridColumn: '1 / -1', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 12 }}>Dynasty Value by Position</div>
        {positions.map(pos => {
          const myPlayers = (myTeam.players || []).filter(p => p.position === pos)
          const myTotal = myPlayers.reduce((s, p) => s + (p.dynasty_value || 0), 0)
          const leagueTotal = standings.reduce((s, t) => s + (t.players || []).filter(p => p.position === pos).reduce((ss, p) => ss + (p.dynasty_value || 0), 0), 0) / standings.length
          const maxVal = Math.max(myTotal, leagueTotal, 1)
          const color = POS_COLORS[pos] || 'var(--accent)'
          return (
            <div key={pos} style={{ marginBottom: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                <span style={{ color, fontWeight: 700 }}>{pos}</span>
                <span>{myTotal.toLocaleString()} vs {Math.round(leagueTotal).toLocaleString()} avg</span>
              </div>
              <div style={{ height: 6, background: 'var(--border)', borderRadius: 3, position: 'relative', overflow: 'hidden' }}>
                <div style={{ position: 'absolute', left: 0, height: '100%', width: `${(leagueTotal / maxVal) * 100}%`, background: 'var(--border)', borderRadius: 3, opacity: 0.6 }} />
                <div style={{ position: 'absolute', left: 0, height: '100%', width: `${(myTotal / maxVal) * 100}%`, background: color, borderRadius: 3, opacity: 0.85 }} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function LeagueDetail({ league, selectedLeague, username, subTab, setSubTab, onBack }) {
  const myTeam = league.standings?.find(s => s.is_me)

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <button onClick={onBack} style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 8, padding: '6px 12px', cursor: 'pointer', color: 'var(--text)', fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
          ← Back
        </button>
        <div>
          <div style={{ fontWeight: 700, fontSize: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
            {league.league_name}
            {league.is_superflex && <span style={{ fontSize: 11, fontWeight: 700, background: '#a78bfa33', color: '#a78bfa', borderRadius: 4, padding: '1px 7px' }}>SUPERFLEX</span>}
          </div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>Season {league.season} · {league.num_teams} teams · {league.status}</div>
        </div>
        {myTeam && (
          <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>Your record</div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{myTeam.wins}-{myTeam.losses}</div>
          </div>
        )}
      </div>

      {/* Sub-tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, background: 'var(--surface2)', borderRadius: 8, padding: 4, width: 'fit-content', border: '1px solid var(--border)' }}>
        {[['roster','My Roster'],['needs','Needs Analysis'],['standings','Standings'],['power','Power Rankings'],['tips','Trade Tips']].map(([t, label]) => (
          <button key={t} onClick={() => setSubTab(t)} style={{ background: subTab === t ? 'var(--accent)' : 'none', border: 'none', color: subTab === t ? '#fff' : 'var(--muted)', padding: '5px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer', borderRadius: 6 }}>
            {label}
          </button>
        ))}
      </div>

      {subTab === 'roster' && myTeam && <RosterView team={myTeam} />}
      {subTab === 'roster' && !myTeam && (
        <div style={{ color: 'var(--muted)', padding: 40, textAlign: 'center' }}>
          Your team not found. Make sure your username matches your Sleeper display name.
        </div>
      )}
      {subTab === 'needs' && <NeedsAnalysis myTeam={myTeam} standings={league.standings} />}
      {subTab === 'standings' && <StandingsView standings={league.standings} myTeam={myTeam} />}
      {subTab === 'power' && <PowerRankingsView leagueId={selectedLeague.league_id} standings={league.standings} />}
      {subTab === 'tips' && <TradeRecommendationsView myTeam={myTeam} standings={league.standings} />}
    </div>
  )
}

function RosterView({ team }) {
  const positions = ['QB', 'WR', 'RB', 'TE']
  const byPos = {}
  for (const pos of positions) byPos[pos] = []

  for (const p of team.players || []) {
    if (positions.includes(p.position)) {
      byPos[p.position].push(p)
    }
  }
  for (const pos of positions) {
    byPos[pos].sort((a, b) => (b.dynasty_value || 0) - (a.dynasty_value || 0))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {positions.map(pos => {
        const players = byPos[pos]
        if (!players.length) return null
        const color = POS_COLORS[pos] || 'var(--accent)'
        return (
          <div key={pos}>
            <div style={{ fontSize: 12, fontWeight: 700, color, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>{pos}s</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {players.map(p => (
                <PlayerRosterCard key={p.sleeper_id} player={p} posColor={color} />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function PlayerRosterCard({ player, posColor }) {
  const isHandcuff = player.is_top_dog === false && (player.adp_gap_to_teammate || 0) > 20
  const { grade, color: gradeColor } = dynastyGrade(player.dynasty_value)
  const mlScore = player.predicted_value_score_2026
  const mlColor = mlScore >= 65 ? 'var(--green)' : mlScore >= 55 ? '#a3e635' : mlScore >= 45 ? '#f5a623' : mlScore != null ? 'var(--red)' : 'var(--muted)'

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '40px 1fr 56px 80px 80px 70px 120px', alignItems: 'center', gap: 12, padding: '10px 14px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10 }}>
      <img src={player.headshot_url} alt="" style={{ width: 36, height: 36, borderRadius: '50%', objectFit: 'cover' }} onError={e => e.target.style.display = 'none'} />
      <div>
        <div style={{ fontWeight: 600, fontSize: 14, display: 'flex', alignItems: 'center', gap: 6 }}>
          {player.name}
          {isHandcuff && <span style={{ fontSize: 10, fontWeight: 700, background: '#f59e0b22', color: '#f59e0b', padding: '1px 5px', borderRadius: 4 }}>HANDCUFF</span>}
        </div>
        <div style={{ fontSize: 11, color: 'var(--muted)' }}>{player.team} · Age {player.age ?? '?'} · {player.years_exp != null ? `${player.years_exp}yr exp` : 'Rookie'}</div>
      </div>
      {/* Dynasty Grade */}
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 20, fontWeight: 900, color: gradeColor, lineHeight: 1 }}>{grade}</div>
        <div style={{ fontSize: 9, color: 'var(--muted)', textTransform: 'uppercase' }}>Grade</div>
      </div>
      {/* 2025 Stats */}
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>2025 PPG</div>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{player.ppg_2025 != null ? player.ppg_2025 : '—'}</div>
        {player.games_2025 != null && <div style={{ fontSize: 10, color: 'var(--muted)' }}>{player.games_2025}G</div>}
      </div>
      {/* Dynasty Value */}
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>Dyn. Val</div>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{player.dynasty_value ? player.dynasty_value.toLocaleString() : '—'}</div>
      </div>
      {/* 2026 ML Prediction */}
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>2026 ML</div>
        <div style={{ fontSize: 14, fontWeight: 700, color: mlColor }}>
          {mlScore != null ? mlScore.toFixed(0) : '—'}
        </div>
      </div>
      {/* Value bar */}
      <div>{player.dynasty_value ? dynastyValueBar(player.dynasty_value) : <span style={{ color: 'var(--muted)', fontSize: 12 }}>No dynasty data</span>}</div>
    </div>
  )
}

// ─── Trade Recommendations ────────────────────────────────────────────────────

function detectTeamMode(myTeam, standings) {
  const myPlayers = (myTeam.players || []).filter(p => (p.dynasty_value || 0) > 500)
  const top8 = [...myPlayers].sort((a, b) => (b.dynasty_value || 0) - (a.dynasty_value || 0)).slice(0, 8)

  const agesArr = top8.map(p => p.age).filter(Boolean)
  const avgAge = agesArr.length ? agesArr.reduce((s, a) => s + a, 0) / agesArr.length : 25

  const totalGames = (myTeam.wins || 0) + (myTeam.losses || 0)
  const winPct = totalGames > 0 ? myTeam.wins / totalGames : 0.5

  if (avgAge >= 27.5 || winPct < 0.33) return 'rebuild'
  if (winPct >= 0.6 && avgAge <= 26.5) return 'contend'
  return 'balanced'
}

function computePositionalNeeds(myTeam, standings) {
  const positions = ['QB', 'WR', 'RB', 'TE']
  const leagueAvg = {}
  for (const pos of positions) {
    const totals = standings.map(t =>
      (t.players || []).filter(p => p.position === pos).reduce((s, p) => s + (p.dynasty_value || 0), 0)
    )
    leagueAvg[pos] = totals.reduce((s, v) => s + v, 0) / Math.max(totals.length, 1)
  }
  const myTotals = {}
  for (const pos of positions) {
    myTotals[pos] = (myTeam.players || []).filter(p => p.position === pos).reduce((s, p) => s + (p.dynasty_value || 0), 0)
  }
  // Return positions sorted worst (biggest deficit) first
  return positions
    .map(pos => ({ pos, gap: myTotals[pos] - leagueAvg[pos] }))
    .sort((a, b) => a.gap - b.gap)
}

function generateRecommendations(myTeam, standings, mode) {
  const myPlayers = (myTeam.players || []).filter(p => (p.dynasty_value || 0) > 500)
  const otherTeams = standings.filter(s => s.roster_id !== myTeam.roster_id)
  const needs = computePositionalNeeds(myTeam, standings)
  const weakPositions = needs.slice(0, 2).map(n => n.pos) // top 2 weakest positions

  const recs = []

  if (mode === 'rebuild') {
    // Sell: aging producers (age >= 27, decent PPG, still has value)
    // Buy: young assets (age <= 24) of similar dynasty value
    const sellPool = myPlayers
      .filter(p => (p.age || 0) >= 27 && (p.ppg_2025 || 0) >= 7 && (p.dynasty_value || 0) >= 1500)
      .sort((a, b) => (b.dynasty_value || 0) - (a.dynasty_value || 0))

    for (const sell of sellPool.slice(0, 8)) {
      const base = sell.dynasty_value || 0
      const lo = base * 0.50
      const hi = base * 1.60
      for (const team of otherTeams) {
        const buyPool = (team.players || []).filter(p =>
          (p.age || 30) <= 25 &&
          (p.dynasty_value || 0) >= lo &&
          (p.dynasty_value || 0) <= hi &&
          p.position !== 'K' && p.position !== 'DEF'
        )
        for (const buy of buyPool) {
          const isNeedPos = weakPositions.includes(buy.position)
          recs.push({
            give: sell,
            get: buy,
            team: team.display_name || team.team_name || 'Opponent',
            mode: 'rebuild',
            valueSwing: (buy.dynasty_value || 0) - (sell.dynasty_value || 0),
            ageSwing: (sell.age || 0) - (buy.age || 0),
            ppgSwing: (sell.ppg_2025 || 0) - (buy.ppg_2025 || 0),
            isNeedPos,
            score: (isNeedPos ? 2000 : 0) + ((sell.age || 0) - (buy.age || 0)) * 100 + ((sell.dynasty_value || 0) - (buy.dynasty_value || 0)) * 0.5
          })
        }
      }
    }
  } else if (mode === 'contend') {
    // Sell: young stashes (high dynasty value, low PPG) — any age but producing below their value
    const sellPool = myPlayers
      .filter(p => (p.dynasty_value || 0) >= 1500 && (p.ppg_2025 || 0) <= 10 && (p.age || 30) <= 25)
      .sort((a, b) => (b.dynasty_value || 0) - (a.dynasty_value || 0))

    for (const sell of sellPool.slice(0, 8)) {
      const base = sell.dynasty_value || 0
      const lo = base * 0.50
      const hi = base * 1.55
      for (const team of otherTeams) {
        const buyPool = (team.players || []).filter(p =>
          (p.ppg_2025 || 0) >= 9 &&
          (p.dynasty_value || 0) >= lo &&
          (p.dynasty_value || 0) <= hi
        )
        for (const buy of buyPool) {
          const isNeedPos = weakPositions.includes(buy.position)
          recs.push({
            give: sell,
            get: buy,
            team: team.display_name || team.team_name || 'Opponent',
            mode: 'contend',
            valueSwing: (buy.dynasty_value || 0) - (sell.dynasty_value || 0),
            ageSwing: (sell.age || 0) - (buy.age || 0),
            ppgSwing: (buy.ppg_2025 || 0) - (sell.ppg_2025 || 0),
            isNeedPos,
            score: (isNeedPos ? 2000 : 0) + ((buy.ppg_2025 || 0) - (sell.ppg_2025 || 0)) * 200 + ((sell.dynasty_value || 0) - (buy.dynasty_value || 0)) * 0.3
          })
        }
      }
    }
  } else {
    // Balanced: trade surplus-position players for need-position players.
    // Value matching: within ±40% OR within 2500 absolute — whichever is more lenient.
    // For the biggest need (gap > 3000), also widen further to cover superflex QB gaps.
    const surplusPositions = needs.filter(n => n.gap > 200).map(n => n.pos)
    const positionsToSellFrom = surplusPositions.length > 0 ? surplusPositions : needs.slice(-2).map(n => n.pos)
    const bigNeedPositions = needs.filter(n => n.gap < -2000).map(n => n.pos)

    // Build flat sell pool: all players at surplus positions (keep starter + depth)
    const sellPool = myPlayers
      .filter(p => positionsToSellFrom.includes(p.position) && (p.dynasty_value || 0) >= 800)
      .sort((a, b) => (b.dynasty_value || 0) - (a.dynasty_value || 0))

    // Build flat buy pool across all need positions and all other teams
    const allBuyCandidates = []
    for (const needPos of weakPositions) {
      for (const team of otherTeams) {
        for (const p of (team.players || [])) {
          if (p.position === needPos && (p.dynasty_value || 0) >= 500) {
            allBuyCandidates.push({ ...p, _team: team })
          }
        }
      }
    }
    for (const sell of sellPool.slice(0, 8)) {
      const base = sell.dynasty_value || 0
      const isBigNeed = bigNeedPositions.length > 0

      for (const buy of allBuyCandidates) {
        const bval = buy.dynasty_value || 0
        const pctLo = isBigNeed ? base * 0.35 : base * 0.50
        const pctHi = isBigNeed ? base * 1.80 : base * 1.60
        const absOk  = Math.abs(bval - base) <= (isBigNeed ? 3500 : 2000)
        if (!((bval >= pctLo && bval <= pctHi) || absOk)) continue

        const posGapBonus = Math.abs(needs.find(n => n.pos === buy.position)?.gap || 0)
        // Penalise large value imbalance so fair trades rank above lopsided ones
        const valuePenalty = Math.abs(bval - base) * 0.15
        recs.push({
          give: sell,
          get: buy,
          team: buy._team.display_name || buy._team.team_name || 'Opponent',
          mode: 'balanced',
          valueSwing: bval - base,
          ageSwing: (sell.age || 0) - (buy.age || 0),
          ppgSwing: (buy.ppg_2025 || 0) - (sell.ppg_2025 || 0),
          isNeedPos: true,
          score: 2000 + posGapBonus * 0.25 - valuePenalty
        })
      }
    }
  }

  // Dedupe (give+get pair), limit same-giver to 3 results for variety, sort by score
  const seen = new Set()
  const giverCount = {}
  return recs
    .sort((a, b) => b.score - a.score)
    .filter(r => {
      const giveKey = r.give.name || r.give.player_id || r.give.sleeper_id
      const getKey  = r.get.name  || r.get.player_id  || r.get.sleeper_id
      const key = `${giveKey}-${getKey}`
      if (seen.has(key)) return false
      seen.add(key)
      const gc = giverCount[giveKey] || 0
      if (gc >= 3) return false
      giverCount[giveKey] = gc + 1
      return true
    })
    .slice(0, 15)
}

const MODE_META = {
  rebuild: { label: 'Rebuilding', color: '#f59e0b', bg: '#f59e0b22', tip: 'Sell aging vets for young dynasty assets. Trade PPG now for value later.' },
  contend: { label: 'Contending', color: '#22c55e', bg: '#22c55e22', tip: 'Sell dynasty stashes for proven producers. Win now while your window is open.' },
  balanced: { label: 'Balanced', color: '#3b82f6', bg: '#3b82f622', tip: 'Trade positional depth for positional need. Stay competitive while improving your roster.' },
}

const POS_COLOR = { QB: '#a78bfa', WR: '#60a5fa', RB: '#34d399', TE: '#fb923c' }

function TradeRecommendationsView({ myTeam, standings }) {
  const [selectedTeam, setSelectedTeam] = useState(myTeam || standings?.[0] || null)

  if (!standings?.length) {
    return <div style={{ color: 'var(--muted)', padding: 40, textAlign: 'center' }}>No league data available.</div>
  }

  const team = selectedTeam || myTeam || standings[0]
  const otherTeams = standings.filter(s => s.roster_id !== team.roster_id)

  const mode = detectTeamMode(team, standings)
  const meta = MODE_META[mode]
  const recs = generateRecommendations(team, standings, mode)
  const needs = computePositionalNeeds(team, standings)

  const posTag = pos => (
    <span style={{ background: (POS_COLOR[pos] || '#888') + '33', color: POS_COLOR[pos] || '#888', borderRadius: 4, padding: '1px 6px', fontSize: 11, fontWeight: 700 }}>{pos}</span>
  )

  const valBadge = (v, label) => {
    const positive = v > 0
    return (
      <span style={{ color: positive ? '#22c55e' : '#ef4444', fontSize: 11, fontWeight: 600 }}>
        {positive ? '+' : ''}{label}
      </span>
    )
  }

  return (
    <div>
      {/* Team picker */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16, overflowX: 'auto', paddingBottom: 4 }}>
        {standings.map(t => {
          const isSelected = t.roster_id === team.roster_id
          const isMe = t.is_me
          return (
            <button
              key={t.roster_id}
              onClick={() => setSelectedTeam(t)}
              style={{
                flexShrink: 0, padding: '5px 14px', borderRadius: 20, cursor: 'pointer',
                border: `1px solid ${isSelected ? 'var(--accent)' : 'var(--border)'}`,
                background: isSelected ? 'var(--accent)22' : 'transparent',
                color: isSelected ? 'var(--accent)' : 'var(--muted)',
                fontWeight: isSelected ? 700 : 500, fontSize: 12,
                outline: isMe ? `1px solid var(--accent)44` : 'none',
              }}
            >
              {t.display_name || t.team_name || `Team ${t.roster_id}`}
              {isMe && <span style={{ fontSize: 10, marginLeft: 4, opacity: 0.7 }}>you</span>}
            </button>
          )
        })}
      </div>
      {/* Mode banner */}
      <div style={{ background: meta.bg, border: `1px solid ${meta.color}44`, borderRadius: 10, padding: '14px 18px', marginBottom: 20, display: 'flex', alignItems: 'center', gap: 14 }}>
        <div style={{ background: meta.color, borderRadius: 6, padding: '4px 12px', color: '#000', fontWeight: 800, fontSize: 13 }}>{meta.label}</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>
            {team.display_name || team.team_name}
            {team.is_me && <span style={{ fontSize: 11, color: 'var(--accent)', marginLeft: 6 }}>you</span>}
          </div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>{meta.tip}</div>
        </div>
        <div style={{ fontSize: 12, color: 'var(--muted)', textAlign: 'right' }}>
          <div>{team.wins}-{team.losses} · {(team.wins / Math.max((team.wins + team.losses), 1) * 100).toFixed(0)}% win rate</div>
        </div>
      </div>

      {/* Positional heat map */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {needs.map(({ pos, gap }) => {
          const isWeak = gap < -500
          const isStrong = gap > 500
          return (
            <div key={pos} style={{ flex: 1, background: isWeak ? '#ef444422' : isStrong ? '#22c55e22' : 'var(--surface2)', border: `1px solid ${isWeak ? '#ef4444' : isStrong ? '#22c55e' : 'var(--border)'}44`, borderRadius: 8, padding: '10px 12px', textAlign: 'center' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: POS_COLOR[pos] || '#888', marginBottom: 4 }}>{pos}</div>
              <div style={{ fontSize: 11, color: isWeak ? '#ef4444' : isStrong ? '#22c55e' : 'var(--muted)', fontWeight: 600 }}>
                {isWeak ? 'Need' : isStrong ? 'Surplus' : 'Average'}
              </div>
              <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>
                {gap > 0 ? '+' : ''}{Math.round(gap / 100) * 100}
              </div>
            </div>
          )
        })}
      </div>

      {/* Trade cards */}
      {recs.length === 0 ? (
        <div style={{ color: 'var(--muted)', textAlign: 'center', padding: 40 }}>
          No trade matches found. Your roster may already be well-balanced for your mode.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {recs.map((rec, i) => (
            <div key={i} style={{ background: 'var(--surface2)', border: `1px solid ${rec.isNeedPos ? '#3b82f644' : 'var(--border)'}`, borderLeft: `3px solid ${rec.isNeedPos ? '#3b82f6' : meta.color}`, borderRadius: 10, padding: '14px 16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 0, marginBottom: 10 }}>
                {/* Give */}
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 600, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>You Give</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {rec.give.headshot_url && <img src={rec.give.headshot_url} style={{ width: 36, height: 36, borderRadius: '50%', objectFit: 'cover', background: 'var(--surface)' }} alt="" />}
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 14 }}>{rec.give.name}</div>
                      <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginTop: 2 }}>
                        {posTag(rec.give.position)}
                        <span style={{ fontSize: 11, color: 'var(--muted)' }}>Age {rec.give.age?.toFixed(0) || '?'}</span>
                        {rec.give.ppg_2025 != null && <span style={{ fontSize: 11, color: 'var(--muted)' }}>{rec.give.ppg_2025} PPG</span>}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 1 }}>{(rec.give.dynasty_value || 0).toLocaleString()} value</div>
                    </div>
                  </div>
                </div>

                {/* Arrow */}
                <div style={{ padding: '0 16px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                  <div style={{ fontSize: 20, color: 'var(--muted)' }}>⇄</div>
                  <div style={{ fontSize: 10, color: 'var(--muted)', textAlign: 'center', maxWidth: 80 }}>w/ {rec.team}</div>
                </div>

                {/* Get */}
                <div style={{ flex: 1, textAlign: 'right' }}>
                  <div style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 600, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>You Get</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end' }}>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 14 }}>{rec.get.name}</div>
                      <div style={{ display: 'flex', gap: 4, alignItems: 'center', justifyContent: 'flex-end', marginTop: 2 }}>
                        {rec.get.ppg_2025 != null && <span style={{ fontSize: 11, color: 'var(--muted)' }}>{rec.get.ppg_2025} PPG</span>}
                        <span style={{ fontSize: 11, color: 'var(--muted)' }}>Age {rec.get.age?.toFixed(0) || '?'}</span>
                        {posTag(rec.get.position)}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 1 }}>{(rec.get.dynasty_value || 0).toLocaleString()} value</div>
                    </div>
                    {rec.get.headshot_url && <img src={rec.get.headshot_url} style={{ width: 36, height: 36, borderRadius: '50%', objectFit: 'cover', background: 'var(--surface)' }} alt="" />}
                  </div>
                </div>
              </div>

              {/* Deltas row */}
              <div style={{ display: 'flex', gap: 16, paddingTop: 8, borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}>
                <div style={{ fontSize: 11 }}>
                  <span style={{ color: 'var(--muted)' }}>Value: </span>
                  {valBadge(rec.valueSwing, `${rec.valueSwing > 0 ? '+' : ''}${rec.valueSwing.toLocaleString()}`)}
                </div>
                {rec.ageSwing !== 0 && (
                  <div style={{ fontSize: 11 }}>
                    <span style={{ color: 'var(--muted)' }}>Age swing: </span>
                    {valBadge(mode === 'rebuild' ? rec.ageSwing : -rec.ageSwing, `${rec.ageSwing > 0 ? '-' : '+'}${Math.abs(rec.ageSwing).toFixed(0)} yrs younger`)}
                  </div>
                )}
                {rec.ppgSwing !== 0 && (
                  <div style={{ fontSize: 11 }}>
                    <span style={{ color: 'var(--muted)' }}>PPG swing: </span>
                    {valBadge(mode === 'rebuild' ? -rec.ppgSwing : rec.ppgSwing, `${rec.ppgSwing > 0 ? '+' : ''}${rec.ppgSwing.toFixed(1)} PPG`)}
                  </div>
                )}
                {rec.isNeedPos && (
                  <div style={{ fontSize: 11, color: '#3b82f6', fontWeight: 600 }}>Fills positional need</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Power Rankings ───────────────────────────────────────────────────────────

function PowerRankingsView({ leagueId, standings }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [highlight, setHighlight] = useState(null) // roster_id to show sparkline detail

  useEffect(() => {
    setLoading(true)
    fetch(`/api/sleeper/league/${leagueId}/power-rankings`)
      .then(r => { if (!r.ok) throw new Error('Failed'); return r.json() })
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [leagueId])

  if (loading) return <div className="spinner" />
  if (error) return <div style={{ color: 'var(--red)', padding: 20 }}>Could not load power rankings: {error}</div>

  const rankings = data?.rankings || []
  const completedWeeks = data?.completed_weeks || []

  if (!rankings.length) {
    return <div style={{ color: 'var(--muted)', textAlign: 'center', padding: 40 }}>No matchup data available yet for this league.</div>
  }

  // Build a map from roster_id → is_me using standings prop
  const standingsMap = {}
  if (standings) standings.forEach(s => { standingsMap[s.roster_id] = s })

  const maxPower = Math.max(...rankings.map(r => r.power_score))
  const maxPPG = Math.max(...rankings.map(r => r.ppg))

  function luckLabel(luck) {
    if (luck >= 2)  return { text: `+${luck.toFixed(1)} lucky`,   color: '#22c55e' }
    if (luck >= 0.5) return { text: `+${luck.toFixed(1)}`,        color: '#86efac' }
    if (luck >= -0.5) return { text: 'Even',                      color: 'var(--muted)' }
    if (luck >= -2)  return { text: `${luck.toFixed(1)}`,         color: '#f97316' }
    return { text: `${luck.toFixed(1)} unlucky`, color: '#ef4444' }
  }

  function Sparkline({ weekly, weeks }) {
    if (!weeks.length) return null
    const vals = weeks.map(w => weekly[w] || 0)
    const min = Math.min(...vals)
    const max = Math.max(...vals) || 1
    const w = 80, h = 28, pad = 3
    const pts = vals.map((v, i) => {
      const x = pad + (i / Math.max(vals.length - 1, 1)) * (w - pad * 2)
      const y = pad + (1 - (v - min) / (max - min || 1)) * (h - pad * 2)
      return `${x},${y}`
    }).join(' ')
    return (
      <svg width={w} height={h} style={{ display: 'block' }}>
        <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinejoin="round" />
        {vals.map((v, i) => {
          const x = pad + (i / Math.max(vals.length - 1, 1)) * (w - pad * 2)
          const y = pad + (1 - (v - min) / (max - min || 1)) * (h - pad * 2)
          return <circle key={i} cx={x} cy={y} r="2" fill="var(--accent)" />
        })}
      </svg>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700 }}>Power Rankings</div>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
            Composite score: 40% PPG + 35% Expected Wins + 25% Recent Form (last 3 wks)
          </div>
        </div>
        {completedWeeks.length > 0 && (
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            {completedWeeks.length} weeks completed · Wks {completedWeeks[0]}–{completedWeeks[completedWeeks.length - 1]}
          </div>
        )}
      </div>

      {/* Header */}
      <div style={{ display: 'grid', gridTemplateColumns: '36px 1fr 70px 90px 80px 80px 70px 90px', alignItems: 'center', padding: '8px 14px', fontSize: 10, color: 'var(--muted)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5, borderBottom: '2px solid var(--border)' }}>
        <div>#</div>
        <div>Team</div>
        <div style={{ textAlign: 'center' }}>Record</div>
        <div style={{ textAlign: 'center' }}>Exp W</div>
        <div style={{ textAlign: 'right' }}>PPG</div>
        <div style={{ textAlign: 'right' }}>Recent</div>
        <div style={{ textAlign: 'right' }}>Luck</div>
        <div style={{ textAlign: 'right' }}>Power</div>
      </div>

      {rankings.map((team, i) => {
        const standingTeam = standingsMap[team.roster_id]
        const isMe = standingTeam?.is_me || false
        const { text: luckText, color: luckColor } = luckLabel(team.luck)
        const powerPct = maxPower > 0 ? (team.power_score / maxPower) * 100 : 0
        const powerColor = powerPct >= 80 ? '#22c55e' : powerPct >= 60 ? '#3b82f6' : powerPct >= 40 ? '#f59e0b' : '#ef4444'
        const isExpanded = highlight === team.roster_id

        return (
          <div key={team.roster_id}>
            <div
              onClick={() => setHighlight(isExpanded ? null : team.roster_id)}
              style={{
                display: 'grid', gridTemplateColumns: '36px 1fr 70px 90px 80px 80px 70px 90px',
                alignItems: 'center', padding: '11px 14px',
                borderBottom: isExpanded ? 'none' : '1px solid var(--border)',
                background: isMe ? 'var(--accent)0d' : i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.012)',
                borderLeft: isMe ? '3px solid var(--accent)' : '3px solid transparent',
                cursor: 'pointer', transition: 'background 0.1s',
              }}
              onMouseEnter={e => { if (!isMe) e.currentTarget.style.background = 'rgba(255,255,255,0.04)' }}
              onMouseLeave={e => { if (!isMe) e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.012)' }}
            >
              {/* Rank */}
              <div style={{ fontWeight: 800, fontSize: 15, color: i < 3 ? ['#f59e0b','#9ca3af','#cd7f32'][i] : 'var(--muted)' }}>
                {i + 1}
              </div>

              {/* Team */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                {team.avatar
                  ? <img src={`https://sleepercdn.com/avatars/thumbs/${team.avatar}`} alt="" style={{ width: 28, height: 28, borderRadius: 6, objectFit: 'cover', flexShrink: 0 }} onError={e => e.target.style.display='none'} />
                  : <div style={{ width: 28, height: 28, borderRadius: 6, background: 'var(--surface2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12 }}>🏈</div>
                }
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: isMe ? 700 : 600, fontSize: 13, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {team.display_name}{isMe && <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--accent)' }}>YOU</span>}
                  </div>
                  <div style={{ height: 3, background: 'var(--border)', borderRadius: 2, marginTop: 3, overflow: 'hidden', width: 60 }}>
                    <div style={{ width: `${powerPct}%`, height: '100%', background: powerColor, borderRadius: 2 }} />
                  </div>
                </div>
              </div>

              {/* Record */}
              <div style={{ textAlign: 'center', fontSize: 13, fontWeight: 600 }}>
                {team.wins}-{team.losses}{team.ties > 0 ? `-${team.ties}` : ''}
              </div>

              {/* Expected Wins */}
              <div style={{ textAlign: 'center', fontSize: 13 }}>
                <span style={{ fontWeight: 600 }}>{team.expected_wins.toFixed(1)}</span>
                <span style={{ fontSize: 10, color: 'var(--muted)', display: 'block' }}>exp</span>
              </div>

              {/* PPG */}
              <div style={{ textAlign: 'right', fontSize: 13, fontWeight: 600 }}>
                {team.ppg > 0 ? team.ppg.toFixed(1) : '—'}
              </div>

              {/* Recent PPG */}
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{team.recent_ppg > 0 ? team.recent_ppg.toFixed(1) : '—'}</div>
                <Sparkline weekly={team.weekly_scores} weeks={completedWeeks.slice(-5)} />
              </div>

              {/* Luck */}
              <div style={{ textAlign: 'right', fontSize: 12, fontWeight: 700, color: luckColor }}>
                {luckText}
              </div>

              {/* Power Score */}
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 16, fontWeight: 800, color: powerColor }}>{team.power_score.toFixed(0)}</div>
                <div style={{ fontSize: 10, color: 'var(--muted)' }}>/ 100</div>
              </div>
            </div>

            {/* Expanded: weekly score breakdown */}
            {isExpanded && (
              <div style={{ padding: '10px 14px 14px', borderBottom: '1px solid var(--border)', background: isMe ? 'var(--accent)07' : 'rgba(255,255,255,0.018)' }}>
                <div style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 700, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  Weekly Scores — Wk {completedWeeks[0]} to {completedWeeks[completedWeeks.length - 1]}
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {completedWeeks.map(w => {
                    const pts = team.weekly_scores[w]
                    const allPts = rankings.map(r => r.weekly_scores[w] || 0)
                    const rank = allPts.filter(p => p > (pts || 0)).length + 1
                    const top3 = rank <= 3
                    const last3 = rank >= rankings.length - 2
                    return (
                      <div key={w} style={{
                        textAlign: 'center', padding: '6px 10px', borderRadius: 8, minWidth: 52,
                        background: top3 ? '#22c55e18' : last3 ? '#ef444418' : 'var(--surface2)',
                        border: `1px solid ${top3 ? '#22c55e40' : last3 ? '#ef444440' : 'var(--border)'}`,
                      }}>
                        <div style={{ fontSize: 10, color: 'var(--muted)' }}>Wk {w}</div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: top3 ? '#22c55e' : last3 ? '#ef4444' : 'var(--text)' }}>
                          {pts != null ? pts.toFixed(1) : '—'}
                        </div>
                        <div style={{ fontSize: 10, color: 'var(--muted)' }}>#{rank}</div>
                      </div>
                    )
                  })}
                </div>
                <div style={{ display: 'flex', gap: 20, marginTop: 10, fontSize: 12, color: 'var(--muted)' }}>
                  <span>PF: <strong style={{ color: 'var(--text)' }}>{team.fpts.toFixed(1)}</strong></span>
                  <span>PA: <strong style={{ color: 'var(--text)' }}>{team.fpts_against.toFixed(1)}</strong></span>
                  <span>Expected W: <strong style={{ color: 'var(--text)' }}>{team.expected_wins.toFixed(1)}</strong></span>
                  <span>Luck: <strong style={{ color: luckColor }}>{team.luck > 0 ? '+' : ''}{team.luck.toFixed(1)}</strong></span>
                </div>
              </div>
            )}
          </div>
        )
      })}

      {/* Legend */}
      <div style={{ display: 'flex', gap: 20, padding: '12px 14px', fontSize: 11, color: 'var(--muted)', borderTop: '1px solid var(--border)', marginTop: 4, flexWrap: 'wrap' }}>
        <span><strong>Exp W</strong> = expected wins vs every opponent each week</span>
        <span><strong>Luck</strong> = actual wins − expected wins</span>
        <span><strong>Recent</strong> = avg last 3 wks · click row to expand weekly breakdown</span>
      </div>
    </div>
  )
}

function StandingsView({ standings, myTeam }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '40px 1fr 100px 120px 120px', alignItems: 'center', padding: '10px 16px', borderBottom: '2px solid var(--border)', fontSize: 11, color: 'var(--muted)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        <div>#</div><div>Team</div><div style={{ textAlign: 'center' }}>Record</div>
        <div style={{ textAlign: 'right' }}>PF</div>
        <div style={{ textAlign: 'right' }}>PA</div>
      </div>
      {(standings || []).map((team, i) => {
        const isMe = team.is_me
        return (
          <div key={team.roster_id} style={{ display: 'grid', gridTemplateColumns: '40px 1fr 100px 120px 120px', alignItems: 'center', padding: '12px 16px', borderBottom: '1px solid var(--border)', background: isMe ? 'var(--accent)11' : i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)', borderLeft: isMe ? '3px solid var(--accent)' : '3px solid transparent' }}>
            <div style={{ fontWeight: 700, fontSize: 14, color: isMe ? 'var(--accent)' : 'var(--muted)' }}>#{i + 1}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {team.avatar
                ? <img src={`https://sleepercdn.com/avatars/thumbs/${team.avatar}`} alt="" style={{ width: 32, height: 32, borderRadius: 8, objectFit: 'cover', flexShrink: 0 }} onError={e => e.target.style.display = 'none'} />
                : <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--surface2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14 }}>🏈</div>
              }
              <div>
                <div style={{ fontWeight: isMe ? 700 : 600, fontSize: 14 }}>{team.display_name}{isMe && <span style={{ marginLeft: 6, fontSize: 11, color: 'var(--accent)' }}>YOU</span>}</div>
              </div>
            </div>
            <div style={{ textAlign: 'center', fontSize: 14, fontWeight: 600 }}>{team.wins}-{team.losses}{team.ties > 0 ? `-${team.ties}` : ''}</div>
            <div style={{ textAlign: 'right', fontSize: 14, color: 'var(--green)' }}>{team.fpts > 0 ? team.fpts.toLocaleString() : '—'}</div>
            <div style={{ textAlign: 'right', fontSize: 14, color: 'var(--muted)' }}>{team.fpts_against > 0 ? team.fpts_against.toLocaleString() : '—'}</div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Trade Analyzer View ──────────────────────────────────────────────────────
const DYNASTY_AGE_PEAK = { QB: 28, WR: 25, RB: 24, TE: 26 }

function ageTrajectory(pos, age) {
  if (!age || !pos) return 'unknown'
  const peak = DYNASTY_AGE_PEAK[pos] || 26
  if (age < peak - 2) return 'rising'
  if (age <= peak + 1) return 'peak'
  if (age <= peak + 3) return 'declining'
  return 'aging'
}

function trajectoryColor(t) {
  return { rising: '#22c55e', peak: '#3b82f6', declining: '#f59e0b', aging: '#ef4444', unknown: 'var(--muted)' }[t] || 'var(--muted)'
}

function TradeAnalyzerView() {
  const [mode, setMode] = useState('dynasty') // 'dynasty' | 'redraft'
  const [superflex, setSuperflex] = useState(false)
  const [allDynastyPlayers, setAllDynastyPlayers] = useState([])
  const [allRedraftPlayers, setAllRedraftPlayers] = useState([])
  const [allPicks, setAllPicks] = useState([])
  const [loading, setLoading] = useState(true)
  const [mySide, setMySide] = useState([])
  const [theirSide, setTheirSide] = useState([])
  const [mySearch, setMySearch] = useState('')
  const [theirSearch, setTheirSearch] = useState('')
  const [myPickOpen, setMyPickOpen] = useState(false)
  const [theirPickOpen, setTheirPickOpen] = useState(false)
  const [pickSearch, setPickSearch] = useState('')

  useEffect(() => {
    setLoading(true)
    const sfParam = superflex ? '&superflex=true' : ''
    Promise.all([
      fetch(`/api/dynasty/positional-rankings?position=ALL${sfParam}`).then(r => r.json()),
      fetch('/api/dynasty/picks').then(r => r.json()),
      fetch('/api/players?limit=300').then(r => r.json()),
    ]).then(([dynData, picksData, playersData]) => {
      setAllDynastyPlayers(dynData.players || [])
      setAllPicks(picksData.picks || [])
      // Enrich redraft players with computed value = weighted PPG
      const rp = (playersData.players || [])
        .filter(p => ['WR', 'RB', 'TE', 'QB'].includes(p.position))
        .map(p => {
          const games = p.games || 0
          const fpts = p.fantasy_points_ppr || 0
          const ppg = games > 0 ? fpts / games : 0
          const wppg = ppg * (games / 17)
          return {
            ...p,
            name: p.player_display_name,
            redraft_value: Math.round(wppg * 100), // scale to comparable units
            ppg: Math.round(ppg * 10) / 10,
            weighted_ppg: Math.round(wppg * 10) / 10,
          }
        })
        .sort((a, b) => b.redraft_value - a.redraft_value)
      setAllRedraftPlayers(rp)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [superflex])

  // Clear sides when switching modes
  function switchMode(m) {
    setMode(m)
    setMySide([])
    setTheirSide([])
    setMySearch('')
    setTheirSearch('')
  }

  const allPlayers = mode === 'dynasty' ? allDynastyPlayers : allRedraftPlayers

  function getValue(p) {
    return mode === 'dynasty' ? (p.dynasty_value || 0) : (p.redraft_value || 0)
  }

  function addPlayer(side, player) {
    const cap = 5
    if (side === 'my' && mySide.length < cap && !mySide.find(p => p.name === player.name)) {
      setMySide([...mySide, player]); setMySearch('')
    } else if (side === 'their' && theirSide.length < cap && !theirSide.find(p => p.name === player.name)) {
      setTheirSide([...theirSide, player]); setTheirSearch('')
    }
  }

  function removePlayer(side, idx) {
    if (side === 'my') setMySide(mySide.filter((_, i) => i !== idx))
    else setTheirSide(theirSide.filter((_, i) => i !== idx))
  }

  const myValue = mySide.reduce((s, p) => s + getValue(p), 0)
  const theirValue = theirSide.reduce((s, p) => s + getValue(p), 0)
  const diff = myValue - theirValue
  const totalValue = myValue + theirValue
  const pctDiff = totalValue > 0 ? (diff / (totalValue / 2)) * 100 : 0

  // Age analysis (dynasty only)
  const mySkillPlayers = mySide.filter(p => p.position !== 'PICK' && p.age)
  const theirSkillPlayers = theirSide.filter(p => p.position !== 'PICK' && p.age)
  const myAvgAge = mySkillPlayers.length ? mySkillPlayers.reduce((s, p) => s + p.age, 0) / mySkillPlayers.length : null
  const theirAvgAge = theirSkillPlayers.length ? theirSkillPlayers.reduce((s, p) => s + p.age, 0) / theirSkillPlayers.length : null
  const ageDiff = (myAvgAge && theirAvgAge) ? theirAvgAge - myAvgAge : null  // positive = you get younger

  // ML edge (dynasty only)
  const myAvgML = mySkillPlayers.length ? mySkillPlayers.reduce((s, p) => s + (p.predicted_value_score_2026 || 50), 0) / mySkillPlayers.length : null
  const theirAvgML = theirSkillPlayers.length ? theirSkillPlayers.reduce((s, p) => s + (p.predicted_value_score_2026 || 50), 0) / theirSkillPlayers.length : null

  // Position breakdown
  const POSITIONS_ORDER = ['QB', 'WR', 'RB', 'TE']
  function posBreakdown(side) {
    const counts = {}
    side.filter(p => p.position !== 'PICK').forEach(p => {
      counts[p.position] = (counts[p.position] || 0) + 1
    })
    return counts
  }
  const myPos = posBreakdown(mySide)
  const theirPos = posBreakdown(theirSide)

  // Verdict
  let recommendation = '', recColor = 'var(--muted)'
  if (mySide.length && theirSide.length) {
    if (pctDiff >= 20)       { recommendation = 'Strong Win';  recColor = '#22c55e' }
    else if (pctDiff >= 8)   { recommendation = 'Slight Win';  recColor = '#a3e635' }
    else if (pctDiff >= -8)  { recommendation = 'Even Trade';  recColor = '#f59e0b' }
    else if (pctDiff >= -20) { recommendation = 'Slight Loss'; recColor = '#f97316' }
    else                     { recommendation = 'Strong Loss'; recColor = '#ef4444' }
  }

  function filterPlayers(search) {
    if (!search) return []
    const s = search.toLowerCase()
    return allPlayers.filter(p => (p.name || '').toLowerCase().includes(s)).slice(0, 8)
  }

  // Key insight bullets
  const insights = []
  if (mySide.length && theirSide.length) {
    if (mode === 'dynasty') {
      if (ageDiff !== null && Math.abs(ageDiff) >= 1) {
        insights.push({
          text: ageDiff > 0
            ? `You get ${ageDiff.toFixed(1)} years younger on average — dynasty upside`
            : `You get ${Math.abs(ageDiff).toFixed(1)} years older — prioritize if win-now`,
          good: ageDiff > 0,
        })
      }
      if (myAvgML !== null && theirAvgML !== null && Math.abs(myAvgML - theirAvgML) >= 3) {
        const mlEdge = myAvgML - theirAvgML
        insights.push({
          text: mlEdge > 0
            ? `Your side has stronger 2026 ML projections (+${mlEdge.toFixed(0)} avg score)`
            : `Their side has stronger 2026 ML projections (+${Math.abs(mlEdge).toFixed(0)} avg score)`,
          good: mlEdge > 0,
        })
      }
    } else {
      const myPPG = mySide.reduce((s, p) => s + (p.ppg || 0), 0)
      const theirPPG = theirSide.reduce((s, p) => s + (p.ppg || 0), 0)
      const ppgDiff = myPPG - theirPPG
      if (Math.abs(ppgDiff) >= 1) {
        insights.push({
          text: ppgDiff > 0
            ? `Your side averages ${ppgDiff.toFixed(1)} more PPG — better weekly production`
            : `Their side averages ${Math.abs(ppgDiff).toFixed(1)} more PPG — better weekly production`,
          good: ppgDiff > 0,
        })
      }
    }
    // Position balance
    const allPos = new Set([...Object.keys(myPos), ...Object.keys(theirPos)])
    allPos.forEach(pos => {
      const myCount = myPos[pos] || 0
      const theirCount = theirPos[pos] || 0
      if (myCount > 0 && theirCount === 0) {
        insights.push({ text: `You're trading away ${pos} depth — check your roster need`, good: false })
      }
    })
  }

  if (loading) return <div className="spinner" />

  return (
    <div>
      {/* Mode toggle */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20, alignItems: 'center', flexWrap: 'wrap' }}>
        {[['dynasty', 'Dynasty'], ['redraft', 'Redraft / Regular']].map(([m, label]) => (
          <button key={m} onClick={() => switchMode(m)} style={{
            padding: '7px 18px', borderRadius: 20, border: `1px solid ${mode === m ? 'var(--accent)' : 'var(--border)'}`,
            background: mode === m ? 'var(--accent)22' : 'transparent',
            color: mode === m ? 'var(--accent)' : 'var(--muted)',
            fontWeight: 700, fontSize: 13, cursor: 'pointer',
          }}>
            {label}
          </button>
        ))}
        {mode === 'dynasty' && (
          <button onClick={() => { setSuperflex(s => !s); setMySide([]); setTheirSide([]) }} style={{
            padding: '7px 14px', borderRadius: 20,
            border: `1px solid ${superflex ? '#a78bfa' : 'var(--border)'}`,
            background: superflex ? '#a78bfa22' : 'transparent',
            color: superflex ? '#a78bfa' : 'var(--muted)',
            fontWeight: 700, fontSize: 13, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <span style={{ fontSize: 10 }}>{superflex ? '●' : '○'}</span> Superflex
          </button>
        )}
        <span style={{ fontSize: 12, color: 'var(--muted)', marginLeft: 4 }}>
          {mode === 'dynasty'
            ? superflex ? 'QB values weighted for superflex (FantasyCalc 2QB)' : 'Values from FantasyCalc · includes draft picks'
            : '2025 PPG weighted by games played (×games/17)'}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 24 }}>
        <TradeSide
          label="My Side" mode={mode}
          players={mySide} search={mySearch} onSearch={setMySearch}
          suggestions={filterPlayers(mySearch)}
          onAdd={p => addPlayer('my', p)} onRemove={idx => removePlayer('my', idx)}
          totalValue={myValue} color="var(--accent)"
          picks={mode === 'dynasty' ? allPicks : []}
          pickSearch={pickSearch} onPickSearch={setPickSearch}
          pickOpen={myPickOpen}
          onPickOpen={() => { setMyPickOpen(o => !o); setTheirPickOpen(false); setPickSearch('') }}
          onAddPick={p => { addPlayer('my', { ...p, player_id: `pick_${p.name}`, age: null }); setMyPickOpen(false) }}
        />
        <TradeSide
          label="Their Side" mode={mode}
          players={theirSide} search={theirSearch} onSearch={setTheirSearch}
          suggestions={filterPlayers(theirSearch)}
          onAdd={p => addPlayer('their', p)} onRemove={idx => removePlayer('their', idx)}
          totalValue={theirValue} color="var(--wr)"
          picks={mode === 'dynasty' ? allPicks : []}
          pickSearch={pickSearch} onPickSearch={setPickSearch}
          pickOpen={theirPickOpen}
          onPickOpen={() => { setTheirPickOpen(o => !o); setMyPickOpen(false); setPickSearch('') }}
          onAddPick={p => { addPlayer('their', { ...p, player_id: `pick_${p.name}`, age: null }); setTheirPickOpen(false) }}
        />
      </div>

      {/* Verdict panel */}
      {(mySide.length > 0 || theirSide.length > 0) && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 24 }}>

          {/* Value totals + verdict */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 2 }}>MY SIDE</div>
              <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--accent)' }}>
                {mode === 'dynasty' ? myValue.toLocaleString() : `${mySide.reduce((s, p) => s + (p.ppg || 0), 0).toFixed(1)} PPG`}
              </div>
              {mode === 'dynasty' && <div style={{ fontSize: 11, color: 'var(--muted)' }}>{myValue.toLocaleString()} pts</div>}
            </div>

            <div style={{ textAlign: 'center' }}>
              {recommendation ? (
                <>
                  <div style={{ fontSize: 20, fontWeight: 800, color: recColor }}>{recommendation}</div>
                  <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
                    {pctDiff > 0 ? '+' : ''}{pctDiff.toFixed(1)}% value differential
                  </div>
                </>
              ) : (
                <div style={{ fontSize: 13, color: 'var(--muted)' }}>Add players to both sides</div>
              )}
            </div>

            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 2 }}>THEIR SIDE</div>
              <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--wr)' }}>
                {mode === 'dynasty' ? theirValue.toLocaleString() : `${theirSide.reduce((s, p) => s + (p.ppg || 0), 0).toFixed(1)} PPG`}
              </div>
              {mode === 'dynasty' && <div style={{ fontSize: 11, color: 'var(--muted)' }}>{theirValue.toLocaleString()} pts</div>}
            </div>
          </div>

          {/* Value bar */}
          {totalValue > 0 && (
            <div style={{ height: 8, background: 'var(--border)', borderRadius: 4, overflow: 'hidden', display: 'flex', marginBottom: 20 }}>
              <div style={{ width: `${(myValue / totalValue) * 100}%`, background: 'var(--accent)', transition: 'width 0.4s' }} />
              <div style={{ width: `${(theirValue / totalValue) * 100}%`, background: 'var(--wr)', transition: 'width 0.4s' }} />
            </div>
          )}

          {/* Position breakdown */}
          {(mySide.length > 0 || theirSide.length > 0) && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
              {POSITIONS_ORDER.map(pos => {
                const my = myPos[pos] || 0
                const their = theirPos[pos] || 0
                if (!my && !their) return null
                const color = POS_COLORS[pos] || 'var(--accent)'
                return (
                  <div key={pos} style={{ background: color + '11', border: `1px solid ${color}33`, borderRadius: 8, padding: '6px 12px', textAlign: 'center', minWidth: 60 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color, marginBottom: 2 }}>{pos}</div>
                    <div style={{ fontSize: 13, fontWeight: 700 }}>
                      <span style={{ color: 'var(--accent)' }}>{my}</span>
                      <span style={{ color: 'var(--muted)' }}> / </span>
                      <span style={{ color: 'var(--wr)' }}>{their}</span>
                    </div>
                    <div style={{ fontSize: 9, color: 'var(--muted)' }}>you / them</div>
                  </div>
                )
              })}
              {mySide.some(p => p.position === 'PICK') || theirSide.some(p => p.position === 'PICK') ? (
                <div style={{ background: '#f59e0b11', border: '1px solid #f59e0b33', borderRadius: 8, padding: '6px 12px', textAlign: 'center', minWidth: 60 }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: '#f59e0b', marginBottom: 2 }}>PICK</div>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>
                    <span style={{ color: 'var(--accent)' }}>{mySide.filter(p => p.position === 'PICK').length}</span>
                    <span style={{ color: 'var(--muted)' }}> / </span>
                    <span style={{ color: 'var(--wr)' }}>{theirSide.filter(p => p.position === 'PICK').length}</span>
                  </div>
                  <div style={{ fontSize: 9, color: 'var(--muted)' }}>you / them</div>
                </div>
              ) : null}
            </div>
          )}

          {/* Dynasty-only: Age + ML row */}
          {mode === 'dynasty' && mySide.length > 0 && theirSide.length > 0 && (
            <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
              {ageDiff !== null && (
                <div style={{ background: 'var(--surface2)', borderRadius: 8, padding: '8px 14px', flex: 1, minWidth: 140 }}>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 2 }}>Avg Age</div>
                  <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                    <span style={{ color: 'var(--accent)', fontWeight: 700 }}>{myAvgAge?.toFixed(1)}</span>
                    <span style={{ color: 'var(--muted)', fontSize: 11 }}>→</span>
                    <span style={{ color: 'var(--wr)', fontWeight: 700 }}>{theirAvgAge?.toFixed(1)}</span>
                    <span style={{ fontSize: 11, color: ageDiff > 0 ? '#22c55e' : '#f97316', marginLeft: 'auto' }}>
                      {ageDiff > 0 ? '▼' : '▲'} {Math.abs(ageDiff).toFixed(1)}yr {ageDiff > 0 ? 'younger' : 'older'}
                    </span>
                  </div>
                </div>
              )}
              {myAvgML !== null && theirAvgML !== null && (
                <div style={{ background: 'var(--surface2)', borderRadius: 8, padding: '8px 14px', flex: 1, minWidth: 140 }}>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 2 }}>2026 ML Score</div>
                  <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                    <span style={{ color: 'var(--accent)', fontWeight: 700 }}>{myAvgML?.toFixed(0)}</span>
                    <span style={{ color: 'var(--muted)', fontSize: 11 }}>vs</span>
                    <span style={{ color: 'var(--wr)', fontWeight: 700 }}>{theirAvgML?.toFixed(0)}</span>
                    <span style={{ fontSize: 11, color: myAvgML > theirAvgML ? '#22c55e' : '#f97316', marginLeft: 'auto' }}>
                      {myAvgML > theirAvgML ? 'You edge ML' : 'They edge ML'}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Key insights */}
          {insights.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {insights.map((ins, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text)' }}>
                  <span style={{ color: ins.good ? '#22c55e' : '#f97316', flexShrink: 0 }}>{ins.good ? '✓' : '!'}</span>
                  {ins.text}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function TradeSide({ label, mode, players, search, onSearch, suggestions, onAdd, onRemove, totalValue, color,
  picks, pickSearch, onPickSearch, pickOpen, onPickOpen, onAddPick }) {

  const filteredPicks = picks
    ? picks.filter(p => !pickSearch || p.name.toLowerCase().includes(pickSearch.toLowerCase())).slice(0, 20)
    : []

  const totalDisplay = mode === 'dynasty'
    ? totalValue.toLocaleString()
    : `${players.reduce((s, p) => s + (p.ppg || 0), 0).toFixed(1)} PPG`

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div style={{ fontWeight: 700, fontSize: 15, color }}>{label}</div>
        <div style={{ fontSize: 13, color: 'var(--muted)' }}>Total: <span style={{ fontWeight: 700, color }}>{totalDisplay}</span></div>
      </div>

      {/* Search + Add Pick button */}
      {players.length < 6 && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <input
              value={search}
              onChange={e => onSearch(e.target.value)}
              placeholder="Search players..."
              style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface2)', color: 'var(--text)', fontSize: 13, outline: 'none', boxSizing: 'border-box' }}
            />
            {suggestions.length > 0 && (
              <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, zIndex: 100, boxShadow: '0 4px 20px rgba(0,0,0,0.4)', marginTop: 4 }}>
                {suggestions.map((p, i) => (
                  <div key={i} onClick={() => onAdd(p)}
                    style={{ padding: '8px 14px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10, borderBottom: i < suggestions.length - 1 ? '1px solid var(--border)' : 'none' }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--surface2)'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: POS_COLORS[p.position], background: (POS_COLORS[p.position] || '#888') + '22', padding: '1px 5px', borderRadius: 4 }}>{p.position}</span>
                    <span style={{ fontSize: 13, fontWeight: 600, flex: 1 }}>{p.name}</span>
                    {mode === 'dynasty'
                      ? <span style={{ fontSize: 11, color: 'var(--muted)' }}>{p.dynasty_value?.toLocaleString() || '—'}</span>
                      : <span style={{ fontSize: 11, color: 'var(--muted)' }}>{p.ppg?.toFixed(1) || '—'} PPG</span>
                    }
                  </div>
                ))}
              </div>
            )}
          </div>
          {/* Add Pick button */}
          <div style={{ position: 'relative' }}>
            <button
              onClick={onPickOpen}
              style={{
                padding: '8px 12px', borderRadius: 8, border: `1px solid ${pickOpen ? color : 'var(--border)'}`,
                background: pickOpen ? color + '22' : 'var(--surface2)', color: pickOpen ? color : 'var(--muted)',
                fontSize: 12, fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap',
              }}
            >
              🎟 + Pick
            </button>
            {pickOpen && (
              <div style={{ position: 'absolute', top: '100%', right: 0, width: 280, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, zIndex: 200, boxShadow: '0 8px 32px rgba(0,0,0,0.5)', marginTop: 6, overflow: 'hidden' }}>
                <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>
                  <input
                    autoFocus
                    value={pickSearch}
                    onChange={e => onPickSearch(e.target.value)}
                    placeholder="Search picks (e.g. 2026 1st)..."
                    style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--surface2)', color: 'var(--text)', fontSize: 12, outline: 'none', boxSizing: 'border-box' }}
                  />
                </div>
                <div style={{ maxHeight: 280, overflowY: 'auto' }}>
                  {filteredPicks.map((pk, i) => (
                    <div key={i} onClick={() => onAddPick(pk)}
                      style={{ padding: '8px 12px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: i < filteredPicks.length - 1 ? '1px solid var(--border)' : 'none' }}
                      onMouseEnter={e => e.currentTarget.style.background = 'var(--surface2)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: 10, fontWeight: 700, color: '#f59e0b', background: '#f59e0b22', padding: '1px 5px', borderRadius: 4 }}>PICK</span>
                        <span style={{ fontSize: 13, fontWeight: 600 }}>{pk.name}</span>
                      </div>
                      <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 600 }}>{pk.dynasty_value?.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Players + Picks */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minHeight: 80 }}>
        {players.length === 0 && (
          <div style={{ color: 'var(--muted)', fontSize: 13, textAlign: 'center', paddingTop: 20 }}>Add players or picks</div>
        )}
        {players.map((p, i) => {
          const isPick = p.position === 'PICK'
          const posColor = POS_COLORS[p.position] || 'var(--accent)'
          const traj = !isPick && mode === 'dynasty' ? ageTrajectory(p.position, p.age) : null
          const trajColor = trajectoryColor(traj)
          const mlScore = p.predicted_value_score_2026
          return (
            <div key={i} style={{
              padding: '10px 12px', background: 'var(--surface2)', borderRadius: 8,
              borderLeft: `3px solid ${isPick ? '#f59e0b' : posColor}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {isPick
                  ? <span style={{ fontSize: 11, fontWeight: 700, color: '#f59e0b', background: '#f59e0b22', padding: '2px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}>🎟 PICK</span>
                  : posBadge(p.position)
                }
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.name}</div>
                  {mode === 'dynasty' && !isPick && (
                    <div style={{ fontSize: 11, color: 'var(--muted)', display: 'flex', gap: 8, marginTop: 1 }}>
                      {p.age && <span>Age {p.age}</span>}
                      {traj && <span style={{ color: trajColor, fontWeight: 600 }}>{traj}</span>}
                      {p.team && <span>{p.team}</span>}
                    </div>
                  )}
                  {mode === 'redraft' && !isPick && (
                    <div style={{ fontSize: 11, color: 'var(--muted)', display: 'flex', gap: 8, marginTop: 1 }}>
                      {p.recent_team && <span>{p.recent_team}</span>}
                      {p.games != null && <span>{p.games}G</span>}
                    </div>
                  )}
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  {mode === 'dynasty' && !isPick && (
                    <>
                      <div style={{ fontSize: 12, fontWeight: 700 }}>{(p.dynasty_value || 0).toLocaleString()}</div>
                      {mlScore != null && (
                        <div style={{ fontSize: 10, color: mlScore >= 60 ? '#22c55e' : mlScore >= 50 ? '#f59e0b' : '#ef4444' }}>
                          ML {mlScore.toFixed(0)}
                        </div>
                      )}
                    </>
                  )}
                  {mode === 'dynasty' && isPick && (
                    <div style={{ fontSize: 12, fontWeight: 700 }}>{(p.dynasty_value || 0).toLocaleString()}</div>
                  )}
                  {mode === 'redraft' && !isPick && (
                    <>
                      <div style={{ fontSize: 12, fontWeight: 700 }}>{p.ppg?.toFixed(1)} PPG</div>
                      <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                        {p.fantasy_points_ppr ? Math.round(p.fantasy_points_ppr) + ' total' : ''}
                      </div>
                    </>
                  )}
                </div>
                <button onClick={() => onRemove(i)} style={{ background: 'none', border: 'none', color: 'var(--muted)', cursor: 'pointer', fontSize: 18, padding: '0 2px', lineHeight: 1, flexShrink: 0 }}>×</button>
              </div>
              {/* Mini value bar */}
              {mode === 'dynasty' && !isPick && p.dynasty_value > 0 && (
                <div style={{ marginTop: 6 }}>
                  <div style={{ height: 3, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ width: `${Math.min(100, (p.dynasty_value / 10000) * 100)}%`, height: '100%', background: posColor, borderRadius: 2 }} />
                  </div>
                </div>
              )}
              {mode === 'redraft' && !isPick && p.ppg > 0 && (
                <div style={{ marginTop: 6 }}>
                  <div style={{ height: 3, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ width: `${Math.min(100, (p.ppg / 35) * 100)}%`, height: '100%', background: posColor, borderRadius: 2 }} />
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Positional Rankings View ─────────────────────────────────────────────────
function PositionalRankingsView() {
  const [allPlayers, setAllPlayers] = useState([])
  const [loading, setLoading] = useState(true)
  const [pos, setPos] = useState('ALL')
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState('dynasty_value')
  const [superflex, setSuperflex] = useState(false)

  useEffect(() => {
    setLoading(true)
    const sfParam = superflex ? '&superflex=true' : ''
    fetch(`/api/dynasty/positional-rankings?position=ALL${sfParam}`)
      .then(r => r.json())
      .then(d => { setAllPlayers(d.players || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [superflex])

  const players = allPlayers
    .filter(p => pos === 'ALL' || p.position === pos)
    .filter(p => !search || p.name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      if (sortKey === 'age') return (a.age || 99) - (b.age || 99)
      if (sortKey === 'predicted_value_score_2026') return (b.predicted_value_score_2026 || 0) - (a.predicted_value_score_2026 || 0)
      return (b.dynasty_value || 0) - (a.dynasty_value || 0)
    })

  return (
    <div>
      <div className="filters" style={{ marginBottom: 12 }}>
        {POSITIONS.map(p => (
          <button key={p} className={`filter-btn pos-${p} ${pos === p ? 'active' : ''}`} onClick={() => setPos(p)}>{p}</button>
        ))}
        <button onClick={() => setSuperflex(s => !s)} style={{
          marginLeft: 'auto', padding: '4px 12px', borderRadius: 16,
          border: `1px solid ${superflex ? '#a78bfa' : 'var(--border)'}`,
          background: superflex ? '#a78bfa22' : 'transparent',
          color: superflex ? '#a78bfa' : 'var(--muted)',
          fontWeight: 700, fontSize: 12, cursor: 'pointer',
        }}>
          {superflex ? '● Superflex' : '○ Superflex'}
        </button>
        <span style={{ color: 'var(--muted)', fontSize: 12 }}>{players.length} players</span>
      </div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, alignItems: 'center' }}>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search player..."
          style={{ padding: '7px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface2)', color: 'var(--text)', fontSize: 13, outline: 'none', width: 200 }}
        />
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>Sort by:</span>
        {[['dynasty_value', 'Dynasty Value'], ['age', 'Age'], ['predicted_value_score_2026', '2026 ML']].map(([key, label]) => (
          <button key={key} onClick={() => setSortKey(key)} style={{ padding: '5px 10px', borderRadius: 6, border: `1px solid ${sortKey === key ? 'var(--accent)' : 'var(--border)'}`, background: sortKey === key ? 'var(--accent)22' : 'transparent', color: sortKey === key ? 'var(--accent)' : 'var(--muted)', fontSize: 11, fontWeight: 700, cursor: 'pointer' }}>{label}</button>
        ))}
      </div>

      {loading ? <div className="spinner" /> : (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
          {/* Header */}
          <div style={{ display: 'grid', gridTemplateColumns: '48px 44px 1fr 48px 56px 70px 120px 44px 60px 60px', alignItems: 'center', padding: '10px 14px', borderBottom: '2px solid var(--border)', fontSize: 11, color: 'var(--muted)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5 }}>
            <div>Rank</div><div>Pos</div><div>Player</div>
            <div style={{ textAlign: 'center' }}>Age</div>
            <div style={{ textAlign: 'center' }}>Grade</div>
            <div style={{ textAlign: 'center' }}>Tier</div>
            <div>Dynasty Value</div>
            <div style={{ textAlign: 'center' }}>Trend</div>
            <div style={{ textAlign: 'right' }}>PPG</div>
            <div style={{ textAlign: 'right' }}>2026</div>
          </div>
          {players.map((p, i) => {
            const color = POS_COLORS[p.position] || 'var(--accent)'
            const tierColor = TIER_COLORS[p.dynasty_tier] || '#6b7280'
            const { grade, color: gradeColor } = dynastyGrade(p.dynasty_value)
            const mlScore = p.predicted_value_score_2026
            const mlColor = mlScore >= 65 ? 'var(--green)' : mlScore >= 55 ? '#a3e635' : mlScore >= 45 ? '#f5a623' : 'var(--muted)'
            return (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: '48px 44px 1fr 48px 56px 70px 120px 44px 60px 60px', alignItems: 'center', padding: '9px 14px', borderBottom: '1px solid var(--border)', background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)' }}>
                <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--muted)' }}>#{i + 1}</div>
                <div>{posBadge(p.position)}</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {p.headshot_url && <img src={p.headshot_url} alt="" style={{ width: 28, height: 28, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} onError={e => e.target.style.display = 'none'} />}
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>{p.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>{p.team}</div>
                  </div>
                </div>
                <div style={{ textAlign: 'center', fontSize: 12 }}>{p.age ? p.age.toFixed(1) : '—'}</div>
                <div style={{ textAlign: 'center', fontWeight: 800, fontSize: 14, color: gradeColor }}>{grade}</div>
                <div style={{ textAlign: 'center' }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: tierColor, background: tierColor + '22', padding: '2px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}>
                    {p.dynasty_tier || '—'}
                  </span>
                </div>
                <div>{dynastyValueBar(p.dynasty_value || 0)}</div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  {p.dynasty_trend != null && trendBadge(p.dynasty_trend)}
                </div>
                <div style={{ textAlign: 'right', fontSize: 12, color: p.ppg_2025 ? 'var(--text)' : 'var(--muted)' }}>{p.ppg_2025 ?? '—'}</div>
                <div style={{ textAlign: 'right', fontSize: 12, fontWeight: 700, color: mlColor }}>
                  {mlScore != null ? mlScore.toFixed(0) : '—'}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─── Main DynastyTab ─────────────────────────────────────────────────────────
export default function DynastyTab() {
  const [rankingsData, setRankingsData] = useState([])
  const [rankingsLoading, setRankingsLoading] = useState(true)
  const [playerMap, setPlayerMap] = useState({})
  const [view, setView] = useState('Rankings')

  useEffect(() => {
    setRankingsLoading(true)
    Promise.all([
      fetch('/api/dynasty-adp').then(r => r.json()),
      fetch('/api/players?limit=300').then(r => r.json()),
    ]).then(([dynData, playerData]) => {
      setRankingsData(dynData.players || [])
      const map = {}
      for (const p of playerData.players || []) map[p.player_id] = p
      setPlayerMap(map)
      setRankingsLoading(false)
    }).catch(() => setRankingsLoading(false))
  }, [])

  return (
    <div>
      {/* Header */}
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
        {view === 'Rankings' && 'Startup ADP & trade values · sourced from FantasyCalc · updated daily'}
        {view === 'My Leagues' && 'Import your Sleeper leagues · view rosters & standings'}
        {view === 'Trade Analyzer' && 'Compare dynasty trade value using FantasyCalc data'}
        {view === 'Positional Rankings' && 'Dynasty tiers by position · sorted by dynasty value'}
      </p>

      {view === 'Rankings' && <RankingsView data={rankingsData} loading={rankingsLoading} playerMap={playerMap} />}
      {view === 'My Leagues' && <MyLeaguesView />}
      {view === 'Trade Analyzer' && <TradeAnalyzerView />}
      {view === 'Positional Rankings' && <PositionalRankingsView />}
    </div>
  )
}
