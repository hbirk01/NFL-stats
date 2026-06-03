import { useState, useEffect, useRef } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'

const ROUTE_COLORS = {
  'GO': '#4a9eff',
  'POST': '#7b6eff',
  'CORNER': '#ff6b35',
  'IN/DIG': '#3ecf8e',
  'DEEP OUT': '#f5a623',
  'QUICK OUT': '#ff4d6a',
  'HITCH/CURL': '#00d4aa',
  'SLANT': '#a78bfa',
  'SHALLOW CROSS/DRAG': '#34d399',
  'SCREEN': '#fbbf24',
  'SWING': '#f87171',
  'WHEEL': '#60a5fa',
  'TEXAS/ANGLE': '#e879f9',
}

// ── SVG field route paths ────────────────────────────────────────────────────
// Coordinate system: origin (ox, oy) = player start on LOS
// x increases to the right (toward sideline), y increases upward (downfield)
// All values in SVG units where field area is ~360×280px
// Player starts at ox=100, oy=220 (bottom-center of SVG)

const SVG_W = 360
const SVG_H = 290
const OX = 140   // player origin x (slightly left of center — hash mark)
const OY = 230   // player origin y (line of scrimmage)
const YD = 18    // pixels per ~5 yards downfield

// Each route is an array of [dx, dy] relative to origin, forming a polyline
// dx: positive = outside (right toward sideline), negative = inside
// dy: positive = upfield
const ROUTE_PATHS = {
  'GO':                 [[0,0],[0,5*YD],[0,11*YD]],
  'POST':               [[0,0],[0,4*YD],[3*YD,10*YD]],
  'CORNER':             [[0,0],[0,4*YD],[-4*YD,10*YD]],
  'IN/DIG':             [[0,0],[0,4*YD],[6*YD,4*YD]],
  'DEEP OUT':           [[0,0],[0,5*YD],[-6*YD,5*YD]],
  'QUICK OUT':          [[0,0],[0,1.5*YD],[-4*YD,1.5*YD]],
  'HITCH/CURL':         [[0,0],[0,3*YD],[0,3.8*YD],[-1.5*YD,2.5*YD]],
  'SLANT':              [[0,0],[0,YD],[5*YD,4*YD]],
  'SHALLOW CROSS/DRAG': [[0,0],[0,0.8*YD],[7*YD,0.8*YD]],
  'SCREEN':             [[0,0],[-2*YD,-0.5*YD],[-5*YD,-0.5*YD]],
  'SWING':              [[0,0],[-2*YD,0.5*YD],[-5*YD,2.5*YD]],
  'WHEEL':              [[0,0],[-3*YD,YD],[-4*YD,3*YD],[-3*YD,8*YD]],
  'TEXAS/ANGLE':        [[0,0],[0,YD],[3*YD,3.5*YD]],
}

// EPA → color interpolation: red(-0.5) → yellow(0) → green(+1)
function epaToColor(epa) {
  if (epa == null || isNaN(epa)) return '#6b7e96'
  const clamped = Math.max(-0.5, Math.min(1.0, epa))
  if (clamped < 0) {
    // red → yellow
    const t = (clamped + 0.5) / 0.5
    const r = 255
    const g = Math.round(255 * t)
    return `rgb(${r},${g},0)`
  } else {
    // yellow → green
    const t = clamped / 1.0
    const r = Math.round(255 * (1 - t))
    const g = Math.round(200 + 55 * t)
    return `rgb(${r},${g},60)`
  }
}

function routeToSVGPoints(route) {
  const pts = ROUTE_PATHS[route]
  if (!pts) return null
  return pts.map(([dx, dy]) => [OX + dx, OY - dy])
}

function FieldRouteTree({ routes }) {
  const [hovered, setHovered] = useState(null)

  const maxTargets = Math.max(...routes.map(r => r.targets), 1)

  return (
    <div style={{ position: 'relative' }}>
      <svg width="100%" viewBox={`0 0 ${SVG_W} ${SVG_H}`} style={{ display: 'block' }}>
        {/* Field background */}
        <rect x={0} y={0} width={SVG_W} height={SVG_H} fill="#0d1a0d" rx={8} />

        {/* Yard lines (every 5 yards = YD px) */}
        {[1,2,3,4,5,6,7,8,9,10].map(i => (
          <line
            key={i}
            x1={20} y1={OY - i * YD}
            x2={SVG_W - 20} y2={OY - i * YD}
            stroke="#1a3a1a" strokeWidth={1}
          />
        ))}

        {/* Line of scrimmage */}
        <line x1={20} y1={OY} x2={SVG_W - 20} y2={OY} stroke="#3a5a3a" strokeWidth={2} />
        <text x={22} y={OY - 4} fill="#3a5a3a" fontSize={9}>LOS</text>

        {/* Hash marks labels */}
        {[5,10,15,20,25,30,35,40].map((yd, i) => (
          <text key={i} x={SVG_W - 18} y={OY - (i + 1) * YD + 4} fill="#1a3a1a" fontSize={8} textAnchor="end">{yd}</text>
        ))}

        {/* Behind LOS shading */}
        <rect x={20} y={OY} width={SVG_W - 40} height={30} fill="rgba(255,80,80,0.04)" />

        {/* Route paths */}
        {routes.map(r => {
          const pts = routeToSVGPoints(r.route)
          if (!pts) return null
          const color = epaToColor(r.epa_per_target)
          const weight = 2 + (r.targets / maxTargets) * 5
          const isHov = hovered?.route === r.route
          const pointsStr = pts.map(([x, y]) => `${x},${y}`).join(' ')

          return (
            <g key={r.route}>
              {/* Glow on hover */}
              {isHov && (
                <polyline
                  points={pointsStr}
                  fill="none"
                  stroke={color}
                  strokeWidth={weight + 6}
                  strokeOpacity={0.25}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              )}
              <polyline
                points={pointsStr}
                fill="none"
                stroke={color}
                strokeWidth={isHov ? weight + 1.5 : weight}
                strokeOpacity={isHov ? 1 : 0.85}
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{ cursor: 'pointer', transition: 'stroke-width 0.1s' }}
                onMouseEnter={() => setHovered(r)}
                onMouseLeave={() => setHovered(null)}
              />
              {/* Arrow head at endpoint */}
              {pts.length >= 2 && (() => {
                const [x2, y2] = pts[pts.length - 1]
                const [x1, y1] = pts[pts.length - 2]
                const angle = Math.atan2(y2 - y1, x2 - x1)
                const len = 7
                const ax1 = x2 - len * Math.cos(angle - 0.5)
                const ay1 = y2 - len * Math.sin(angle - 0.5)
                const ax2 = x2 - len * Math.cos(angle + 0.5)
                const ay2 = y2 - len * Math.sin(angle + 0.5)
                return (
                  <polygon
                    points={`${x2},${y2} ${ax1},${ay1} ${ax2},${ay2}`}
                    fill={color}
                    opacity={isHov ? 1 : 0.85}
                    style={{ pointerEvents: 'none' }}
                  />
                )
              })()}
              {/* Target count dot at end */}
              {pts.length >= 1 && (
                <circle
                  cx={pts[pts.length - 1][0]}
                  cy={pts[pts.length - 1][1]}
                  r={3.5}
                  fill={color}
                  style={{ pointerEvents: 'none' }}
                />
              )}
            </g>
          )
        })}

        {/* Player origin dot */}
        <circle cx={OX} cy={OY} r={6} fill="#e8edf5" />
        <circle cx={OX} cy={OY} r={3} fill="#0a0e13" />
      </svg>

      {/* Hover tooltip */}
      {hovered && (
        <div style={{
          position: 'absolute', bottom: 12, left: 12,
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 8, padding: '10px 14px', fontSize: 12, pointerEvents: 'none',
          borderLeft: `3px solid ${epaToColor(hovered.epa_per_target)}`,
          minWidth: 160,
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>{hovered.route}</div>
          <div>Targets: <b>{hovered.targets}</b></div>
          <div>Catch Rate: <b>{hovered.catch_rate}%</b></div>
          <div>Yds/Target: <b>{hovered.yards_per_target}</b></div>
          <div>EPA/Target: <b style={{ color: epaToColor(hovered.epa_per_target) }}>{hovered.epa_per_target > 0 ? '+' : ''}{hovered.epa_per_target}</b></div>
          {hovered.tds > 0 && <div>TDs: <b>{hovered.tds}</b></div>}
        </div>
      )}

      {/* EPA color legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
        <span>Route color:</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <div style={{ width: 60, height: 6, borderRadius: 3, background: 'linear-gradient(to right, #ff4d6a, #ffff00, #3ecf8e)' }} />
          <span>Low EPA → High EPA</span>
        </div>
        <span style={{ marginLeft: 12 }}>Width = target volume</span>
      </div>
    </div>
  )
}

// ── Bar chart tooltip ────────────────────────────────────────────────────────
const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null
  return (
    <div style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 12 }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>{d.route}</div>
      <div>Targets: <b>{d.targets}</b></div>
      <div>Catch Rate: <b>{d.catch_rate}%</b></div>
      <div>Yds/Target: <b>{d.yards_per_target}</b></div>
      <div>EPA/Target: <b>{d.epa_per_target > 0 ? '+' : ''}{d.epa_per_target}</b></div>
      {d.tds > 0 && <div>TDs: <b>{d.tds}</b></div>}
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────
export default function WRRouteTree({ playerId }) {
  const [routes, setRoutes] = useState([])
  const [loading, setLoading] = useState(true)
  const [metric, setMetric] = useState('targets')
  const [view, setView] = useState('bar') // 'bar' | 'field'

  useEffect(() => {
    setLoading(true)
    fetch(`/api/players/${playerId}/routes`)
      .then(r => r.json())
      .then(d => { setRoutes(d.routes || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [playerId])

  const metrics = [
    { key: 'targets', label: 'Targets' },
    { key: 'catch_rate', label: 'Catch Rate %' },
    { key: 'yards_per_target', label: 'Yds / Target' },
    { key: 'epa_per_target', label: 'EPA / Target' },
  ]

  if (loading) return <div className="spinner" style={{ margin: '20px auto' }} />
  if (!routes.length) return <div style={{ color: 'var(--muted)', fontSize: 13, padding: 16 }}>No route data available</div>

  const data = [...routes].sort((a, b) => b.targets - a.targets)
  // Only show routes we have paths for in field view
  const fieldRoutes = data.filter(r => ROUTE_PATHS[r.route])

  return (
    <div className="chart-wrap">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h4 style={{ margin: 0 }}>Route Tree</h4>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {view === 'bar' && (
            <select className="metric-select" value={metric} onChange={e => setMetric(e.target.value)} style={{ fontSize: 11 }}>
              {metrics.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select>
          )}
          <div style={{ display: 'flex', background: 'var(--surface2)', borderRadius: 6, overflow: 'hidden', border: '1px solid var(--border)' }}>
            {['bar', 'field'].map(v => (
              <button
                key={v}
                onClick={() => setView(v)}
                style={{
                  background: view === v ? 'var(--wr)' : 'none',
                  border: 'none',
                  color: view === v ? '#fff' : 'var(--muted)',
                  padding: '4px 12px',
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: 'pointer',
                  textTransform: 'capitalize',
                }}
              >
                {v === 'bar' ? '≡ Bar' : '⬡ Field'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {view === 'bar' ? (
        <>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data} layout="vertical" margin={{ left: 10, right: 24, top: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
              <XAxis type="number" tick={{ fill: 'var(--muted)', fontSize: 11 }} />
              <YAxis type="category" dataKey="route" tick={{ fill: 'var(--text)', fontSize: 11 }} width={130} />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
              <Bar dataKey={metric} radius={[0, 4, 4, 0]}>
                {data.map((entry) => (
                  <Cell key={entry.route} fill={ROUTE_COLORS[entry.route] || 'var(--wr)'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
            {data.map(r => (
              <div key={r.route} style={{ background: 'var(--surface2)', borderRadius: 5, padding: '3px 8px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: ROUTE_COLORS[r.route] || 'var(--wr)', display: 'inline-block' }} />
                <span style={{ color: 'var(--muted)' }}>{r.route}</span>
                <span style={{ fontWeight: 700 }}>{r.targets}t</span>
                <span style={{ color: 'var(--muted)' }}>{r.catch_rate}%</span>
              </div>
            ))}
          </div>
        </>
      ) : (
        <FieldRouteTree routes={fieldRoutes} />
      )}
    </div>
  )
}
