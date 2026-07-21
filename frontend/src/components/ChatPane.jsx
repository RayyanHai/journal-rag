import { useEffect, useRef, useState } from 'react'
import Message from './Message.jsx'

export default function ChatPane({ conversation, loading, error, onSend }) {
  const [input, setInput] = useState('')
  const endRef = useRef(null)
  const messages = conversation?.messages ?? []

  // keep the latest message in view as the conversation grows / while loading
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, loading])

  function submit(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    onSend(text)
  }

  return (
    <main className="chat-pane">
      <header className="chat-header">{conversation?.title || 'Journal RAG'}</header>

      <div className="messages">
        {messages.length === 0 && (
          <div className="welcome">
            <h1>Ask your journal</h1>
            <p>
              Try: “When was the last time I hung out with …?” · “How many times did I go
              to the gym in May?” · “How have I been coping with stress lately?”
            </p>
          </div>
        )}

        {messages.map((m, i) => (
          <Message key={i} message={m} />
        ))}

        {loading && <div className="typing">Assistant is researching…</div>}
        <div ref={endRef} />
      </div>

      {error && <div className="error-banner">{error}</div>}

      <form className="composer" onSubmit={submit}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your journal…"
          autoFocus
        />
        <button type="submit" disabled={loading || !input.trim()}>
          Send
        </button>
      </form>
    </main>
  )
}
