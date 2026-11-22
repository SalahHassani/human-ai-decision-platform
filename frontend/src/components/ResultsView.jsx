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
    <div className="exp1-card">
      <div className="exp1-winner-banner">
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            fontWeight: 700,
            color: '#9bbcf9',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
          }}
        >
          Selected Decision Maker
        </div>
        <div
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 28,
            fontWeight: 800,
            color: '#ffffff',
            marginTop: 6,
          }}
        >
          {result.decision_maker_name} {isMeWinner ? '(You!)' : ''}
        </div>
        {sessionState.selected_topic?.title && (
          <div style={{ fontSize: 13, color: '#cbd5e1', marginTop: 6 }}>
            Topic: {sessionState.selected_topic.title}
          </div>
        )}
      </div>

      <h3
        style={{
          marginTop: 0,
          marginBottom: 10,
          fontFamily: 'var(--font-display)',
          fontSize: 16.5,
        }}
      >
        Final Vote Breakdown
      </h3>
      <table className="exp1-table">
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

      <div
        style={{
          marginTop: 20,
          paddingTop: 16,
          borderTop: '1px solid var(--border-subtle)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <span style={{ fontSize: 13, color: 'var(--slate-600)' }}>
          Research Export (messages, round votes, totals, locked topic, Decision Maker)
        </span>
        <button
          type="button"
          onClick={handleExport}
          disabled={exporting}
          className="exp1-btn exp1-btn-secondary"
        >
          {exporting ? 'Exporting...' : 'Download CSV'}
        </button>
      </div>
      {exportError && <div className="exp1-error">{exportError}</div>}
    </div>
  )
}