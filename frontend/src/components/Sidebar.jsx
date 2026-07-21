import RefreshButton from './RefreshButton.jsx'

export default function Sidebar({
  conversations,
  activeId,
  setActiveId,
  createConversation,
  deleteConversation,
}) {
  return (
    <aside className="sidebar">
      <button className="new-chat" onClick={() => createConversation()}>
        + New chat
      </button>

      <RefreshButton />

      <nav className="convo-list">
        {conversations.length === 0 && <p className="empty-hint">No chats yet</p>}
        {conversations.map((c) => (
          <div
            key={c.id}
            className={'convo-item' + (c.id === activeId ? ' active' : '')}
            onClick={() => setActiveId(c.id)}
          >
            <span className="convo-title">{c.title || 'New chat'}</span>
            <button
              className="delete-btn"
              title="Delete chat"
              onClick={(e) => {
                e.stopPropagation()
                deleteConversation(c.id)
              }}
            >
              ×
            </button>
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">Journal RAG</div>
    </aside>
  )
}
