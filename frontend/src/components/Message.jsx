import { useState } from 'react'

// One chat bubble. Assistant messages also render a collapsible "sources" panel that
// lists each cited journal entry together with the specific excerpt the answer was
// grounded in — the transparency that makes this read as a RAG system, not a black box.
export default function Message({ message }) {
  const { role, content, sources, isError } = message
  const [showSources, setShowSources] = useState(false)

  const hasSources = role === 'assistant' && sources && sources.length > 0

  return (
    <div className={`message ${role}` + (isError ? ' error' : '')}>
      <div className="bubble">
        {role === 'assistant' && !isError && (
          <div className="assistant-label">
            <span className="mark">✦</span>
            Journal
          </div>
        )}
        <div className="content">{content}</div>

        {hasSources && (
          <div className="sources-block">
            <button className="sources-toggle" onClick={() => setShowSources((v) => !v)}>
              {showSources ? '▾' : '▸'} {sources.length} source{sources.length > 1 ? 's' : ''}
            </button>
            {showSources && (
              <div className="sources">
                {sources.map((s, i) => (
                  <div className="source-entry" key={i}>
                    <div className="source-head">
                      {s.date && <span className="source-date">{s.date}</span>}
                      <span className="source-title">{s.title}</span>
                    </div>
                    {s.excerpt && <p className="source-excerpt">“{s.excerpt}”</p>}
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
