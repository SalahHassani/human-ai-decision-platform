import React, { useEffect, useRef, useState } from 'react'

export default function ChatRoom({ sessionState, myParticipant, onSendMessage }) {
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(sessionState.discussion_duration_seconds || 60)
  const bottomRef = useRef(null)

  const currentRound = sessionState.current_round || 1
  const roundMessages = (sessionState.messages || []).filter((m) => m.round_number === currentRound)

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
    <div style={cardStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <h2 style={{ margin: 0 }}>Round {currentRound} of 2 — Group Discussion</h2>
          <p style={{ margin: '4px 0 0', color: '#4b5563', fontSize: 14 }}>
            Discuss who among <strong>Player A</strong>, <strong>Player B</strong>, and{' '}
            <strong>Player C</strong> should be elected as the Decision Maker.
          </p>
        </div>
        <div
          style={{
            padding: '8px 14px',
            borderRadius: 8,
            background: secondsLeft <= 10 ? '#fef2f2' : '#f3f4f6',
            color: secondsLeft <= 10 ? '#b91c1c' : '#111827',
            fontWeight: 700,
            fontVariantNumeric: 'tabular-nums',
            fontSize: 18,
          }}
        >
          {secondsLeft}s
        </div>
      </div>

      <div
        style={{
          height: 300,
          overflowY: 'auto',
          border: '1px solid #e5e7eb',
          borderRadius: 8,
          padding: 12,
          background: '#f9fafb',
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}
      >
        {roundMessages.length === 0 && (
          <div style={{ color: '#6b7280', textAlign: 'center', marginTop: 110 }}>
            No messages yet in Round {currentRound}. Say hello and share your thoughts!
          </div>
        )}
        {roundMessages.map((m) => {
          const isMe = m.sender_id === myParticipant?.id
          return (
            <div
              key={m.id}
              style={{
                alignSelf: isMe ? 'flex-end' : 'flex-start',
                maxWidth: '78%',
                background: isMe ? '#2563eb' : '#ffffff',
                color: isMe ? '#ffffff' : '#111827',
                border: isMe ? 'none' : '1px solid #e5e7eb',
                borderRadius: 10,
                padding: '8px 12px',
              }}
            >
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  marginBottom: 2,
                  opacity: isMe ? 0.9 : 0.7,
                }}
              >
                {m.sender_name} {isMe ? '(You)' : ''}
              </div>
              <div style={{ fontSize: 14, lineHeight: 1.4 }}>{m.content}</div>
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
          style={{
            flex: 1,
            padding: '10px 12px',
            borderRadius: 8,
            border: '1px solid #d1d5db',
            fontSize: 14,
          }}
        />
        <button
          type="submit"
          disabled={!draft.trim() || sending}
          style={{
            padding: '10px 18px',
            borderRadius: 8,
            border: 'none',
            background: !draft.trim() || sending ? '#93c5fd' : '#2563eb',
            color: '#ffffff',
            fontWeight: 600,
            cursor: !draft.trim() || sending ? 'not-allowed' : 'pointer',
          }}
        >
          Send
        </button>
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

