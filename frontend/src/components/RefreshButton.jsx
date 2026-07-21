import { useEffect, useRef, useState } from 'react'
import { startRefresh, getRefreshStatus } from '../api.js'

// Kicks off a journal refresh (ingest -> chunk -> database -> add_date_int) and polls
// the background job until it finishes. The pipeline re-embeds the whole corpus, so it
// can take a few minutes — the button shows the current step while it runs.
export default function RefreshButton() {
  const [status, setStatus] = useState('idle') // idle | running | done | error
  const [step, setStep] = useState(null)
  const [detail, setDetail] = useState(null)
  const pollRef = useRef(null)

  useEffect(() => () => clearInterval(pollRef.current), [])

  function startPolling() {
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const s = await getRefreshStatus()
        setStatus(s.status)
        setStep(s.step)
        setDetail(s.detail)
        if (s.status === 'done' || s.status === 'error') {
          clearInterval(pollRef.current)
        }
      } catch {
        // transient network hiccup while polling — keep trying
      }
    }, 1500)
  }

  async function onClick() {
    if (status === 'running') return
    setDetail(null)
    try {
      const s = await startRefresh()
      setStatus(s.status)
      setStep(s.step)
      startPolling()
    } catch (e) {
      setStatus('error')
      setDetail(e.message)
    }
  }

  const label =
    status === 'running'
      ? `Refreshing… ${step ?? ''}`
      : status === 'done'
        ? 'Journal updated ✓'
        : status === 'error'
          ? 'Refresh failed — retry'
          : '🔄 Refresh journal'

  return (
    <div className="refresh">
      <button className="refresh-btn" onClick={onClick} disabled={status === 'running'}>
        {label}
      </button>
      {status === 'error' && detail && <pre className="refresh-error">{detail}</pre>}
    </div>
  )
}
