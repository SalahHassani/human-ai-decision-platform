import React, { useCallback, useEffect, useState } from 'react'
import {
  advanceDiscussion,
  getActiveSession,
  getSessionState,
  joinSession,
  resetActiveSession,
  sendMessage,
  submitVote,
} from './services/api'
import { useExperimentSocket } from './hooks/useExperimentSocket'
import WaitingRoom from './components/WaitingRoom'
import ChatRoom from './components/ChatRoom'
import VotingPanel from './components/VotingPanel'
import ResultsView from './components/ResultsView'

const STORAGE_KEY = 'chm_experiment_auth_v1'

export default function App() {
  const [sessionState, setSessionState] = useState(null)
  const [auth, setAuth] = useState(() => {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY)
      return saved ? JSON.parse(saved) : null
    } catch {
      return null
    }
  })
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const saveAuth = (nextAuth) => {
    setAuth(nextAuth)
    try {
      if (nextAuth) {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(nextAuth))
      } else {
        sessionStorage.removeItem(STORAGE_KEY)
      }
    } catch {
      // ignore storage errors
    }
  }

  const loadInitial = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const active = await getActiveSession()
      setSessionState(active)
      if (auth && auth.sessionId !== active.session_id) {
        saveAuth(null)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    loadInitial()
  }, [loadInitial])

  const handleFullSync = useCallback((freshState) => {
    setSessionState(freshState)
  }, [])

  const handleSocketEvent = useCallback(
    async (msg) => {
      if (!msg?.event) return
      if (msg.event === 'new_message') {
        setSessionState((prev) => {
          if (!prev) return prev
          const exists = prev.messages?.some((m) => m.id === msg.payload.id)
          if (exists) return prev
          return { ...prev, messages: [...(prev.messages || []), msg.payload] }
        })
      } else if (msg.event === 'vote_status') {
        setSessionState((prev) => (prev ? { ...prev, vote_status: msg.payload } : prev))
      } else if (sessionState?.session_id) {
        try {
          const fresh = await getSessionState(sessionState.session_id)
          setSessionState(fresh)
        } catch {
          // ignore transient sync error
        }
      }
    },
    [sessionState?.session_id]
  )

  const { connected } = useExperimentSocket(
    auth?.sessionId,
    auth?.token,
    handleFullSync,
    handleSocketEvent
  )

  const handleJoin = async () => {
    if (!sessionState) return
    setError(null)
    try {
      const joined = await joinSession(sessionState.session_id)
      saveAuth({
        sessionId: joined.session_id,
        token: joined.participant_token,
        participant: joined.participant,
      })
      setSessionState(joined.session_state)
    } catch (err) {
      setError(err.message)
    }
  }

  const handleSendMessage = async (content) => {
    if (!auth) return
    setError(null)
    try {
      const created = await sendMessage(auth.sessionId, auth.token, content)
      setSessionState((prev) => {
        if (!prev) return prev
        const exists = prev.messages?.some((m) => m.id === created.id)
        if (exists) return prev
        return { ...prev, messages: [...(prev.messages || []), created] }
      })
    } catch (err) {
      setError(err.message)
    }
  }

  const handleSubmitVote = async (targetId) => {
    if (!auth) return
    setError(null)
    try {
      const status = await submitVote(auth.sessionId, auth.token, targetId)
      setSessionState((prev) => (prev ? { ...prev, vote_status: status } : prev))
      const fresh = await getSessionState(auth.sessionId)
      setSessionState(fresh)
    } catch (err) {
      setError(err.message)
    }
  }

  const handleReset = async (conditionKey = null) => {
    setError(null)
    try {
      const next = await resetActiveSession(conditionKey)
      saveAuth(null)
      setSessionState(next)
    } catch (err) {
      setError(err.message)
    }
  }

  const handleSkipTimer = async () => {
    if (!sessionState) return
    setError(null)
    try {
      const next = await advanceDiscussion(sessionState.session_id)
      if (next) setSessionState(next)
    } catch (err) {
      setError(err.message)
    }
  }

  const isDiscussion =
    sessionState?.phase === 'ROUND_1_DISCUSSION' || sessionState?.phase === 'ROUND_2_DISCUSSION'
  const isVoting =
    sessionState?.phase === 'ROUND_1_VOTING' || sessionState?.phase === 'ROUND_2_VOTING'

  return (
    <div
      style={{
        minHeight: '100vh',
        background: '#f3f4f6',
        fontFamily: 'system-ui, -apple-system, sans-serif',
        color: '#111827',
        padding: '24px 16px',
      }}
    >
      <div style={{ maxWidth: 760, margin: '0 auto' }}>
        <header
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 20,
          }}
        >
          <div>
            <h1 style={{ margin: 0, fontSize: 22 }}>Group Decision-Making Experiment</h1>
            <div style={{ fontSize: 13, color: '#6b7280', marginTop: 2 }}>
              Session: {sessionState?.session_id?.slice(0, 8) || '...'}
              {auth?.participant ? ` • You are ${auth.participant.display_name}` : ''}
              {auth ? (connected ? ' • Live' : ' • Reconnecting...') : ''}
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {isDiscussion && (
              <button type="button" onClick={handleSkipTimer} style={secondaryBtnStyle}>
                End Discussion Now
              </button>
            )}
            <button
              type="button"
              onClick={() => handleReset(sessionState?.condition_key)}
              style={secondaryBtnStyle}
            >
              Reset Session
            </button>
          </div>
        </header>

        {error && (
          <div
            style={{
              padding: 12,
              marginBottom: 16,
              borderRadius: 8,
              background: '#fef2f2',
              color: '#991b1b',
              border: '1px solid #fecaca',
              fontSize: 14,
            }}
          >
            {error}
          </div>
        )}

        {loading && <div style={{ color: '#6b7280' }}>Loading session...</div>}

        {!loading && sessionState && !auth && (
          <div
            style={{
              background: '#ffffff',
              border: '1px solid #e5e7eb',
              borderRadius: 10,
              padding: 28,
              textAlign: 'center',
            }}
          >
            <h2 style={{ marginTop: 0 }}>Join Experiment Session</h2>
            <p style={{ color: '#4b5563', maxWidth: 500, margin: '8px auto 20px' }}>
              You will be assigned a neutral identifier (Player A, Player B, or Player C).
              Participate in two 1-minute discussion rounds and vote for the group&apos;s Decision Maker.
            </p>
            <button type="button" onClick={handleJoin} style={primaryBtnStyle}>
              Join Active Session ({sessionState.joined_humans}/{sessionState.required_humans} Humans Joined)
            </button>

            <div
              style={{
                marginTop: 28,
                paddingTop: 16,
                borderTop: '1px solid #e5e7eb',
                fontSize: 13,
                color: '#6b7280',
              }}
            >
              <span>Switch Condition (Demo): </span>
              {['condition_1', 'condition_2', 'condition_3'].map((cKey) => (
                <button
                  key={cKey}
                  type="button"
                  onClick={() => handleReset(cKey)}
                  style={{
                    marginLeft: 6,
                    padding: '4px 10px',
                    borderRadius: 6,
                    border:
                      sessionState.condition_key === cKey
                        ? '1px solid #2563eb'
                        : '1px solid #d1d5db',
                    background: sessionState.condition_key === cKey ? '#eff6ff' : '#ffffff',
                    cursor: 'pointer',
                    fontSize: 12,
                  }}
                >
                  {cKey === 'condition_1'
                    ? '3 Humans'
                    : cKey === 'condition_2'
                    ? '2 Humans + 1 AI'
                    : '1 Human + 2 AI'}
                </button>
              ))}
            </div>
          </div>
        )}

        {!loading && sessionState && auth && sessionState.phase === 'WAITING' && (
          <WaitingRoom sessionState={sessionState} myParticipant={auth.participant} />
        )}

        {!loading && sessionState && auth && isDiscussion && (
          <ChatRoom
            sessionState={sessionState}
            myParticipant={auth.participant}
            onSendMessage={handleSendMessage}
          />
        )}

        {!loading && sessionState && auth && isVoting && (
          <VotingPanel
            sessionState={sessionState}
            myParticipant={auth.participant}
            onSubmitVote={handleSubmitVote}
          />
        )}

        {!loading && sessionState && auth && sessionState.phase === 'COMPLETED' && (
          <ResultsView sessionState={sessionState} myParticipant={auth.participant} />
        )}
      </div>
    </div>
  )
}

const primaryBtnStyle = {
  padding: '12px 24px',
  borderRadius: 8,
  border: 'none',
  background: '#2563eb',
  color: '#ffffff',
  fontWeight: 600,
  fontSize: 15,
  cursor: 'pointer',
}

const secondaryBtnStyle = {
  padding: '6px 12px',
  borderRadius: 6,
  border: '1px solid #d1d5db',
  background: '#ffffff',
  color: '#374151',
  fontSize: 13,
  fontWeight: 500,
  cursor: 'pointer',
}