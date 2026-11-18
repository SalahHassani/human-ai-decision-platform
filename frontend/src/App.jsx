import React, { useEffect, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function App() {
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API_URL}/api/health`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(setHealth)
      .catch((err) => setError(err.message))
  }, [])

  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', maxWidth: 680, margin: '48px auto', padding: '0 16px' }}>
      <h1>Human-AI Decision Experiment Platform</h1>
      <p style={{ color: '#555' }}>Milestone 0 — Environment & Configuration Verification</p>
      {error && (
        <div style={{ padding: 12, background: '#fee2e2', color: '#991b1b', borderRadius: 6 }}>
          Backend unreachable: {error}
        </div>
      )}
      {health && (
        <pre style={{ padding: 16, background: '#f3f4f6', borderRadius: 6 }}>
          {JSON.stringify(health, null, 2)}
        </pre>
      )}
    </div>
  )
}