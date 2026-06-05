import { useState, useEffect } from 'react'
import { POS_COLORS } from '../utils'
import PlayerDetail from './PlayerDetail'

const POS_ORDER = { QB: 0, WR: 1, RB: 2, TE: 3 }

function scoreColor(score) {
  if (!score) return 'var(--muted)'
  if (score >= 65) return 'var(--green)'
  if (score >= 55) return '#a3e635'
  if (score >= 45) return '#f5a623'
  return 'var(--red)'
}

function PlayerCard({ p, onClick }) {
  const color = POS_COLORS[p.position] || 'var(--accent)'
  const pred = p.predicted_value_score_2026
  const sc = scoreColor(pred)
  const isHandcuff = p.is_top_dog === false && p.adp_gap_to_teammate > 20

  return (
    <div
      onClick={onClick}
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderLeft: `3px solid ${color}`,
        borderRadius: 10,
        padding: '10px 14px',
        cursor: onClick ? 'pointer' : 'default',
        display: 'grid',
        gridTemplateColumns: '44px 1fr auto auto',
        alignItems: 'center',
        gap: 10,
      }}
      onMouseEnter={e => onClick && (e.currentTarget.style.background = 'var(--surface2)')}
      onMouseLeave={e => onClick && (e.currentTarget.style.background = 'var(--surface)')}
    >
      {/* Headshot */}
      <img
        src={p.headshot_url}
        alt=""
        style={{ width: 40, height: 40, borderRadius: '50%', objectFit: 'cover' }}
        onError={e => {
          e.target.style.display = 'none'
          e.target.nextSibling && (e.target.nextSibling.style.display = 'flex')
        }}
      />

      {/* Identity */}
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 700, fontSize: 14 }}>{p.name}</span>
          {isHandcuff && (
            <span style={{ fontSize: 9, fontWeight: 700, background: '#f5a62333', color: '#f5a623', padding: '1px 5px', borderRadius: 3 }}>HANDCUFF</span>
          )}
        </div>
        <div style={{ fontSize: 11, color: 'var(--muted)', display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontWeight: 700, color, background: color + '22', padding: '1px 5px', borderRadius: 3 }}>{p.position}</span>
          <span>{p.team}</span>
          {p.age && <span>· {p.age}y</span>}
        </div>
      </div>

      {/* 2025 stats */}
      <div style={{ textAlign: 'center', minWidth: 70 }}>
        {p.ppg_2025 != null ? (
          <>
            <div style={{ fontSize: 15, fontWeight: 700 }}>{p.ppg_2025}</div>
            <div style={{ fontSize: 10, color: 'var(--muted)' }}>PPG · {p.games_2025}G</div>
          </>
        ) : (
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>No 2025 data</div>
        )}
      </div>

      {/* 2026 prediction */}
      <div style={{ textAlign: 'center', minWidth: 56 }}>
        {pred != null ? (
          <>
            <div style={{ fontSize: 18, fontWeight: 900, color: sc, lineHeight: 1 }}>{pred.toFixed(0)}</div>
            <div style={{ fontSize: 9, color: sc, fontWeight: 700, textTransform: 'uppercase' }}>
              {pred >= 65 ? 'Strong' : pred >= 55 ? 'Likely' : pred >= 45 ? 'Neutral' : 'Unlikely'}
            </div>
          </>
        ) : (
          <div style={{ fontSize: 10, color: 'var(--muted)' }}>—</div>
        )}
      </div>
    </div>
  )
}

function RosterSection({ title, players, onSelect }) {
  if (!players.length) return null
  const byPos = players.reduce((acc, p) => {
    const pos = p.position || 'OTH'
    if (!acc[pos]) acc[pos] = []
    acc[pos].push(p)
    return acc
  }, {})

  const sorted = Object.entries(byPos).sort(([a], [b]) => (POS_ORDER[a] ?? 9) - (POS_ORDER[b] ?? 9))

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10 }}>{title}</div>
      {sorted.map(([pos, grp]) => (
        <div key={pos} style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 10, color: POS_COLORS[pos] || 'var(--muted)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 5 }}>{pos}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {grp.sort((a, b) => (b.ppg_2025 ?? -1) - (a.ppg_2025 ?? -1)).map(p => (
              <PlayerCard key={p.sleeper_id} p={p} onClick={() => onSelect(p)} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export default function MyTeamTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState('team')  // 'team' | 'standings'
  const [selected, setSelected] = useState(null)
  const [leagueData, setLeagueData] = useState(null)

  useEffect(() => {
    fetch('/api/sleeper/league')
      .then(r => r.json())
      .then(d => {
        setLeagueData(d)
        setData(d.standings.find(s => s.is_me))
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  if (loading) return <div className="spinner" style={{ margin: '40px auto' }} />
  if (!data) return <div style={{ color: 'var(--muted)', padding: 24 }}>Could not load league data.</div>

  if (selected) {
    // Try to find matching player in our system for PlayerDetail
    // For now just go back
    return (
      <div>
        <button onClick={() => setSelected(null)} style={{ background: 'none', border: 'none', color: 'var(--muted)', cursor: 'pointer', fontSize: 13, marginBottom: 16 }}>← Back to roster</button>
        <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>{selected.name}</div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16 }}>{selected.position} · {selected.team}</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10 }}>
          {[
            ['2025 PPG', selected.ppg_2025?.toFixed(1) ?? '—'],
            ['2025 wPPG', selected.weighted_ppg_2025?.toFixed(1) ?? '—'],
            ['2025 Games', selected.games_2025 ?? '—'],
            ['Total Pts', selected.fantasy_points_2025?.toFixed(1) ?? '—'],
            ['Age', selected.age ?? '—'],
            ['Experience', selected.years_exp != null ? `${selected.years_exp}yr` : '—'],
            ['2026 Score', selected.predicted_value_score_2026?.toFixed(0) ?? '—'],
            ['Top Dog', selected.is_top_dog == null ? '—' : selected.is_top_dog ? 'Yes' : 'No'],
          ].map(([label, val]) => (
            <div key={label} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px' }}>
              <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 18, fontWeight: 700 }}>{val}</div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const VIEWS = ['My Team', 'Standings']

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 4 }}>
        <div className="section-title" style={{ marginBottom: 0 }}>Dynasty Men</div>
        <div style={{ display: 'flex', background: 'var(--surface2)', borderRadius: 6, overflow: 'hidden', border: '1px solid var(--border)' }}>
          {VIEWS.map(v => (
            <button key={v} onClick={() => setView(v === 'My Team' ? 'team' : 'standings')} style={{
              background: view === (v === 'My Team' ? 'team' : 'standings') ? 'var(--accent)' : 'none',
              border: 'none', color: view === (v === 'My Team' ? 'team' : 'standings') ? '#fff' : 'var(--muted)',
              padding: '5px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
            }}>{v}</button>
          ))}
        </div>
      </div>
      <p className="section-subtitle">
        {leagueData?.league_name} · 2025 season · {leagueData?.num_teams} teams
      </p>

      {view === 'team' && (
        <>
          {/* My record */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
            {[
              ['Record', `${data.wins}-${data.losses}`],
              ['Pts For', data.fpts?.toFixed(1)],
              ['Pts Against', data.fpts_against?.toFixed(1)],
              ['FAAB Left', `$${100 - (data.waiver_budget_used || 0)}`],
              ['Roster size', data.players.length],
            ].map(([label, val]) => (
              <div key={label} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 16px', textAlign: 'center' }}>
                <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>{label}</div>
                <div style={{ fontSize: 18, fontWeight: 700 }}>{val}</div>
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 10, marginBottom: 16, fontSize: 11, color: 'var(--muted)' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ fontWeight: 700, color: 'var(--text)' }}>2026 Score</span> = ML predicted value score (0-100)
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ background: '#f5a62333', color: '#f5a623', padding: '1px 5px', borderRadius: 3, fontSize: 9, fontWeight: 700 }}>HANDCUFF</span> = behind a teammate with better ADP by 20+ ranks
            </span>
          </div>

          <RosterSection title="Active Roster" players={data.players} onSelect={setSelected} />
          {data.taxi?.length > 0 && (
            <RosterSection title="Taxi Squad" players={data.taxi} onSelect={setSelected} />
          )}
        </>
      )}

      {view === 'standings' && (
        <div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {leagueData?.standings.map((team, i) => (
              <div key={team.roster_id} style={{
                background: team.is_me ? 'var(--accent)11' : 'var(--surface)',
                border: `1px solid ${team.is_me ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 10, padding: '10px 16px',
                display: 'grid', gridTemplateColumns: '28px 1fr auto auto auto', alignItems: 'center', gap: 12,
              }}>
                <div style={{ fontWeight: 800, fontSize: 16, color: 'var(--muted)', textAlign: 'center' }}>{i + 1}</div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14 }}>
                    {team.display_name} {team.is_me && <span style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700 }}>← You</span>}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>{team.players.length} players</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 15, fontWeight: 700 }}>{team.wins}-{team.losses}</div>
                  <div style={{ fontSize: 10, color: 'var(--muted)' }}>W-L</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 15, fontWeight: 700 }}>{team.fpts?.toFixed(0)}</div>
                  <div style={{ fontSize: 10, color: 'var(--muted)' }}>PF</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 15, fontWeight: 700 }}>{team.fpts_against?.toFixed(0)}</div>
                  <div style={{ fontSize: 10, color: 'var(--muted)' }}>PA</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
