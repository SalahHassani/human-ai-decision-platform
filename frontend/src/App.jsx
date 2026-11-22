import React, { useCallback, useEffect, useRef, useState } from 'react'
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
import './styles/app.css'

const STORAGE_KEY = 'chm_experiment_auth_v1'

const PHASE_STEPS = [
  { key: 'WAITING', label: '01 Lobby' },
  { key: 'ROUND_1_DISCUSSION', label: '02 Round 1 Discussion' },
  { key: 'ROUND_1_VOTING', label: '03 Round 1 Vote' },
  { key: 'ROUND_2_DISCUSSION', label: '04 Round 2 Discussion' },
  { key: 'ROUND_2_VOTING', label: '05 Round 2 Vote' },
  { key: 'COMPLETED', label: '06 Results' },
]

export default function App() {
  const [sessionState, setSessionState] = useState(null)
  const [topics, setTopics] = useState([])
  const [selectedTopicId, setSelectedTopicId] = useState('remote_work_policy')
  const [topicMenuOpen, setTopicMenuOpen] = useState(false)
  const pickerRef = useRef(null)

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

  useEffect(() => {
    if (!topicMenuOpen) return undefined
    const handleClickOutside = (e) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target)) {
        setTopicMenuOpen(false)
      }
    }
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setTopicMenuOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [topicMenuOpen])

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
    setTopicMenuOpen(false)
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

  const phase = sessionState?.phase || 'WAITING'
  const isDiscussion = phase === 'ROUND_1_DISCUSSION' || phase === 'ROUND_2_DISCUSSION'
  const isVoting = phase === 'ROUND_1_VOTING' || phase === 'ROUND_2_VOTING'
  const activeStepIndex = PHASE_STEPS.findIndex((s) => s.key === phase)

  const previewTopic =
    topics.find((t) => t.topic_id === selectedTopicId) || sessionState?.selected_topic

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-info">
          <div className="app-kicker">Decision Studio • Research Platform</div>
          <h1 className="app-title">Group Decision-Making Experiment</h1>
          <div className="app-header-meta">
            <span className="app-chip-slate">
              Session {sessionState?.session_id?.slice(0, 8) || '--------'}
            </span>
            {sessionState?.condition_key && (
              <span className="app-chip-slate">{sessionState.condition_key}</span>
            )}
            {auth?.participant && (
              <span>
                You: <strong>{auth.participant.display_name}</strong>
              </span>
            )}
            {auth && (
              <span className={`app-live-dot ${connected ? 'is-live' : 'is-reconnecting'}`}>
                {connected ? 'Live' : 'Reconnecting'}
              </span>
            )}
          </div>
        </div>

        <div className="app-right-actions">
          {isDiscussion && (
            <button type="button" onClick={handleSkipTimer} className="app-btn app-btn-orange">
              End Discussion Now
            </button>
          )}
          <button
            type="button"
            onClick={() =>
              handleReset(sessionState?.condition_key, sessionState?.selected_topic_id)
            }
            className="app-btn app-btn-header"
          >
            Reset Session
          </button>
        </div>
      </header>

      {sessionState && (
        <div className="app-two-line-slate">
          <span className="app-two-line-accent">Locked Topic:</span>{' '}
          {sessionState.selected_topic?.title || 'Scenario'} —{' '}
          {sessionState.selected_topic?.main_question ||
            'Discuss and vote for the Decision Maker across two rounds.'}
        </div>
      )}

      {sessionState && (
        <nav aria-label="Session stages" className="app-phase-bar">
          {PHASE_STEPS.map((step, idx) => {
            const isCurrent = step.key === phase
            const isDone = activeStepIndex > idx && activeStepIndex !== -1
            return (
              <span
                key={step.key}
                className={`app-phase-pill ${isCurrent ? 'is-active' : ''} ${
                  isDone ? 'is-done' : ''
                }`}
              >
                {step.label}
              </span>
            )
          })}
        </nav>
      )}

      {error && <div className="app-error">{error}</div>}

      {loading && (
        <div className="app-card" style={{ marginTop: 18, color: 'var(--ink-muted)' }}>
          Loading session...
        </div>
      )}

      {!loading && sessionState && !auth && (
        <div className="app-workspace is-single">
          <div className="app-card" style={{ textAlign: 'center' }}>
            <h2 className="app-heading">Join Experiment Session</h2>
            <p className="app-subtext" style={{ maxWidth: 560, margin: '8px auto 0' }}>
              You will be assigned a neutral identifier (Player A, Player B, or Player C). Discuss
              the locked scenario across two timed rounds and vote for the Decision Maker.
            </p>

            {sessionState.selected_topic && (
              <div className="app-topic-panel">
                <span className="app-badge-mustard">Active Session Topic (Locked)</span>
                <div className="app-topic-title">{sessionState.selected_topic.title}</div>
                <p className="app-subtext" style={{ marginTop: 4 }}>
                  {sessionState.selected_topic.description}
                </p>
                <div className="app-topic-question">
                  Question: {sessionState.selected_topic.main_question}
                </div>
              </div>
            )}

            <button type="button" onClick={handleJoin} className="app-btn app-btn-primary">
              Join Active Session ({sessionState.joined_humans}/{sessionState.required_humans}{' '}
              Humans Joined)
            </button>

            <div className="app-setup-box">
              <div className="app-label" style={{ fontSize: 13.5 }}>
                New Session Setup (Condition &amp; Locked Discussion Topic)
              </div>

              {topics.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <label id="topic-picker-label" className="app-label">
                    Select Discussion Topic (cannot be changed once session starts):
                  </label>

                  <div className="app-topic-picker-row">
                    <div className="app-picker-wrapper" ref={pickerRef}>
                      <button
                        type="button"
                        aria-haspopup="listbox"
                        aria-expanded={topicMenuOpen}
                        aria-labelledby="topic-picker-label"
                        onClick={() => setTopicMenuOpen((o) => !o)}
                        className={`app-picker-trigger ${topicMenuOpen ? 'is-open' : ''}`}
                      >
                        <span className="app-picker-trigger-text">
                          <span className="app-picker-trigger-title">
                            {previewTopic?.title || 'Select a topic'}
                          </span>
                          {previewTopic?.main_question && (
                            <span className="app-picker-trigger-sub">
                              {previewTopic.main_question}
                            </span>
                          )}
                        </span>
                        <svg
                          className={`app-picker-chevron ${topicMenuOpen ? 'is-open' : ''}`}
                          width="16"
                          height="16"
                          viewBox="0 0 20 20"
                          fill="none"
                          aria-hidden="true"
                        >
                          <path
                            d="M5 7.5L10 12.5L15 7.5"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </button>

                      {topicMenuOpen && (
                        <div role="listbox" className="app-picker-menu">
                          {topics.map((t) => {
                            const isSelected = t.topic_id === selectedTopicId
                            return (
                              <button
                                key={t.topic_id}
                                type="button"
                                role="option"
                                aria-selected={isSelected}
                                onClick={() => {
                                  setSelectedTopicId(t.topic_id)
                                  setTopicMenuOpen(false)
                                }}
                                className={`app-picker-option ${isSelected ? 'is-selected' : ''}`}
                              >
                                <div className="app-picker-opt-header">
                                  <span className="app-picker-opt-title">{t.title}</span>
                                  {isSelected && (
                                    <span className="app-badge-mustard" style={{ fontSize: 10 }}>
                                      Selected
                                    </span>
                                  )}
                                </div>
                                <span className="app-picker-opt-question">{t.main_question}</span>
                              </button>
                            )
                          })}
                        </div>
                      )}
                    </div>

                    <button
                      type="button"
                      onClick={() => handleReset(sessionState.condition_key, selectedTopicId)}
                      className="app-btn app-btn-secondary"
                      style={{ whiteSpace: 'nowrap', flexShrink: 0 }}
                    >
                      Start with Topic
                    </button>
                  </div>

                  {previewTopic && (
                    <div
                      style={{
                        fontSize: 12.5,
                        color: 'var(--ink-subtle)',
                        marginTop: 8,
                        lineHeight: 1.5,
                      }}
                    >
                      {previewTopic.description}
                    </div>
                  )}
                </div>
              )}

              <div className="app-cond-row">
                <span style={{ fontWeight: 600 }}>Switch Condition:</span>
                {['condition_1', 'condition_2', 'condition_3'].map((cKey) => (
                  <button
                    key={cKey}
                    type="button"
                    onClick={() => handleReset(cKey, selectedTopicId)}
                    className={`app-cond-btn ${
                      sessionState.condition_key === cKey ? 'is-selected' : ''
                    }`}
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
        </div>
      )}

      {!loading && sessionState && auth && (
        <div className="app-workspace">
          <main style={{ minWidth: 0 }}>
            {phase === 'WAITING' && (
              <WaitingRoom sessionState={sessionState} myParticipant={auth.participant} />
            )}

            {isDiscussion && (
              <ChatRoom
                sessionState={sessionState}
                myParticipant={auth.participant}
                onSendMessage={handleSendMessage}
              />
            )}

            {isVoting && (
              <VotingPanel
                sessionState={sessionState}
                myParticipant={auth.participant}
                onSubmitVote={handleSubmitVote}
              />
            )}

            {phase === 'COMPLETED' && (
              <ResultsView sessionState={sessionState} myParticipant={auth.participant} />
            )}
          </main>

          <aside className="app-inspector">
            <span className="app-badge-mustard">Locked Topic Brief</span>
            {sessionState.selected_topic ? (
              <>
                <h3
                  style={{
                    margin: '10px 0 6px',
                    fontFamily: 'var(--font-display)',
                    fontSize: 17,
                    color: 'var(--slate-950)',
                  }}
                >
                  {sessionState.selected_topic.title}
                </h3>
                <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5, color: 'var(--ink-muted)' }}>
                  {sessionState.selected_topic.description}
                </p>
                <div
                  style={{
                    marginTop: 10,
                    paddingTop: 10,
                    borderTop: '1px solid var(--border-light)',
                    fontSize: 13,
                    fontWeight: 600,
                    color: 'var(--slate-800)',
                  }}
                >
                  {sessionState.selected_topic.main_question}
                </div>
              </>
            ) : (
              <p className="app-subtext">No scenario loaded.</p>
            )}

            <div
              style={{
                marginTop: 18,
                paddingTop: 14,
                borderTop: '1px solid var(--border-light)',
              }}
            >
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  color: 'var(--ink-subtle)',
                  marginBottom: 8,
                }}
              >
                Group Roster
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {(sessionState.participants || []).map((p) => {
                  const isMe = p.id === auth.participant?.id
                  return (
                    <div key={p.id} className={`app-roster-row ${isMe ? 'is-me' : ''}`}>
                      <span style={{ fontWeight: 600 }}>
                        {p.display_name} {isMe ? '(You)' : ''}
                      </span>
                      <span
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: 11,
                          color: p.is_connected ? 'var(--orange-ink)' : 'var(--ink-subtle)',
                        }}
                      >
                        {p.is_connected ? 'ACTIVE' : 'PENDING'}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}

