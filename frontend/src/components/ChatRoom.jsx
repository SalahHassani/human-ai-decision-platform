import React, { useEffect, useRef, useState } from 'react'

export default function ChatRoom({ sessionState, myParticipant, onSendMessage }) {
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(sessionState.discussion_duration_seconds || 60)
  const bottomRef = useRef(null)

  const currentRound = sessionState.current_round || 1
  const roundMessages = (sessionState.messages || []).filter(
    (m) => m.round_number === currentRound
  )

  useEffect(() => {
    if (!sessionState.round_ends_at) return undefined
    const updateTimer = () => {
      const endMs = new Date(sessionState.round_ends_at).getTime()
      const diff = Math.max(0, Math.ceil((endMs - Date.now()) / 1000))
      setSecondsLeft(diff)
    }
    updateTimer()
    const id = setInterval(updateTimer, 500)
    return () => clearInterval(id)
  }, [sessionState.round_ends_at])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [roundMessages.length])

  const handleSubmit = async (e) => {
    e.preventDefault()
    const text = draft.trim()
    if (!text || sending) return
    setSending(true)
    try {
      await onSendMessage(text)
      setDraft('')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="exp1-card">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 12,
          marginBottom: 12,
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 20 }}>
            Round {currentRound} of 2 — Group Discussion
          </h2>
          <p style={{ margin: '4px 0 0', color: 'var(--slate-600)', fontSize: 13.5 }}>
            {sessionState.selected_topic?.title ? (
              <>
                Topic: <strong>{sessionState.selected_topic.title}</strong> —{' '}
              </>
            ) : null}
            Deliberate on the scenario and who among <strong>Player A</strong>,{' '}
            <strong>Player B</strong>, and <strong>Player C</strong> should be Decision Maker.
          </p>
        </div>

        <div className={`exp1-timer ${secondsLeft <= 10 ? 'is-urgent' : ''}`}>
          {secondsLeft}s
        </div>
      </div>

      <div className="exp1-chat-feed">
        {roundMessages.length === 0 && (
          <div
            style={{
              color: 'var(--slate-500)',
              textAlign: 'center',
              marginTop: 115,
              fontSize: 13.5,
            }}
          >
            No messages yet in Round {currentRound}. Share your perspective to start the
            discussion.
          </div>
        )}
        {roundMessages.map((m) => {
          const isMe = m.sender_id === myParticipant?.id
          return (
            <div key={m.id} className={`exp1-bubble ${isMe ? 'is-me' : 'is-other'}`}>
              <div className="exp1-bubble-meta">
                {m.sender_name} {isMe ? '(You)' : ''}
              </div>
              <div>{m.content}</div>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={`Message as ${myParticipant?.display_name || 'Participant'}...`}
          maxLength={1000}
          className="exp1-select"
        />
        <button
          type="submit"
          disabled={!draft.trim() || sending}
          className="exp1-btn exp1-btn-primary"
          style={{ padding: '10px 20px' }}
        >
          Send
        </button>
      </form>
    </div>
  )
}