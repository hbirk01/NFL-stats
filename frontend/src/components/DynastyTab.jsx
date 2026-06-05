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
  const [subTab, setSubTab] = useState('roster') // 'roster' | 'standings'

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
          <div style={{ fontWeight: 700, fontSize: 16 }}>{league.league_name}</div>
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
        {['roster', 'needs', 'standings'].map(t => (
          <button key={t} onClick={() => setSubTab(t)} style={{ background: subTab === t ? 'var(--accent)' : 'none', border: 'none', color: subTab === t ? '#fff' : 'var(--muted)', padding: '5px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer', borderRadius: 6, textTransform: 'capitalize' }}>
            {t === 'roster' ? 'My Roster' : t === 'needs' ? 'Needs Analysis' : 'Standings'}
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
function TradeAnalyzerView() {
  const [allPlayers, setAllPlayers] = useState([])
  const [loading, setLoading] = useState(true)
  const [mySide, setMySide] = useState([])
  const [theirSide, setTheirSide] = useState([])
  const [mySearch, setMySearch] = useState('')
  const [theirSearch, setTheirSearch] = useState('')

  useEffect(() => {
    fetch('/api/dynasty/positional-rankings?position=ALL')
      .then(r => r.json())
      .then(d => { setAllPlayers(d.players || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  function addPlayer(side, player) {
    if (side === 'my' && mySide.length < 4 && !mySide.find(p => p.player_id === player.player_id && p.name === player.name)) {
      setMySide([...mySide, player])
      setMySearch('')
    } else if (side === 'their' && theirSide.length < 4 && !theirSide.find(p => p.player_id === player.player_id && p.name === player.name)) {
      setTheirSide([...theirSide, player])
      setTheirSearch('')
    }
  }

  function removePlayer(side, idx) {
    if (side === 'my') setMySide(mySide.filter((_, i) => i !== idx))
    else setTheirSide(theirSide.filter((_, i) => i !== idx))
  }

  const myValue = mySide.reduce((s, p) => s + (p.dynasty_value || 0), 0)
  const theirValue = theirSide.reduce((s, p) => s + (p.dynasty_value || 0), 0)
  const diff = myValue - theirValue
  const totalValue = myValue + theirValue

  const myAvgAge = mySide.length ? mySide.reduce((s, p) => s + (p.age || 25), 0) / mySide.length : 0
  const theirAvgAge = theirSide.length ? theirSide.reduce((s, p) => s + (p.age || 25), 0) / theirSide.length : 0
  const ageDiff = theirAvgAge - myAvgAge  // positive = you're getting younger

  // Percentage-based recommendation (more meaningful than raw value diff)
  const pctDiff = totalValue > 0 ? (diff / (totalValue / 2)) * 100 : 0
  let recommendation = ''
  let recColor = 'var(--muted)'
  let recEmoji = ''
  if (mySide.length && theirSide.length) {
    if (pctDiff >= 20)       { recommendation = 'Strong Win'; recColor = 'var(--green)'; recEmoji = '🔥' }
    else if (pctDiff >= 8)   { recommendation = 'Slight Win';  recColor = '#a3e635';     recEmoji = '✅' }
    else if (pctDiff >= -8)  { recommendation = 'Even Trade';  recColor = '#f59e0b';     recEmoji = '⚖️' }
    else if (pctDiff >= -20) { recommendation = 'Slight Loss'; recColor = '#f5a623';     recEmoji = '⚠️' }
    else                     { recommendation = 'Strong Loss'; recColor = 'var(--red)';  recEmoji = '🚨' }
  }

  function filterPlayers(search) {
    if (!search) return []
    const s = search.toLowerCase()
    return allPlayers.filter(p => p.name.toLowerCase().includes(s)).slice(0, 8)
  }

  if (loading) return <div className="spinner" />

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 24 }}>
        {/* My Side */}
        <TradeSide
          label="My Side"
          players={mySide}
          search={mySearch}
          onSearch={setMySearch}
          suggestions={filterPlayers(mySearch)}
          onAdd={p => addPlayer('my', p)}
          onRemove={idx => removePlayer('my', idx)}
          totalValue={myValue}
          color="var(--accent)"
        />
        {/* Their Side */}
        <TradeSide
          label="Their Side"
          players={theirSide}
          search={theirSearch}
          onSearch={setTheirSearch}
          suggestions={filterPlayers(theirSearch)}
          onAdd={p => addPlayer('their', p)}
          onRemove={idx => removePlayer('their', idx)}
          totalValue={theirValue}
          color="var(--wr)"
        />
      </div>

      {/* Value comparison */}
      {(mySide.length > 0 || theirSide.length > 0) && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 4 }}>MY SIDE</div>
              <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--accent)' }}>{myValue.toLocaleString()}</div>
            </div>
            <div style={{ textAlign: 'center' }}>
                {recommendation && (
                <div>
                  <div style={{ fontSize: 18, fontWeight: 800, color: recColor }}>{recEmoji} {recommendation}</div>
                  <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>{pctDiff > 0 ? '+' : ''}{pctDiff.toFixed(1)}% value differential</div>
                </div>
              )}
              {mySide.length > 0 && theirSide.length > 0 && Math.abs(ageDiff) > 1 && (
                <div style={{ fontSize: 12, color: ageDiff > 0 ? 'var(--green)' : '#f5a623', marginTop: 4 }}>
                  {ageDiff > 0 ? '⬇ You get younger' : '⬆ You get older'} by {Math.abs(ageDiff).toFixed(1)}yr avg
                </div>
              )}
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 4 }}>THEIR SIDE</div>
              <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--wr)' }}>{theirValue.toLocaleString()}</div>
            </div>
          </div>

          {/* Value bar */}
          {totalValue > 0 && (
            <div style={{ height: 10, background: 'var(--border)', borderRadius: 5, overflow: 'hidden', display: 'flex' }}>
              <div style={{ width: `${(myValue / totalValue) * 100}%`, background: 'var(--accent)', transition: 'width 0.3s' }} />
              <div style={{ width: `${(theirValue / totalValue) * 100}%`, background: 'var(--wr)', transition: 'width 0.3s' }} />
            </div>
          )}

          {mySide.length > 0 && theirSide.length > 0 && diff !== 0 ? (
            <div style={{ marginTop: 12, fontSize: 13, color: 'var(--muted)', textAlign: 'center' }}>
              Raw value difference: <span style={{ fontWeight: 700, color: diff > 0 ? 'var(--green)' : 'var(--red)' }}>{diff > 0 ? '+' : ''}{diff.toLocaleString()}</span>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}

function TradeSide({ label, players, search, onSearch, suggestions, onAdd, onRemove, totalValue, color }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div style={{ fontWeight: 700, fontSize: 15, color }}>{label}</div>
        <div style={{ fontSize: 13, color: 'var(--muted)' }}>Total: <span style={{ fontWeight: 700, color }}>{totalValue.toLocaleString()}</span></div>
      </div>

      {/* Search */}
      {players.length < 4 && (
        <div style={{ position: 'relative', marginBottom: 12 }}>
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
                  <span style={{ fontSize: 13, fontWeight: 600 }}>{p.name}</span>
                  <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 'auto' }}>{p.dynasty_value?.toLocaleString() || '—'}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Players */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minHeight: 80 }}>
        {players.length === 0 && (
          <div style={{ color: 'var(--muted)', fontSize: 13, textAlign: 'center', paddingTop: 20 }}>Add up to 4 players</div>
        )}
        {players.map((p, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', background: 'var(--surface2)', borderRadius: 8 }}>
            {posBadge(p.position)}
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{p.name}</div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Age {p.age ?? '?'}</div>
            </div>
            <div style={{ width: 80 }}>{dynastyValueBar(p.dynasty_value || 0)}</div>
            <button onClick={() => onRemove(i)} style={{ background: 'none', border: 'none', color: 'var(--red)', cursor: 'pointer', fontSize: 16, padding: '0 4px' }}>×</button>
          </div>
        ))}
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

  useEffect(() => {
    setLoading(true)
    fetch('/api/dynasty/positional-rankings?position=ALL')
      .then(r => r.json())
      .then(d => { setAllPlayers(d.players || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

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
        <span style={{ color: 'var(--muted)', fontSize: 12, marginLeft: 'auto' }}>{players.length} players</span>
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
