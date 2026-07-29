import { useEffect, useState } from 'react'

// Past chats live in localStorage — no backend DB. Each conversation is
// { id, title, messages: [{ role, content, sources?, isError? }], createdAt }.
// A source is { title, date?, excerpt? } — excerpt is the passage the answer was cited from.
// Mutators take an explicit conversation id (never rely on a possibly-stale activeId
// closure inside async handlers).

const KEY = 'journal-rag-conversations'

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || []
  } catch {
    return []
  }
}

export function useConversations() {
  const [conversations, setConversations] = useState(load)
  const [activeId, setActiveId] = useState(() => load()[0]?.id ?? null)

  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify(conversations))
  }, [conversations])

  function createConversation() {
    const convo = { id: crypto.randomUUID(), title: 'New chat', messages: [], createdAt: Date.now() }
    setConversations((prev) => [convo, ...prev])
    setActiveId(convo.id)
    return convo.id
  }

  function deleteConversation(id) {
    setConversations((prev) => prev.filter((c) => c.id !== id))
    setActiveId((cur) => (cur === id ? null : cur))
  }

  // Append one message to a specific conversation, keeping the title synced to the
  // first user turn. Functional update, so concurrent appends never clobber each other.
  function addMessage(id, message) {
    setConversations((prev) =>
      prev.map((c) => {
        if (c.id !== id) return c
        const messages = [...c.messages, message]
        const firstUser = messages.find((m) => m.role === 'user')
        return { ...c, messages, title: firstUser ? firstUser.content.slice(0, 40) : c.title }
      }),
    )
  }

  const active = conversations.find((c) => c.id === activeId) || null

  return {
    conversations,
    active,
    activeId,
    setActiveId,
    createConversation,
    deleteConversation,
    addMessage,
  }
}
