import { useState, useEffect } from 'react'
import { POS_COLORS, POS_EMOJI, detailStats } from '../utils'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts'
import WRRouteTree from './deepdive/WRRouteTree'
import QBPressure from './deepdive/QBPressure'
import RBRushDetail from './deepdive/RBRushDetail'
import PlayerSOSCard from './PlayerSOSCard'

export default function PlayerDetail({ player, onBack }) {
  const [report, setReport] = useState(null)
  const [loadingReport, setLoadingReport] = useState(false)

  const pos = player.position
  const color = POS_COLORS[pos] || 'var(--accent)'
  const stats = detailStats(player)

  useEffect(() => {
    setLoadingReport(true)
    fetch(`/api/players/${player.player_id}/scouting-report`)
      .then(r => r.json())
      .then(data => {
        setReport(data)
        setLoadingReport(false)
      })
      .catch(() => setLoadingReport(false))
  }, [player.player_id])

  // Build radar data for visual positions
  const radarData = buildRadarData(player, pos)

  return (
    <div className="detail-view">
      <button className="back-btn" onClick={onBack}>
        ← Back to players
      </button>

      <div className="detail-header">
        {player.headshot_url
          ? <img className="detail-headshot" src={player.headshot_url} alt={player.player_display_name} onError={e => { e.target.style.display='none' }} />
          : <div className="headshot-placeholder" style={{ width: 80, height: 80, fontSize: 32 }}>{POS_EMOJI[pos]}</div>
        }
        <div>
          <div className="detail-name">{player.player_display_name}</div>
          <div className="detail-meta">
            <span className="pos-badge" style={{ background: color + '22', color, marginRight: 8 }}>{pos}</span>
            {player.recent_team} · {player.games} games · 2025 season
          </div>
        </div>
      </div>

      <div className="stats-grid">
        {stats.map(s => (
          <div key={s.lbl} className="stat-box">
            <div className="val">{s.val}</div>
            <div className="lbl">{s.lbl}</div>
          </div>
        ))}
      </div>

      {radarData.length > 0 && (
        <div className="chart-wrap" style={{ marginBottom: 24 }}>
          <h4>Skill Profile</h4>
          <ResponsiveContainer width="100%" height={260}>
            <RadarChart data={radarData}>
              <PolarGrid stroke="var(--border)" />
              <PolarAngleAxis dataKey="skill" tick={{ fill: 'var(--muted)', fontSize: 12 }} />
              <Radar name={player.player_display_name} dataKey="score" stroke={color} fill={color} fillOpacity={0.2} />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      )}

      <PlayerSOSCard playerId={player.player_id} position={pos} />

      {pos === 'WR' && <WRRouteTree playerId={player.player_id} />}
      {pos === 'TE' && <WRRouteTree playerId={player.player_id} />}
      {pos === 'QB' && <QBPressure playerId={player.player_id} />}
      {pos === 'RB' && <RBRushDetail playerId={player.player_id} />}

      <div className="scouting-report">
        <h3>⚡ AI Scouting Report</h3>
        {loadingReport && <div className="spinner" style={{ margin: '20px auto' }} />}
        {report && !loadingReport && (
          <>
            {report.strengths && (
              <div className="report-section">
                <h4>Strengths</h4>
                <p>{report.strengths}</p>
              </div>
            )}
            {report.limitations && (
              <div className="report-section">
                <h4>Limitations</h4>
                <p>{report.limitations}</p>
              </div>
            )}
            {report.outlook && (
              <div className="report-section">
                <h4>Outlook</h4>
                <p>{report.outlook}</p>
              </div>
            )}
            {!report.strengths && report.report && (
              <div className="report-section">
                <p>{report.report}</p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function norm(val, min, max) {
  if (val == null || isNaN(val)) return 50
  return Math.round(Math.min(100, Math.max(0, ((val - min) / (max - min)) * 100)))
}

function buildRadarData(p, pos) {
  if (pos === 'QB') return [
    { skill: 'Volume', score: norm(p.passing_yards, 1000, 5000) },
    { skill: 'Efficiency', score: norm(p.completion_pct, 55, 75) },
    { skill: 'EPA', score: norm(p.passing_epa, -50, 400) },
    { skill: 'CPOE', score: norm(p.completion_percentage_above_expectation, -5, 10) },
    { skill: 'TD Rate', score: norm(p.passing_tds / Math.max(p.attempts, 1) * 100, 2, 8) },
    { skill: 'Ball Sec.', score: norm(10 - (p.interceptions / Math.max(p.attempts, 1) * 100), 7, 10) },
  ]
  if (pos === 'WR') return [
    { skill: 'Volume', score: norm(p.receiving_yards, 200, 1700) },
    { skill: 'Sep.', score: norm(p.avg_separation, 1, 5) },
    { skill: 'YAC+', score: norm(p.avg_yac_above_expectation, -2, 4) },
    { skill: 'EPA', score: norm(p.receiving_epa, -10, 80) },
    { skill: 'Share', score: norm(p.target_share, 0.05, 0.35) },
    { skill: 'WOPR', score: norm(p.wopr, 0.1, 0.7) },
  ]
  if (pos === 'RB') return [
    { skill: 'Volume', score: norm(p.rushing_yards, 100, 1500) },
    { skill: 'YPC', score: norm(p.yards_per_carry, 2.5, 5.5) },
    { skill: 'EPA', score: norm(p.rushing_epa, -50, 50) },
    { skill: 'RYOE', score: norm(p.rush_yards_over_expected_per_att, -1, 2) },
    { skill: 'Receiving', score: norm(p.receiving_yards, 0, 600) },
    { skill: 'Rec EPA', score: norm(p.receiving_epa, -5, 40) },
  ]
  if (pos === 'TE') return [
    { skill: 'Volume', score: norm(p.receiving_yards, 100, 1000) },
    { skill: 'Sep.', score: norm(p.avg_separation, 0.5, 4) },
    { skill: 'YAC+', score: norm(p.avg_yac_above_expectation, -2, 4) },
    { skill: 'EPA', score: norm(p.receiving_epa, -5, 60) },
    { skill: 'TD Rate', score: norm(p.receiving_tds / Math.max(p.targets, 1) * 100, 0, 15) },
    { skill: 'Share', score: norm(p.target_share, 0.02, 0.2) },
  ]
  return []
}
