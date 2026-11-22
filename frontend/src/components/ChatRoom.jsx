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
    <div className="app-card">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 12,
          marginBottom: 14,
        }}
      >
        <div>
          <h2 className="app-heading">Round {currentRound} of 2 — Group Discussion</h2>
          <p className="app-subtext" style={{ marginTop: 4 }}>
            Discuss who among <strong>Player A</strong>, <strong>Player B</strong>, and{' '}
            <strong>Player C</strong> should be elected as the Decision Maker.
          </p>
        </div>

        <div className={`app-timer ${secondsLeft <= 10 ? 'is-urgent' : ''}`}>
          {secondsLeft}s
        </div>
      </div>

      <div className="app-chat-stream">
        {roundMessages.length === 0 && (
          <div
            style={{
              color: 'var(--ink-subtle)',
              textAlign: 'center',
              margin: 'auto 0',
              fontSize: 13.5,
            }}
          >
            No messages yet in Round {currentRound}. Say hello and share your thoughts!
          </div>
        )}
        {roundMessages.map((m) => {
          const isMe = m.sender_id === myParticipant?.id
          return (
            <div key={m.id} className={`app-bubble ${isMe ? 'is-me' : 'is-other'}`}>
              <div className="app-bubble-meta">
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
          className="app-input"
        />
        <button
          type="submit"
          disabled={!draft.trim() || sending}
          className="app-btn app-btn-primary"
          style={{ padding: '10px 20px', flexShrink: 0 }}
        >
          Send
        </button>
      </form>
    </div>
  )
}

