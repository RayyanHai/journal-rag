import { useEffect, useRef, useState } from 'react'
import Message from './Message.jsx'

const EXAMPLES = [
  { kind: 'Counts', text: '“How many times did I go to the gym in May?”' },
  { kind: 'Summaries', text: '“Summarize how work has been going lately.”' },
  { kind: 'Explanations', text: '“How have I been coping with stress?”' },
  { kind: 'Recall', text: '“When was the last time I hung out with ___?”' },
]

export default function ChatPane({ conversation, loading, error, onSend }) {
  const [input, setInput] = useState('')
  const endRef = useRef(null)
  const inputRef = useRef(null)
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
      <header className="chat-header">
        <span className="header-dot" />
        {conversation?.title || 'Journal RAG'}
      </header>

      <div className="messages">
        {messages.length === 0 && (
          <div className="welcome">
            <div className="welcome-mark">✦</div>
            <h1>Ask your journal</h1>
            <p>
              Search across everything you've written — moods, people, habits, and moments
              — in plain language. Ask for things like:
            </p>
            <ul className="examples">
              {EXAMPLES.map((e) => (
                <li key={e.kind} className="example">
                  <span className="example-kind">{e.kind}</span>
                  <span className="example-text">{e.text}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {messages.map((m, i) => (
          <Message key={i} message={m} />
        ))}

        {loading && (
          <div className="typing">
            <span className="dot" />
            Assistant is researching…
          </div>
        )}
        <div ref={endRef} />
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="composer-wrap">
        <form className="composer" onSubmit={submit}>
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about your journal…"
            autoFocus
          />
          <button type="submit" disabled={loading || !input.trim()} aria-label="Send">
            ↑
          </button>
        </form>
        <div className="composer-hint">
          Answers are grounded in your own journal entries.
        </div>
      </div>
    </main>
  )
}
