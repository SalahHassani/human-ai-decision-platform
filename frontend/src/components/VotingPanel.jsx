import React, { useState } from 'react'

export default function VotingPanel({ sessionState, myParticipant, onSubmitVote }) {
  const [selectedTarget, setSelectedTarget] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const currentRound = sessionState.current_round || 1
  const voteStatus = sessionState.vote_status
  const submittedIds = voteStatus?.submitted_participant_ids || []
  const hasVoted = myParticipant ? submittedIds.includes(myParticipant.id) : false

  // Hide the participant's own identity from selectable voting options
  const eligibleCandidates = (sessionState.participants || []).filter(
    (p) => p.id !== myParticipant?.id
  )

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
    <div className="exp1-card">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <h2 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 20 }}>
          Round {currentRound} of 2 — Cast Your Vote
        </h2>
        <span className="exp1-badge">
          {voteStatus?.votes_received || 0} / 3 Votes Submitted
        </span>
      </div>

      <p style={{ color: 'var(--slate-600)', marginTop: 8, fontSize: 14, lineHeight: 1.5 }}>
        Select one of the other two participants to serve as the group&apos;s{' '}
        <strong>Decision Maker</strong> (your own identity,{' '}
        <strong>{myParticipant?.display_name}</strong>, is excluded from voting options).
      </p>

      <form onSubmit={handleVote} style={{ marginTop: 18 }}>
        <div className="exp1-grid-2">
          {eligibleCandidates.map((p) => {
            const isSelected = selectedTarget === p.id
            return (
              <button
                key={p.id}
                type="button"
                disabled={hasVoted}
                onClick={() => !hasVoted && setSelectedTarget(p.id)}
                className={`exp1-candidate-btn ${isSelected ? 'is-selected' : ''}`}
              >
                <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 16.5 }}>
                  {p.display_name}
                </div>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11.5,
                    color: 'var(--slate-500)',
                    marginTop: 6,
                  }}
                >
                  {submittedIds.includes(p.id) ? 'VOTE SUBMITTED' : 'AWAITING VOTE'}
                </div>
              </button>
            )
          })}
        </div>

        <div style={{ marginTop: 18 }}>
          {hasVoted ? (
            <div
              style={{
                padding: 13,
                background: 'var(--success-bg)',
                border: '1px solid var(--success-border)',
                color: 'var(--success-text)',
                borderRadius: 'var(--radius-md)',
                fontWeight: 600,
                fontSize: 13.5,
              }}
            >
              Your Round {currentRound} vote has been recorded. Waiting for remaining
              participants...
            </div>
          ) : (
            <button
              type="submit"
              disabled={!selectedTarget || submitting}
              className="exp1-btn exp1-btn-primary"
              style={{ width: '100%', padding: '12px 16px', fontSize: 14.5 }}
            >
              {submitting ? 'Submitting Vote...' : 'Confirm Vote'}
            </button>
          )}
        </div>
      </form>
    </div>
  )
}