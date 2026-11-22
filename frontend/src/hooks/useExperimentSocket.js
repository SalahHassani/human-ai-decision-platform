// frontend/src/hooks/useExperimentSocket.js

import { useEffect, useRef, useState } from 'react'
import { getSessionState } from '../services/api'

const rawApiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const API_URL = rawApiUrl.startsWith('http')
  ? rawApiUrl.replace(/\/+$/, '')
  : `https://${rawApiUrl.replace(/\/+$/, '')}`
const WS_BASE = API_URL.replace(/^http/, 'ws')

export function useExperimentSocket(sessionId, token, onFullSync, onEvent) {
  const [connected, setConnected] = useState(false)
  const syncRef = useRef(onFullSync)
  const eventRef = useRef(onEvent)

  syncRef.current = onFullSync
  eventRef.current = onEvent

  useEffect(() => {
    if (!sessionId || !token) return undefined

    let ws = null
    let reconnectTimer = null
    let cancelled = false

    const resync = async () => {
      try {
        const freshState = await getSessionState(sessionId)
        if (!cancelled && syncRef.current) {
          syncRef.current(freshState)
        }
      } catch {
        // handled on manual refresh
      }
    }

    const connect = () => {
      if (cancelled) return
      ws = new WebSocket(`${WS_BASE}/ws/sessions/${sessionId}?token=${encodeURIComponent(token)}`)

      ws.onopen = () => {
        if (cancelled) return
        setConnected(true)
        resync()
      }

      ws.onmessage = (evt) => {
        if (cancelled) return
        try {
          const parsed = JSON.parse(evt.data)
          if (eventRef.current) {
            eventRef.current(parsed)
          }
        } catch {
          // ignore malformed frames
        }
      }

      ws.onclose = () => {
        if (cancelled) return
        setConnected(false)
        reconnectTimer = setTimeout(connect, 2000)
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      cancelled = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (ws) ws.close()
    }
  }, [sessionId, token])

  return { connected }
}

