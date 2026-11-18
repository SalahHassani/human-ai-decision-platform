import React, { useState } from 'react'

export default function VotingPanel({ sessionState, myParticipant, onSubmitVote }) {
  const [selectedTarget, setSelectedTarget] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const currentRound = sessionState.current_round || 1
  const voteStatus = sessionState.vote_status
  const submittedIds = voteStatus?.submitted_participant_ids || []
  const hasVoted = myParticipant ? submittedIds.includes(myParticipant.id) : false

  const handleVote = async (e) => {
    e.preventDefault()
    if (!selectedTarget || selectedTarget === myParticipant?.id || hasVoted || submitting) return
    setSubmitting(true)
    try {
      await onSubmitVote(selectedTarget)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={cardStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>Round {currentRound} of 2 — Cast Your Vote</h2>
        <span style={badgeStyle}>
          {voteStatus?.votes_received || 0} / 3 Votes Submitted
        </span>
      </div>

      <p style={{ color: '#4b5563', marginTop: 8 }}>
        Select another participant to serve as the group&apos;s <strong>Decision Maker</strong>{' '}
        (self-voting is not allowed). Individual choices stay hidden until the final results.
      </p>

      <form onSubmit={handleVote} style={{ marginTop: 16 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {(sessionState.participants || []).map((p) => {
            const isSelected = selectedTarget === p.id
            const isMe = p.id === myParticipant?.id
            const isDisabled = hasVoted || isMe

            return (
              <button
                key={p.id}
                type="button"
                disabled={isDisabled}
                onClick={() => !isDisabled && setSelectedTarget(p.id)}
                style={{
                  padding: 16,
                  borderRadius: 8,
                  border: isSelected ? '2px solid #2563eb' : '1px solid #d1d5db',
                  background: isMe ? '#f3f4f6' : isSelected ? '#eff6ff' : '#ffffff',
                  opacity: isMe ? 0.65 : 1,
                  cursor: isDisabled ? 'not-allowed' : 'pointer',
                  textAlign: 'center',
                }}
              >
                <div style={{ fontWeight: 700, fontSize: 16 }}>
                  {p.display_name} {isMe ? '(You)' : ''}
                </div>
                <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>
                  {isMe
                    ? 'Cannot vote for yourself'
                    : submittedIds.includes(p.id)
                    ? 'Vote submitted'
                    : 'Awaiting vote'}
                </div>
              </button>
            )
          })}
        </div>

        <div style={{ marginTop: 18 }}>
          {hasVoted ? (
            <div style={{ padding: 12, background: '#f0fdf4', color: '#166534', borderRadius: 8, fontWeight: 500 }}>
              Your Round {currentRound} vote has been recorded. Waiting for remaining participants...
            </div>
          ) : (
            <button
              type="submit"
              disabled={!selectedTarget || submitting}
              style={{
                width: '100%',
                padding: '12px 16px',
                borderRadius: 8,
                border: 'none',
                background: !selectedTarget || submitting ? '#93c5fd' : '#2563eb',
                color: '#ffffff',
                fontWeight: 600,
                fontSize: 15,
                cursor: !selectedTarget || submitting ? 'not-allowed' : 'pointer',
              }}
            >
              {submitting ? 'Submitting Vote...' : 'Confirm Vote'}
            </button>
          )}
        </div>
      </form>
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
  background: '#fef3c7',
  color: '#92400e',
  padding: '4px 10px',
  borderRadius: 999,
  fontSize: 13,
  fontWeight: 600,
}