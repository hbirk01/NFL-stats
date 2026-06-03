import { useState, useEffect } from 'react'

export function usePlayers() {
  const [players, setPlayers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/api/players?limit=300')
      .then(r => r.json())
      .then(data => {
        setPlayers(data.players)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  return { players, loading, error }
}
