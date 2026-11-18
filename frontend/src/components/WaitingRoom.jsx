import React from 'react'

export default function WaitingRoom({ sessionState, myParticipant }) {
  const { participants = [], joined_humans = 0, required_humans = 3 } = sessionState

  return (
    <div style={cardStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>Waiting Room</h2>
        <span style={badgeStyle}>
          {joined_humans} / {required_humans} Participants Ready
        </span>
      </div>

      <p style={{ color: '#4b5563', marginTop: 8 }}>
        The experiment will start automatically as soon as all 3 participant slots are occupied.
        You are assigned as <strong>{myParticipant?.display_name}</strong>.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginTop: 20 }}>
        {participants.map((p) => {
          const isMe = p.id === myParticipant?.id
          return (
            <div
              key={p.id}
              style={{
                padding: 16,
                borderRadius: 8,
                border: isMe ? '2px solid #2563eb' : '1px solid #e5e7eb',
                background: p.is_connected ? '#f0fdf4' : '#f9fafb',
                textAlign: 'center',
              }}
            >
              <div style={{ fontWeight: 700, fontSize: 16 }}>
                {p.display_name} {isMe ? '(You)' : ''}
              </div>
              <div
                style={{
                  marginTop: 6,
                  fontSize: 13,
                  color: p.is_connected ? '#15803d' : '#6b7280',
                }}
              >
                {p.is_connected ? 'Ready' : 'Waiting to join...'}
              </div>
            </div>
          )
        })}
      </div>
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

const badgeStyle = {
  background: '#eff6ff',
  color: '#1d4ed8',
  padding: '4px 10px',
  borderRadius: 999,
  fontSize: 13,
  fontWeight: 600,
}