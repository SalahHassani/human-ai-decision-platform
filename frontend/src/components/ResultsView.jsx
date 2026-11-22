import React, { useState } from 'react'
import { downloadSessionCsv } from '../services/api'

export default function ResultsView({ sessionState, myParticipant }) {
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState(null)

  const result = sessionState.result
  if (!result) return null

  const participants = sessionState.participants || []
  const isMeWinner = result.decision_maker_id === myParticipant?.id

  const handleExport = async () => {
    setExporting(true)
    setExportError(null)
    try {
      await downloadSessionCsv(sessionState.session_id)
    } catch (err) {
      setExportError(err.message)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="app-card">
      <div className="app-winner-hero">
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            fontWeight: 700,
            color: 'var(--orange-500)',
            textTransform: 'uppercase',
            letterSpacing: '0.07em',
          }}
        >
          Selected Decision Maker
        </div>
        <div
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 'clamp(24px, 4vw, 30px)',
            fontWeight: 700,
            color: 'var(--bg-white)',
            marginTop: 6,
          }}
        >
          {result.decision_maker_name} {isMeWinner ? '(You!)' : ''}
        </div>
        {sessionState.selected_topic?.title && (
          <div style={{ fontSize: 13, color: '#dbe4ef', marginTop: 6 }}>
            Topic: {sessionState.selected_topic.title}
          </div>
        )}
      </div>

      <h3
        style={{
          marginTop: 0,
          marginBottom: 10,
          fontFamily: 'var(--font-display)',
          fontSize: 17.5,
        }}
      >
        Final Vote Breakdown
      </h3>
      <div className="app-table-wrap">
        <table className="app-table">
          <thead>
            <tr>
              <th>Participant</th>
              <th>Round 1</th>
              <th>Round 2</th>
              <th>Total Votes</th>
            </tr>
          </thead>
          <tbody>
            {participants.map((p) => {
              const isWinner = p.id === result.decision_maker_id
              return (
                <tr key={p.id} className={isWinner ? 'is-winner' : ''}>
                  <td>
                    {p.display_name} {p.id === myParticipant?.id ? '(You)' : ''}
                  </td>
                  <td>{result.round_1_totals?.[p.id] ?? 0}</td>
                  <td>{result.round_2_totals?.[p.id] ?? 0}</td>
                  <td>{result.totals_by_participant?.[p.id] ?? 0}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div
        style={{
          marginTop: 22,
          paddingTop: 16,
          borderTop: '1px solid var(--border-light)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <span style={{ fontSize: 13, color: 'var(--ink-muted)' }}>
          Research Export (messages, round votes, totals, Decision Maker)
        </span>
        <button
          type="button"
          onClick={handleExport}
          disabled={exporting}
          className="app-btn app-btn-secondary"
        >
          {exporting ? 'Exporting...' : 'Download CSV'}
        </button>
      </div>
      {exportError && (
        <div className="app-error" style={{ marginTop: 12, marginBottom: 0 }}>
          {exportError}
        </div>
      )}
    </div>
  )
}

