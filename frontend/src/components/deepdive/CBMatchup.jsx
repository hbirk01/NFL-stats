import { useState, useEffect } from 'react'
import { POS_COLORS } from '../../utils'

const GRADE_COLORS = {
  'A+': '#f59e0b', 'A': '#8b5cf6', 'B+': '#3b82f6', 'B': '#10b981',
  'C': '#6b7280', 'D': '#374151', 'F': '#ef4444', '—': '#6b7280',
}

const REC_COLORS = { Target: '#10b981', Avoid: '#ef4444', Neutral: '#6b7280' }

function QualityBar({ value, max = 100 }) {
  const color = value >= 65 ? '#10b981' : value >= 50 ? '#3b82f6' : value >= 35 ? '#f59e0b' : '#ef4444'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ flex: 1, height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${(value / max) * 100}%`, height: '100%', background: color, borderRadius: 3, transition: 'width 0.4s' }} />
      </div>
      <span style={{ fontSize: 11, color: 'var(--muted)', width: 28, textAlign: 'right' }}>{value.toFixed(0)}</span>
    </div>
  )
}

function CBCard({ cb }) {
  const gradeColor = GRADE_COLORS[cb.coverage_grade] || '#6b7280'
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ fontWeight: 700, fontSize: 15 }}>{cb.name}</div>
            {cb.slot && (
              <span style={{ fontSize: 10, fontWeight: 700, background: '#8b5cf622', color: '#8b5cf6', padding: '2px 6px', borderRadius: 4 }}>
                {cb.slot}
              </span>
            )}
          </div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>{cb.team} · CB</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 900, color: gradeColor, lineHeight: 1 }}>{cb.coverage_grade}</div>
          <div style={{ fontSize: 9, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>Coverage Grade</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 10 }}>
        {[
          ['Tgt/G', cb.targets_per_game?.toFixed(1)],
          ['Cmp%', cb.comp_pct ? (cb.comp_pct * 100).toFixed(0) + '%' : '—'],
          ['Yds/Tgt', cb.yards_per_target?.toFixed(1)],
        ].map(([label, val]) => (
          <div key={label} style={{ textAlign: 'center', background: 'var(--surface2)', borderRadius: 6, padding: '6px 4px' }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>{val ?? '—'}</div>
            <div style={{ fontSize: 10, color: 'var(--muted)' }}>{label}</div>
          </div>
        ))}
      </div>

      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
          <span>Coverage Quality</span>
          <span style={{ color: gradeColor }}>{cb.coverage_quality?.toFixed(0)}/100</span>
        </div>
        <QualityBar value={cb.coverage_quality || 0} />
      </div>

      {cb.passer_rating_allowed > 0 && (
        <div style={{ marginTop: 8, fontSize: 11, color: 'var(--muted)', display: 'flex', justifyContent: 'space-between' }}>
          <span>Passer Rating Allowed</span>
          <span style={{ fontWeight: 700, color: cb.passer_rating_allowed < 75 ? '#10b981' : cb.passer_rating_allowed < 90 ? '#f59e0b' : '#ef4444' }}>
            {cb.passer_rating_allowed.toFixed(1)}
          </span>
        </div>
      )}
    </div>
  )
}

export default function CBMatchup({ player, opponent }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const team = player?.recent_team || player?.team || ''

  useEffect(() => {
    if (!team || !opponent) return
    setLoading(true)
    setError('')
    fetch(`/api/cb/team-matchup?team=${encodeURIComponent(team)}&opponent=${encodeURIComponent(opponent)}&year=2025`)
      .then(r => { if (!r.ok) throw new Error('Failed to load'); return r.json() })
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [team, opponent])

  if (!opponent) return (
    <div style={{ color: 'var(--muted)', fontSize: 13, padding: '20px 0', textAlign: 'center' }}>
      Select an opponent from the schedule to see CB matchup analysis
    </div>
  )

  if (loading) return <div className="spinner" style={{ margin: '20px auto' }} />
  if (error) return <div style={{ color: 'var(--red)', padding: 20 }}>Error: {error}</div>
  if (!data) return null

  const scheme = data.scheme || {}
  const cbs = data.starting_cbs || []
  const routes = data.route_advice || []
  const targetRoutes = routes.filter(r => r.recommendation === 'Target')
  const avoidRoutes = routes.filter(r => r.recommendation === 'Avoid')
  const neutralRoutes = routes.filter(r => r.recommendation === 'Neutral')

  const isManHeavy = (scheme.pct_man || 0) >= 0.4
  const schemeColor = isManHeavy ? '#8b5cf6' : '#3b82f6'

  return (
    <div>
      {/* Header summary */}
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 18px', marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>
            {team} vs <span style={{ color: 'var(--accent)' }}>{opponent}</span> · CB Matchup
          </div>
          <span style={{ fontSize: 11, fontWeight: 700, color: schemeColor, background: schemeColor + '22', padding: '3px 10px', borderRadius: 6 }}>
            {isManHeavy ? '👤 Man-Heavy' : '🛡 Zone-Heavy'} {Math.round((isManHeavy ? scheme.pct_man : scheme.pct_zone) * 100)}%
          </span>
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)' }}>{data.summary}</div>

        {/* Scheme breakdown bar */}
        <div style={{ marginTop: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
            <span>👤 Man {Math.round((scheme.pct_man || 0) * 100)}%</span>
            <span>🛡 Zone {Math.round((scheme.pct_zone || 0) * 100)}%</span>
          </div>
          <div style={{ height: 8, background: 'var(--border)', borderRadius: 4, overflow: 'hidden', display: 'flex' }}>
            <div style={{ width: `${(scheme.pct_man || 0) * 100}%`, background: '#8b5cf6', transition: 'width 0.4s' }} />
            <div style={{ width: `${(scheme.pct_zone || 0) * 100}%`, background: '#3b82f6', transition: 'width 0.4s' }} />
          </div>
        </div>
      </div>

      {/* Starting CBs */}
      {cbs.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10 }}>
            {opponent} Starting Cornerbacks
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
            {cbs.map((cb, i) => <CBCard key={i} cb={cb} />)}
          </div>
        </div>
      )}

      {/* Route advice */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10 }}>
          Route Advice vs {opponent}'s Scheme
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {/* Target routes */}
          <div style={{ background: 'var(--surface)', border: '1px solid #10b98144', borderRadius: 10, padding: '12px 14px' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#10b981', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
              ✅ Target Routes
            </div>
            {targetRoutes.length === 0
              ? <div style={{ fontSize: 12, color: 'var(--muted)' }}>No strong route advantages</div>
              : targetRoutes.map((r, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, padding: '5px 8px', background: '#10b98111', borderRadius: 6 }}>
                  <span style={{ fontSize: 12, fontWeight: 600 }}>{r.route}</span>
                  <div style={{ textAlign: 'right' }}>
                    <span style={{ fontSize: 12, color: '#10b981', fontWeight: 700 }}>{r.expected_ypa} YPA</span>
                    <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 4 }}>(+{r.route_edge.toFixed(1)})</span>
                  </div>
                </div>
              ))}
          </div>

          {/* Avoid routes */}
          <div style={{ background: 'var(--surface)', border: '1px solid #ef444444', borderRadius: 10, padding: '12px 14px' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#ef4444', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
              🚫 Avoid Routes
            </div>
            {avoidRoutes.length === 0
              ? <div style={{ fontSize: 12, color: 'var(--muted)' }}>No strong route disadvantages</div>
              : avoidRoutes.map((r, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, padding: '5px 8px', background: '#ef444411', borderRadius: 6 }}>
                  <span style={{ fontSize: 12, fontWeight: 600 }}>{r.route}</span>
                  <div style={{ textAlign: 'right' }}>
                    <span style={{ fontSize: 12, color: '#ef4444', fontWeight: 700 }}>{r.expected_ypa} YPA</span>
                    <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 4 }}>({r.route_edge.toFixed(1)})</span>
                  </div>
                </div>
              ))}
          </div>
        </div>

        {/* Neutral routes */}
        {neutralRoutes.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6 }}>Neutral routes (scheme-independent)</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {neutralRoutes.map((r, i) => (
                <span key={i} style={{ fontSize: 11, background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 8px', color: 'var(--muted)' }}>
                  {r.route} · {r.expected_ypa} YPA
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8 }}>
        * CB quality based on 2025 PFR coverage stats. Route advice based on {Math.round((scheme.total_plays || 0))} plays of coverage data.
        CB assignments based on starting depth chart — actual coverage varies by play.
      </div>
    </div>
  )
}
