import { useState, useEffect } from 'react'

const FEATURE_LABELS = {
  shotgun: 'Shotgun formation',
  down: 'Down',
  off_wr: 'WR count (personnel)',
  posteam_timeouts_remaining: 'Offense timeouts left',
  ydstogo: 'Distance to go',
  qtr: 'Quarter',
  off_ol: 'Extra OL (personnel)',
  score_differential: 'Score differential',
  no_huddle: 'No-huddle',
  game_seconds_remaining: 'Time remaining',
  off_rb: 'RB count (personnel)',
  posteam: 'Offense identity',
  off_te: 'TE count (personnel)',
  yardline_100: 'Field position',
  defteam_timeouts_remaining: 'Defense timeouts left',
  defteam: 'Defense identity',
  is_home: 'Home / away',
}

function statCard(label, value, sub) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 18px', flex: 1, minWidth: 140 }}>
      <div style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 800 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function accuracyColor(acc, min, max) {
  const t = max > min ? (acc - min) / (max - min) : 0.5
  // red (low) -> yellow -> green (high)
  const r = t < 0.5 ? 255 : Math.round(255 - (t - 0.5) * 2 * 155)
  const g = t < 0.5 ? Math.round(t * 2 * 200) : 200
  return `rgb(${r}, ${g}, 90)`
}

function PredictabilityBar({ team, avg, min, max }) {
  const pct = max > 0 ? (team.accuracy / max) * 100 : 0
  const avgPct = max > 0 ? (avg / max) * 100 : 0
  const color = accuracyColor(team.accuracy, min, max)
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '46px 1fr 130px', alignItems: 'center', gap: 12, padding: '6px 16px' }}>
      <div style={{ fontWeight: 700, fontSize: 13 }}>{team.team}</div>
      <div style={{ position: 'relative', height: 16, background: 'var(--surface2)', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.3s' }} />
        <div style={{ position: 'absolute', left: `${avgPct}%`, top: 0, bottom: 0, width: 1, background: 'rgba(255,255,255,0.5)' }} />
      </div>
      <div style={{ fontSize: 12, color: 'var(--muted)', textAlign: 'right' }}>
        {(team.accuracy * 100).toFixed(1)}% · {team.plays} plays
      </div>
    </div>
  )
}

export default function PlayPredictabilityTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [sort, setSort] = useState('predictability_rank')

  useEffect(() => {
    setLoading(true)
    fetch('/api/play-predictability')
      .then(r => {
        if (!r.ok) throw new Error(r.status === 503 ? 'Model not generated yet — run backend/ml/play_prediction.py' : 'Failed to load')
        return r.json()
      })
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  if (loading) return <div className="spinner" />
  if (error) return <div style={{ color: 'var(--red)', padding: 40, textAlign: 'center' }}>{error}</div>
  if (!data) return null

  const teams = [...data.teams]
  if (sort === 'predictability_rank') teams.sort((a, b) => a.predictability_rank - b.predictability_rank)
  else if (sort === 'pass_rate') teams.sort((a, b) => b.actual_pass_rate - a.actual_pass_rate)
  else if (sort === 'alpha') teams.sort((a, b) => a.team.localeCompare(b.team))

  const accuracies = data.teams.map(t => t.accuracy)
  const min = Math.min(...accuracies)
  const max = Math.max(...accuracies)
  const avg = accuracies.reduce((s, v) => s + v, 0) / accuracies.length

  const maxImportance = Math.max(...data.feature_importance.map(f => f.importance))
  const maxPassRate = Math.max(...data.pass_rate_by_down.map(d => d.pass_rate))

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 20, fontWeight: 800, marginBottom: 4 }}>Play-Calling Predictability</div>
        <div style={{ fontSize: 13, color: 'var(--muted)' }}>
          XGBoost run/pass classifier trained on {data.train_years[0]}-{data.train_years.at(-1)} PBP ({data.n_train.toLocaleString()} plays),
          evaluated on the held-out {data.test_year} season ({data.n_test.toLocaleString()} plays). Team accuracy = how often the model's
          predicted call matched the offense's actual call — low accuracy means that offense defies typical situational tendencies more often.
        </div>
      </div>

      {/* Overall model stats */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 28, flexWrap: 'wrap' }}>
        {statCard('Model Accuracy', `${(data.overall.accuracy * 100).toFixed(1)}%`, `vs ${(data.overall.majority_class_baseline * 100).toFixed(1)}% majority-class baseline`)}
        {statCard('AUC', data.overall.auc.toFixed(3))}
        {statCard('Log Loss', data.overall.log_loss.toFixed(3))}
        {statCard('Most Predictable', teams.length ? [...data.teams].sort((a, b) => b.accuracy - a.accuracy)[0].team : '—')}
        {statCard('Least Predictable', teams.length ? [...data.teams].sort((a, b) => a.accuracy - b.accuracy)[0].team : '—')}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 20 }}>
        {/* Team predictability ranking */}
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', borderBottom: '1px solid var(--border)' }}>
            <div style={{ fontWeight: 700, fontSize: 14 }}>Predictability Ranking — {data.test_year}</div>
            <select className="metric-select" value={sort} onChange={e => setSort(e.target.value)}>
              <option value="predictability_rank">Most predictable first</option>
              <option value="pass_rate">Pass rate</option>
              <option value="alpha">Team A-Z</option>
            </select>
          </div>
          <div style={{ padding: '10px 0' }}>
            {teams.map(t => (
              <PredictabilityBar key={t.team} team={t} avg={avg} min={min} max={max} />
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Feature importance */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 16 }}>
            <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>What Drives the Model</div>
            {data.feature_importance.slice(0, 8).map(f => (
              <div key={f.feature} style={{ marginBottom: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--muted)', marginBottom: 3 }}>
                  <span>{FEATURE_LABELS[f.feature] || f.feature}</span>
                  <span>{(f.importance * 100).toFixed(1)}%</span>
                </div>
                <div style={{ height: 6, background: 'var(--surface2)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{ width: `${(f.importance / maxImportance) * 100}%`, height: '100%', background: 'var(--accent)', borderRadius: 3 }} />
                </div>
              </div>
            ))}
          </div>

          {/* Pass rate by down */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 16 }}>
            <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>League Pass Rate by Down</div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', height: 100 }}>
              {data.pass_rate_by_down.map(d => (
                <div key={d.down} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', height: '100%' }}>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>{(d.pass_rate * 100).toFixed(0)}%</div>
                  <div style={{ width: '100%', height: `${(d.pass_rate / maxPassRate) * 100}%`, background: 'var(--green)', borderRadius: '4px 4px 0 0', opacity: 0.85 }} />
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>Down {d.down}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
