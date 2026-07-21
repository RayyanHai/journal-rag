// Thin fetch helpers over api.py. Paths are RELATIVE so the same code works in dev
// (Vite proxy -> :8000) and in the built app (served by api.py on the same origin).

async function postJson(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`)
  }
  return data
}

// message + prior turns -> { answer, standalone_question, tool_calls, sources }
export function sendChat(message, history) {
  return postJson('/chat', { message, history })
}

// kick off the ingest -> chunk -> database -> add_date_int rebuild (returns immediately)
export function startRefresh() {
  return postJson('/refresh')
}

// poll the background refresh -> { status, step, detail }
export async function getRefreshStatus() {
  const res = await fetch('/refresh/status')
  return res.json()
}
