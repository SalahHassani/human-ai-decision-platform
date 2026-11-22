import React from 'react'

export default function WaitingRoom({ sessionState, myParticipant }) {
  const { participants = [], joined_humans = 0, required_humans = 3 } = sessionState

  return (
    <div className="app-card">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <h2 className="app-heading">Waiting Room</h2>
        <span className="app-badge-mustard">
          {joined_humans} / {required_humans} Participants Ready
        </span>
      </div>

      <p className="app-subtext">
        The experiment will start automatically as soon as all 3 participant slots are occupied.
        You are assigned as <strong>{myParticipant?.display_name}</strong>.
      </p>

      <div className="app-grid-3">
        {participants.map((p) => {
          const isMe = p.id === myParticipant?.id
          return (
            <div
              key={p.id}
              className={`app-slot ${p.is_connected ? 'is-ready' : ''} ${isMe ? 'is-me' : ''}`}
            >
              <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 16.5 }}>
                {p.display_name} {isMe ? '(You)' : ''}
              </div>
              <div
                style={{
                  marginTop: 6,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11.5,
                  fontWeight: 600,
                  color: p.is_connected ? 'var(--mustard-ink)' : 'var(--ink-subtle)',
                }}
              >
                {p.is_connected ? 'READY' : 'WAITING TO JOIN'}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

