# WEB API — a thin HTTP layer over the existing engine.
#
# The engine is already a clean callable (agent.answer_journal); this file does NOT
# reimplement any RAG logic. It exposes two things the CLI (main.py) already does,
# so a browser front-end can drive them:
#
#   POST /chat            one question -> one answer (mirrors main.py's loop exactly:
#                         rewrite follow-ups via router, then run the agent). STATELESS —
#                         the browser owns the history and sends it each turn, matching
#                         the engine's stateless-by-design contract.
#   POST /refresh         re-run the offline pipeline (ingest -> chunk -> database ->
#                         add_date_int) to pull new Notion entries into the index. Runs
#                         in a background thread; poll GET /refresh/status for progress.
#   GET  /refresh/status  current refresh state (idle | running | done | error).
#   GET  /health          liveness + whether the API key is configured.
#
# CORPUS: this server reads whatever config.py selects. Leave JOURNAL_DEMO unset to run
# against the REAL journal (the point — using it on your own data). Set JOURNAL_DEMO=1
# before launching to demo on the synthetic corpus instead. NOTE: /refresh always
# rebuilds the REAL corpus (ingest/add_date_int are hardcoded to data/), so only call
# it when running in real mode.

import os
import subprocess
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from agent import answer_journal
from router import rewrite_query

PROJECT_ROOT = Path(__file__).parent

app = FastAPI(title="Journal RAG API", version="1.0")

# Local dev: the front-end may be served from a different origin (e.g. a live-server
# on :5500) while the API runs on :8000. Allow localhost so the browser can call it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local single-user tool; not exposed publicly
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ /chat

class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = Field(default_factory=list)


class Source(BaseModel):
    title: str
    date: str | None = None


class ChatResponse(BaseModel):
    answer: str
    standalone_question: str  # what the rewriter produced (== message on the first turn)
    tool_calls: list[dict]
    sources: list[Source]


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message.")
    if "GEMINI_API_KEY" not in os.environ:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not set on the server.")

    # Mirror main.py: rewrite a follow-up into a standalone question first, but only
    # when there's prior history to resolve pronouns/shorthand against.
    if req.history:
        history = [{"role": t.role, "content": t.content} for t in req.history]
        standalone = rewrite_query(history, req.message)
    else:
        standalone = req.message

    try:
        result = answer_journal(standalone, verbose=False)
    except Exception as e:
        # answer_journal handles its own internal failures, but guard the endpoint
        # so an unexpected error is a clean 500, not a broken response.
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

    # Sources come back one-per-CHUNK, so the same entry appears multiple times when
    # several of its chunks are retrieved. Dedupe to one row per entry (date, title) —
    # the UI shows entries, not chunks. Drop the heavy chunk `text` too; the UI only
    # needs title + date. (The engine keeps text internally for the faithfulness judge.)
    seen = set()
    sources = []
    for s in result.sources:
        key = (s.get("date"), s.get("title"))
        if key in seen:
            continue
        seen.add(key)
        sources.append(Source(title=s.get("title", "Untitled"), date=s.get("date")))
    return ChatResponse(
        answer=result.answer,
        standalone_question=standalone,
        tool_calls=result.tool_calls,
        sources=sources,
    )


# ------------------------------------------------------------------ /refresh

# The refresh pipeline, in order. Each is a standalone script run as its own process
# (same as running them by hand), so a crash in one is isolated and reported per-step.
REFRESH_STEPS = ["ingest.py", "chunk.py", "database.py", "add_date_int.py"]

# Single shared refresh state. Guarded by a lock because /refresh (writer, from the
# background thread) and /refresh/status (reader, from request threads) race otherwise.
_refresh_lock = threading.Lock()
_refresh_state = {
    "status": "idle",   # idle | running | done | error
    "step": None,       # which script is running / failed
    "detail": None,     # error tail on failure, summary on success
}


def _run_refresh():
    for script in REFRESH_STEPS:
        with _refresh_lock:
            _refresh_state["step"] = script
        proc = subprocess.run(
            [sys.executable, script],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-500:]
            with _refresh_lock:
                _refresh_state.update(status="error", detail=f"{script} failed:\n{tail}")
            return
    with _refresh_lock:
        _refresh_state.update(status="done", step=None, detail="Index rebuilt from Notion.")


class RefreshStatus(BaseModel):
    status: str
    step: str | None = None
    detail: str | None = None


@app.post("/refresh", response_model=RefreshStatus)
def refresh():
    if os.getenv("JOURNAL_DEMO", "").strip().lower() in ("1", "true", "yes"):
        raise HTTPException(
            status_code=409,
            detail="Refusing to refresh in demo mode — the pipeline rebuilds the REAL "
                   "corpus. Restart the server without JOURNAL_DEMO to refresh your journal.",
        )
    with _refresh_lock:
        if _refresh_state["status"] == "running":
            raise HTTPException(status_code=409, detail="A refresh is already running.")
        _refresh_state.update(status="running", step=REFRESH_STEPS[0], detail=None)

    threading.Thread(target=_run_refresh, daemon=True).start()
    return RefreshStatus(**_refresh_state)


@app.get("/refresh/status", response_model=RefreshStatus)
def refresh_status():
    with _refresh_lock:
        return RefreshStatus(**_refresh_state)


# ------------------------------------------------------------------ /health

@app.get("/health")
def health():
    return {
        "ok": True,
        "gemini_key_set": "GEMINI_API_KEY" in os.environ,
        "demo_mode": os.getenv("JOURNAL_DEMO", "").strip().lower() in ("1", "true", "yes"),
    }


# ------------------------------------------------------------------ static front-end
# When a web/ directory exists (built in the next step), serve it from the same origin
# so one `python api.py` launches both API and UI. Mounted LAST so it can't shadow the
# API routes above. Harmless no-op until web/ exists.
_WEB_DIR = PROJECT_ROOT / "web"
if _WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
