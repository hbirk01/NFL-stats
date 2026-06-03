import { useState, useEffect } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, PieChart, Pie, Legend } from 'recharts'

const BAND_COLORS = ['var(--red)', '#f97316', 'var(--muted)', 'var(--green)', '#00d4aa']

export default function RBRushDetail({ playerId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch(`/api/players/${playerId}/rushing-detail`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [playerId])

  if (loading) return <div className="spinner" style={{ margin: '20px auto' }} />
  if (!data) return null

  const { run_gap, down_splits, yardage_bands } = data

  return (
    <>
      {/* Yardage distribution */}
      {yardage_bands.length > 0 && (
        <div className="chart-wrap">
          <h4>Carry Distribution by Yardage</h4>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
            {yardage_bands.map((b, i) => (
              <div key={b.band} style={{ flex: 1, minWidth: 70, background: 'var(--surface2)', borderRadius: 8, padding: '10px 12px', borderTop: `3px solid ${BAND_COLORS[i]}` }}>
                <div style={{ fontSize: 18, fontWeight: 700 }}>{b.pct}%</div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{b.band} yds</div>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>{b.carries} carries</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            Explosion rate (20+ yds): <b style={{ color: 'var(--text)' }}>{yardage_bands.find(b => b.band === '20+')?.pct ?? 0}%</b>
            &nbsp;·&nbsp;
            Stuffed rate (0 or less): <b style={{ color: 'var(--text)' }}>{yardage_bands.find(b => b.band === '0 or less')?.pct ?? 0}%</b>
          </div>
        </div>
      )}

      {/* Down splits */}
      {down_splits.length > 0 && (
        <div className="chart-wrap">
          <h4>Performance by Down</h4>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={down_splits} margin={{ left: 0, right: 16, top: 4, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="down" tickFormatter={d => `${d}${d===1?'st':d===2?'nd':'rd'} Down`} tick={{ fill: 'var(--muted)', fontSize: 11 }} />
              <YAxis yAxisId="left" tick={{ fill: 'var(--muted)', fontSize: 11 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fill: 'var(--muted)', fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: 'var(--surface2)', border: '1px solid var(--border)', fontSize: 12 }}
                formatter={(val, name) => [name === 'ypc' ? `${val} ypc` : name === 'epa' ? (val > 0 ? `+${val}` : val) : val, name.toUpperCase()]}
              />
              <Legend wrapperStyle={{ fontSize: 11, color: 'var(--muted)', paddingTop: 4 }} formatter={v => v === 'ypc' ? 'YPC' : 'Carries'} />
              <Bar yAxisId="left" dataKey="ypc" name="ypc" fill="var(--rb)" radius={[4, 4, 0, 0]} />
              <Bar yAxisId="right" dataKey="carries" name="carries" fill="var(--border)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Run gap breakdown */}
      {run_gap.length > 0 && (
        <div className="chart-wrap">
          <h4>Run Gap Breakdown</h4>
          <ResponsiveContainer width="100%" height={Math.max(180, run_gap.length * 32)}>
            <BarChart data={run_gap} layout="vertical" margin={{ left: 8, right: 32, top: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
              <XAxis type="number" tick={{ fill: 'var(--muted)', fontSize: 11 }} />
              <YAxis type="category" dataKey="gap_label" tick={{ fill: 'var(--text)', fontSize: 11 }} width={100} />
              <Tooltip
                contentStyle={{ background: 'var(--surface2)', border: '1px solid var(--border)', fontSize: 12 }}
                formatter={(val, name) => [name === 'ypc' ? `${val}` : val, name.toUpperCase()]}
              />
              <Bar dataKey="ypc" name="ypc" fill="var(--rb)" radius={[0, 4, 4, 0]} label={{ position: 'right', fill: 'var(--muted)', fontSize: 11, formatter: v => `${v}` }} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </>
  )
}
