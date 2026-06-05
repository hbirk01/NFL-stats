import { useState } from 'react'
import { usePlayers } from './hooks/usePlayers'
import ExplorerTab from './components/ExplorerTab'
import LeaderboardTab from './components/LeaderboardTab'
import FantasyTab from './components/FantasyTab'
import CompareTab from './components/CompareTab'
import DynastyTab from './components/DynastyTab'
import MyTeamTab from './components/MyTeamTab'
import './index.css'

const TABS = [
  { id: 'explorer',     label: 'Explorer' },
  { id: 'leaderboards', label: 'Leaderboards' },
  { id: 'fantasy',      label: 'Fantasy' },
  { id: 'dynasty',      label: 'Dynasty' },
  { id: 'compare',      label: 'Compare' },
  { id: 'myteam',       label: 'Dynasty Men' },
]

export default function App() {
  const [tab, setTab] = useState('explorer')
  const { players, loading } = usePlayers()

  return (
    <div className="app">
      <header className="header">
        <div className="logo">Grid<span>Iron</span></div>
        <nav className="nav">
          {TABS.map(t => (
            <button
              key={t.id}
              className={`nav-btn ${tab === t.id ? 'active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div style={{ fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
          2025 NFL Season
        </div>
      </header>

      <main className="main">
        {tab === 'explorer'     && <ExplorerTab players={players} loading={loading} />}
        {tab === 'leaderboards' && <LeaderboardTab />}
        {tab === 'fantasy'      && <FantasyTab />}
        {tab === 'dynasty'      && <DynastyTab />}
        {tab === 'compare'      && <CompareTab players={players} />}
        {tab === 'myteam'       && <MyTeamTab />}
      </main>
    </div>
  )
}
