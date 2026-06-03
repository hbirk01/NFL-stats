import { POS_COLORS, POS_EMOJI, cardStats } from '../utils'

export default function PlayerCard({ player, onClick }) {
  const pos = player.position
  const color = POS_COLORS[pos] || 'var(--accent)'
  const stats = cardStats(player)

  return (
    <div
      className="player-card"
      style={{ '--pos-color': color }}
      onClick={() => onClick(player)}
    >
      <div className="card-header">
        {player.headshot_url
          ? <img className="headshot" src={player.headshot_url} alt={player.player_display_name} onError={e => { e.target.style.display='none' }} />
          : <div className="headshot-placeholder">{POS_EMOJI[pos] || '🏈'}</div>
        }
        <div>
          <div className="card-name">{player.player_display_name}</div>
          <div className="card-meta">{player.recent_team} · {player.games}G</div>
        </div>
        <div className="pos-badge" style={{ background: color + '22', color }}>
          {pos}
        </div>
      </div>

      <div className="stat-row">
        {stats.map(s => (
          <div key={s.lbl} className="stat-chip">
            <span className="val">{s.val}</span>
            <span className="lbl">{s.lbl}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
