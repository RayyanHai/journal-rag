import { useState } from 'react'

// One chat bubble. Assistant messages also render source citation chips and a
// collapsible "retrieval details" panel (the rewritten search query + which tools ran)
// — the transparency that makes this read as a RAG system, not a black box.
export default function Message({ message }) {
  const { role, content, sources, standalone, toolCalls, isError } = message
  const [showDetails, setShowDetails] = useState(false)

  const hasDetails = role === 'assistant' && (standalone || (toolCalls && toolCalls.length > 0))

  return (
    <div className={`message ${role}` + (isError ? ' error' : '')}>
      <div className="bubble">
        <div className="content">{content}</div>

        {role === 'assistant' && sources && sources.length > 0 && (
          <div className="sources">
            {sources.map((s, i) => (
              <span className="source-chip" key={i}>
                {s.date ? `${s.date} · ` : ''}
                {s.title}
              </span>
            ))}
          </div>
        )}

        {hasDetails && (
          <div className="details">
            <button className="details-toggle" onClick={() => setShowDetails((v) => !v)}>
              {showDetails ? 'Hide' : 'Show'} retrieval details
            </button>
            {showDetails && (
              <div className="details-body">
                {standalone && (
                  <div>
                    <strong>Searched:</strong> {standalone}
                  </div>
                )}
                {toolCalls &&
                  toolCalls.map((t, i) => (
                    <div key={i}>
                      <strong>{t.name}</strong> {JSON.stringify(t.input)}
                    </div>
                  ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
