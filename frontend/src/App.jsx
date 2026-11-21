import React, { useCallback, useEffect, useState } from 'react'
import {
  advanceDiscussion,
  getActiveSession,
  getSessionState,
  joinSession,
  listTopics,
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
  const [topics, setTopics] = useState([])
  const [selectedTopicId, setSelectedTopicId] = useState('remote_work_policy')
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
      const [active, availableTopics] = await Promise.all([
        getActiveSession(),
        listTopics().catch(() => []),
      ])
      setSessionState(active)
      if (active?.selected_topic_id) {
        setSelectedTopicId(active.selected_topic_id)
      }
      if (availableTopics.length > 0) {
        setTopics(availableTopics)
      }
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

  const handleReset = async (conditionKey = null, topicId = null) => {
    setError(null)
    try {
      const next = await resetActiveSession(
        conditionKey || sessionState?.condition_key,
        topicId || selectedTopicId
      )
      saveAuth(null)
      setSessionState(next)
      if (next?.selected_topic_id) {
        setSelectedTopicId(next.selected_topic_id)
      }
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

  const previewTopic =
    topics.find((t) => t.topic_id === selectedTopicId) || sessionState?.selected_topic

  return (
    <div
      style={{
        minHeight: '100vh',
        background: '#f3f4f6',
        fontFamily: 'system-ui, -apple-system, sans-serif',
        color: '#111827',
        padding: '24px 16px',
        boxSizing: 'border-box',
      }}
    >
      <div style={{ maxWidth: 760, margin: '0 auto' }}>
        <header
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 20,
            gap: 12,
            flexWrap: 'wrap',
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
              onClick={() => handleReset(sessionState?.condition_key, sessionState?.selected_topic_id)}
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
              boxSizing: 'border-box',
              overflow: 'hidden',
            }}
          >
            <h2 style={{ marginTop: 0 }}>Join Experiment Session</h2>
            <p style={{ color: '#4b5563', maxWidth: 520, margin: '8px auto 18px' }}>
              You will be assigned a neutral identifier (Player A, Player B, or Player C).
              Discuss the locked scenario across two 1-minute rounds and vote for the Decision Maker.
            </p>

            {sessionState.selected_topic && (
              <div
                style={{
                  textAlign: 'left',
                  maxWidth: 560,
                  margin: '0 auto 20px',
                  padding: 14,
                  borderRadius: 8,
                  background: '#f8fafc',
                  border: '1px solid #cbd5e1',
                  boxSizing: 'border-box',
                }}
              >
                <div style={{ fontSize: 11, fontWeight: 700, color: '#2563eb', textTransform: 'uppercase' }}>
                  Active Session Topic (Locked)
                </div>
                <div style={{ fontSize: 16, fontWeight: 700, marginTop: 2 }}>
                  {sessionState.selected_topic.title}
                </div>
                <div style={{ fontSize: 13, color: '#475569', marginTop: 4 }}>
                  {sessionState.selected_topic.description}
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', marginTop: 6 }}>
                  Question: {sessionState.selected_topic.main_question}
                </div>
              </div>
            )}

            <button type="button" onClick={handleJoin} style={primaryBtnStyle}>
              Join Active Session ({sessionState.joined_humans}/{sessionState.required_humans} Humans Joined)
            </button>

            <div
              style={{
                marginTop: 28,
                paddingTop: 18,
                borderTop: '1px solid #e5e7eb',
                textAlign: 'left',
                maxWidth: 560,
                marginLeft: 'auto',
                marginRight: 'auto',
                boxSizing: 'border-box',
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 600, color: '#374151', marginBottom: 8 }}>
                New Session Setup (Condition &amp; Locked Discussion Topic)
              </div>

              {topics.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <label
                    htmlFor="topic-select"
                    style={{ display: 'block', fontSize: 12, color: '#6b7280', marginBottom: 6 }}
                  >
                    Select Discussion Topic (cannot be changed once session starts):
                  </label>
                  <div
                    style={{
                      display: 'flex',
                      gap: 8,
                      alignItems: 'center',
                      width: '100%',
                    }}
                  >
                    <select
                      id="topic-select"
                      value={selectedTopicId}
                      onChange={(e) => setSelectedTopicId(e.target.value)}
                      style={{
                        flex: 1,
                        minWidth: 0,
                        width: '100%',
                        padding: '8px 10px',
                        borderRadius: 6,
                        border: '1px solid #d1d5db',
                        fontSize: 13,
                        background: '#ffffff',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {topics.map((t) => (
                        <option key={t.topic_id} value={t.topic_id}>
                          {t.title} — {t.main_question}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => handleReset(sessionState.condition_key, selectedTopicId)}
                      style={{ ...secondaryBtnStyle, whiteSpace: 'nowrap', flexShrink: 0 }}
                    >
                      Start with Topic
                    </button>
                  </div>
                  {previewTopic && (
                    <div style={{ fontSize: 12, color: '#6b7280', marginTop: 6, lineHeight: 1.4 }}>
                      {previewTopic.description}
                    </div>
                  )}
                </div>
              )}

              <div style={{ fontSize: 13, color: '#6b7280', display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}>
                <span>Switch Condition:</span>
                {['condition_1', 'condition_2', 'condition_3'].map((cKey) => (
                  <button
                    key={cKey}
                    type="button"
                    onClick={() => handleReset(cKey, selectedTopicId)}
                    style={{
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
  padding: '7px 12px',
  borderRadius: 6,
  border: '1px solid #d1d5db',
  background: '#ffffff',
  color: '#374151',
  fontSize: 13,
  fontWeight: 500,
  cursor: 'pointer',
}