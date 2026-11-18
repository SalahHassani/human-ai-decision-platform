import React from 'react'

export default function ResultsView({ sessionState, myParticipant }) {
  const result = sessionState.result
  if (!result) return null

  const participants = sessionState.participants || []
  const isMeWinner = result.decision_maker_id === myParticipant?.id

  return (
    <div style={cardStyle}>
      <div
        style={{
          padding: 20,
          borderRadius: 10,
          background: '#eff6ff',
          border: '1px solid #bfdbfe',
          textAlign: 'center',
          marginBottom: 20,
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 600, color: '#1d4ed8', textTransform: 'uppercase' }}>
          Selected Decision Maker
        </div>
        <div style={{ fontSize: 28, fontWeight: 800, color: '#111827', marginTop: 4 }}>
          {result.decision_maker_name} {isMeWinner ? '(You!)' : ''}
        </div>
      </div>

      <h3 style={{ marginTop: 0 }}>Final Vote Breakdown</h3>
      <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
        <thead>
          <tr style={{ borderBottom: '2px solid #e5e7eb', color: '#4b5563', fontSize: 14 }}>
            <th style={{ padding: '10px 8px' }}>Participant</th>
            <th style={{ padding: '10px 8px' }}>Round 1</th>
            <th style={{ padding: '10px 8px' }}>Round 2</th>
            <th style={{ padding: '10px 8px' }}>Total Votes</th>
          </tr>
        </thead>
        <tbody>
          {participants.map((p) => {
            const isWinner = p.id === result.decision_maker_id
            return (
              <tr
                key={p.id}
                style={{
                  borderBottom: '1px solid #e5e7eb',
                  background: isWinner ? '#f0fdf4' : 'transparent',
                  fontWeight: isWinner ? 700 : 400,
                }}
              >
                <td style={{ padding: '10px 8px' }}>
                  {p.display_name} {p.id === myParticipant?.id ? '(You)' : ''}
                </td>
                <td style={{ padding: '10px 8px' }}>{result.round_1_totals?.[p.id] ?? 0}</td>
                <td style={{ padding: '10px 8px' }}>{result.round_2_totals?.[p.id] ?? 0}</td>
                <td style={{ padding: '10px 8px' }}>{result.totals_by_participant?.[p.id] ?? 0}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

const cardStyle = {
  background: '#ffffff',
  border: '1px solid #e5e7eb',
  borderRadius: 10,
  padding: 24,
  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
}