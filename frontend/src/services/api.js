const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const ADMIN_TOKEN = import.meta.env.VITE_ADMIN_TOKEN || 'dev-admin-token'

async function request(path, options = {}) {
  const { headers = {}, ...restOptions } = options

  const res = await fetch(`${API_URL}${path}`, {
    ...restOptions,
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
  })

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const data = await res.json()
      if (typeof data?.detail === 'string') {
        detail = data.detail
      } else if (Array.isArray(data?.detail)) {
        detail = data.detail.map((e) => e.msg).join(', ')
      }
    } catch {
      // ignore non-JSON error bodies
    }
    throw new Error(detail)
  }

  return res.json()
}

export function getActiveSession() {
  return request('/api/sessions/active')
}

export function resetActiveSession(conditionKey = null) {
  return request('/api/sessions/active/reset', {
    method: 'POST',
    headers: { 'X-Admin-Token': ADMIN_TOKEN },
    body: JSON.stringify(conditionKey ? { condition_key: conditionKey } : {}),
  })
}

export function joinSession(sessionId) {
  return request(`/api/sessions/${sessionId}/join`, {
    method: 'POST',
  })
}

export function getSessionState(sessionId) {
  return request(`/api/sessions/${sessionId}`)
}

export function sendMessage(sessionId, token, content) {
  return request(`/api/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'X-Participant-Token': token },
    body: JSON.stringify({ content }),
  })
}

export function submitVote(sessionId, token, targetId) {
  return request(`/api/sessions/${sessionId}/vote`, {
    method: 'POST',
    headers: { 'X-Participant-Token': token },
    body: JSON.stringify({ target_id: targetId }),
  })
}

export function advanceDiscussion(sessionId) {
  return request(`/api/sessions/${sessionId}/advance`, {
    method: 'POST',
    headers: { 'X-Admin-Token': ADMIN_TOKEN },
  })
}

export async function downloadSessionCsv(sessionId) {
  const res = await fetch(`${API_URL}/api/sessions/${sessionId}/export.csv`, {
    headers: { 'X-Admin-Token': ADMIN_TOKEN },
  })
  if (!res.ok) {
    throw new Error(`Export failed (HTTP ${res.status})`)
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `session_${sessionId}_export.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}