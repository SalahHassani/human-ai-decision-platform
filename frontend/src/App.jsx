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
import './styles/experiment1.css'

const STORAGE_KEY = 'chm_experiment_auth_v1'

const PHASE_STEPS = [
  { key: 'WAITING', label: '1. Lobby & Ready' },
  { key: 'ROUND_1_DISCUSSION', label: '2. Round 1 Chat' },
  { key: 'ROUND_1_VOTING', label: '3. Round 1 Vote' },
  { key: 'ROUND_2_DISCUSSION', label: '4. Round 2 Chat' },
  { key: 'ROUND_2_VOTING', label: '5. Final Vote' },
]

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

  const phase = sessionState?.phase || 'WAITING'
  const isDiscussion = phase === 'ROUND_1_DISCUSSION' || phase === 'ROUND_2_DISCUSSION'
  const isVoting = phase === 'ROUND_1_VOTING' || phase === 'ROUND_2_VOTING'
  const activeStepIndex = PHASE_STEPS.findIndex((s) => s.key === phase)

  const previewTopic =
    topics.find((t) => t.topic_id === selectedTopicId) || sessionState?.selected_topic

  return (
    <div className="exp1-shell">
      <div className="exp1-container">
        <header className="exp1-topbar">
          <div>
            <div className="exp1-brand-kicker">Research Workbench • Multi-Agent Decision Lab</div>
            <h1 className="exp1-title">Group Decision-Making Experiment</h1>
            <div className="exp1-meta-row">
              <span className="exp1-mono-tag">
                ID {sessionState?.session_id?.slice(0, 8) || '--------'}
              </span>
              {sessionState?.condition_key && (
                <span className="exp1-mono-tag">{sessionState.condition_key}</span>
              )}
              {auth?.participant && (
                <span>
                  Role: <strong>{auth.participant.display_name}</strong>
                </span>
              )}
              {auth && (
                <span
                  className={`exp1-status-dot ${connected ? 'is-live' : 'is-reconnecting'}`}
                >
                  {connected ? 'Live Stream' : 'Reconnecting'}
                </span>
              )}
            </div>
          </div>

          <div className="exp1-actions">
            {isDiscussion && (
              <button
                type="button"
                onClick={handleSkipTimer}
                className="exp1-btn exp1-btn-ghost-dark"
              >
                End Discussion Now
              </button>
            )}
            <button
              type="button"
              onClick={() =>
                handleReset(sessionState?.condition_key, sessionState?.selected_topic_id)
              }
              className="exp1-btn exp1-btn-ghost-dark"
            >
              Reset Session
            </button>
          </div>
        </header>

        {sessionState && (
          <nav aria-label="Experiment progression" className="exp1-stepper">
            {PHASE_STEPS.map((step, idx) => {
              const isCurrent = step.key === phase
              const isDone = phase === 'COMPLETED' || (activeStepIndex > idx && activeStepIndex !== -1)
              return (
                <div
                  key={step.key}
                  className={`exp1-step ${isCurrent ? 'is-active' : ''} ${isDone ? 'is-done' : ''}`}
                >
                  <span>{step.label}</span>
                </div>
              )
            })}
          </nav>
        )}

        {error && <div className="exp1-error">{error}</div>}

        {loading && (
          <div className="exp1-card" style={{ marginTop: 16, color: 'var(--slate-600)' }}>
            Loading session state...
          </div>
        )}

        {!loading && sessionState && !auth && (
          <div className="exp1-card" style={{ marginTop: 16, textAlign: 'center' }}>
            <h2 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 20 }}>
              Join Experiment Session
            </h2>
            <p
              style={{
                color: 'var(--slate-600)',
                maxWidth: 560,
                margin: '8px auto 0',
                fontSize: 14,
                lineHeight: 1.55,
              }}
            >
              You will be assigned a neutral identifier (Player A, Player B, or Player C).
              Collaborate on the locked scenario across two discussion rounds and vote for the
              Decision Maker.
            </p>

            {sessionState.selected_topic && (
              <div className="exp1-topic-box">
                <div className="exp1-topic-badge">Active Session Topic (Locked)</div>
                <div className="exp1-topic-title">{sessionState.selected_topic.title}</div>
                <p className="exp1-topic-desc">{sessionState.selected_topic.description}</p>
                <div className="exp1-topic-question">
                  Question: {sessionState.selected_topic.main_question}
                </div>
              </div>
            )}

            <button type="button" onClick={handleJoin} className="exp1-btn exp1-btn-primary">
              Join Active Session ({sessionState.joined_humans}/{sessionState.required_humans}{' '}
              Humans Joined)
            </button>

            <div className="exp1-setup-panel">
              <div className="exp1-label" style={{ fontSize: 13.5, color: 'var(--slate-800)' }}>
                New Session Setup (Condition &amp; Locked Discussion Topic)
              </div>

              {topics.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <label htmlFor="topic-select" className="exp1-label">
                    Select Discussion Topic (cannot be changed once session starts):
                  </label>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', width: '100%' }}>
                    <select
                      id="topic-select"
                      value={selectedTopicId}
                      onChange={(e) => setSelectedTopicId(e.target.value)}
                      className="exp1-select"
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
                      className="exp1-btn exp1-btn-secondary"
                      style={{ whiteSpace: 'nowrap', flexShrink: 0 }}
                    >
                      Start with Topic
                    </button>
                  </div>
                  {previewTopic && (
                    <div
                      style={{
                        fontSize: 12.5,
                        color: 'var(--slate-500)',
                        marginTop: 7,
                        lineHeight: 1.45,
                      }}
                    >
                      {previewTopic.description}
                    </div>
                  )}
                </div>
              )}

              <div className="exp1-condition-row">
                <span style={{ fontWeight: 600 }}>Switch Condition:</span>
                {['condition_1', 'condition_2', 'condition_3'].map((cKey) => (
                  <button
                    key={cKey}
                    type="button"
                    onClick={() => handleReset(cKey, selectedTopicId)}
                    className={`exp1-cond-pill ${
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
        )}

        <main className="exp1-main">
          {!loading && sessionState && auth && phase === 'WAITING' && (
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

          {!loading && sessionState && auth && phase === 'COMPLETED' && (
            <ResultsView sessionState={sessionState} myParticipant={auth.participant} />
          )}
        </main>
      </div>
    </div>
  )
}