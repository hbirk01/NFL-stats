import { useState, useEffect } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'

export default function QBPressure({ playerId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch(`/api/players/${playerId}/pressure`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [playerId])

  if (loading) return <div className="spinner" style={{ margin: '20px auto' }} />
  if (!data?.pressure || !data?.clean) return <div style={{ color: 'var(--muted)', fontSize: 13, padding: 16 }}>No pressure data available</div>

  const { pressure, clean, pressure_rate } = data

  const compChart = [
    { label: 'Clean', value: clean.comp_pct, color: 'var(--green)' },
    { label: 'Pressured', value: pressure.comp_pct, color: 'var(--red)' },
  ]

  const epaChart = [
    { label: 'Clean', value: clean.epa_per_att, color: 'var(--green)' },
    { label: 'Pressured', value: pressure.epa_per_att, color: 'var(--red)' },
  ]

  const StatBlock = ({ label, data, color }) => (
    <div style={{ background: 'var(--surface2)', borderRadius: 10, padding: '14px 16px', borderTop: `3px solid ${color}` }}>
      <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color, marginBottom: 10 }}>{label}</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {[
          { val: `${data.comp_pct}%`, lbl: 'Comp %' },
          { val: data.epa_per_att > 0 ? `+${data.epa_per_att}` : data.epa_per_att, lbl: 'EPA/Att' },
          { val: `${data.yards} yds`, lbl: 'Yards' },
          { val: `${data.tds} / ${data.ints}`, lbl: 'TD / INT' },
        ].map(s => (
          <div key={s.lbl}>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{s.val}</div>
            <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{s.lbl}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 8, fontSize: 11, color: 'var(--muted)' }}>{data.attempts} attempts</div>
    </div>
  )

  return (
    <div className="chart-wrap">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h4 style={{ margin: 0 }}>Pressure Handling</h4>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>Pressured on <b style={{ color: 'var(--text)' }}>{pressure_rate}%</b> of dropbacks</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
        <StatBlock label="Clean Pocket" data={clean} color="var(--green)" />
        <StatBlock label="Under Pressure" data={pressure} color="var(--red)" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>Completion %</div>
          <ResponsiveContainer width="100%" height={80}>
            <BarChart data={compChart} barSize={36} margin={{ left: 0, right: 0, top: 0, bottom: 0 }}>
              <XAxis dataKey="label" tick={{ fill: 'var(--muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis hide domain={[0, 100]} />
              <Tooltip formatter={(v) => `${v}%`} contentStyle={{ background: 'var(--surface2)', border: '1px solid var(--border)', fontSize: 12 }} />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {compChart.map((e, i) => <Cell key={i} fill={e.color} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>EPA / Attempt</div>
          <ResponsiveContainer width="100%" height={80}>
            <BarChart data={epaChart} barSize={36} margin={{ left: 0, right: 0, top: 0, bottom: 0 }}>
              <XAxis dataKey="label" tick={{ fill: 'var(--muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis hide />
              <Tooltip formatter={(v) => v > 0 ? `+${v}` : v} contentStyle={{ background: 'var(--surface2)', border: '1px solid var(--border)', fontSize: 12 }} />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {epaChart.map((e, i) => <Cell key={i} fill={e.color} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
