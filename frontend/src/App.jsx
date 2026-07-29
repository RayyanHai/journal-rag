import { useState } from 'react'
import Sidebar from './components/Sidebar.jsx'
import ChatPane from './components/ChatPane.jsx'
import { useConversations } from './hooks/useConversations.js'
import { sendChat } from './api.js'

export default function App() {
  const convos = useConversations()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSend(text) {
    setError(null)

    // Ensure there's a conversation to write into. createConversation returns the id
    // synchronously, so we can target it even though the state update is async.
    let id = convos.activeId
    const exists = convos.conversations.some((c) => c.id === id)
    if (!id || !exists) {
      id = convos.createConversation()
    }

    // History = prior turns of THIS conversation (before the new message). Empty for a
    // brand-new chat, which is exactly when the backend skips the follow-up rewrite.
    const convo = convos.conversations.find((c) => c.id === id)
    const history = (convo?.messages ?? [])
      .filter((m) => !m.isError)
      .map((m) => ({ role: m.role, content: m.content }))

    convos.addMessage(id, { role: 'user', content: text })
    setLoading(true)
    try {
      const res = await sendChat(text, history)
      convos.addMessage(id, {
        role: 'assistant',
        content: res.answer,
        sources: res.sources,
      })
    } catch (e) {
      setError(e.message)
      convos.addMessage(id, { role: 'assistant', content: `⚠️ ${e.message}`, isError: true })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <Sidebar
        conversations={convos.conversations}
        activeId={convos.activeId}
        setActiveId={convos.setActiveId}
        createConversation={convos.createConversation}
        deleteConversation={convos.deleteConversation}
      />
      <ChatPane
        conversation={convos.active}
        loading={loading}
        error={error}
        onSend={handleSend}
      />
    </div>
  )
}
