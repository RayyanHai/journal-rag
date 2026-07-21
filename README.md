# Journal RAG

A personal-journal question-answering engine over ~800 Notion journal entries
(~3,500 chunks). Ask it things like *"when was the last time I hung out with Alex?"*,
*"how have I been coping with stress lately?"*, or *"how many times did I go to the
gym in May?"* and it answers from your own entries, with dates cited.

Built to learn RAG fundamentals hands-on. The narrative of how it was built (and why)
lives in [BUILD_LOG.md](BUILD_LOG.md); this file is the current-state map.

## Architecture

**Offline — build the index (run once, re-run when you add entries):**

```
ingest.py    Notion API  -> data/raw/*.json        (one file per entry)
chunk.py     entries      -> data/chunks/*.json      (sentence/paragraph chunks + metadata)
database.py  chunks       -> data/chroma_db/         (embeds + loads into ChromaDB)
add_date_int.py  backfills a numeric date_int (YYYYMMDD) onto every chunk so dates
                 can be range-filtered ($gte/$lte). One-time migration.
```

**Query-time — answer a question:**

```
main.py            interactive chat loop
  └─ router.py     rewrites a follow-up into a standalone question using chat
                   history (Gemini). This is where conversational memory lives.
  └─ agent.py      the agent loop (Gemini). Given two tools, it searches,
                   inspects results, re-searches with adjusted filters if
                   needed, then answers — strictly from what it retrieved.
        ├─ tool: search_journal -> chroma_search.run_chroma_hybrid_search
        │        temporal-aware hybrid retrieval: date filter + (recency sort
        │        OR dense-vector + BM25 fused with RRF). Schema = query_constructor.JournalQuery.
        └─ tool: count_entries  -> chroma_search.count_journal_entries
                 deterministic EXACT count of matching entries (no top_k cap).
```

`query_constructor.py` defines the `JournalQuery` schema (search_text, keywords,
date bounds, recency) reused as the search tool's input contract; `construct_query()`
is also usable standalone for a cheap non-agentic parse.

## Running it

1. **Env** — create `.env`:
   ```
   NOTION_TOKEN=...          # only needed to (re)ingest
   NOTION_DATABASE_ID=...    # only needed to (re)ingest
   GEMINI_API_KEY=...        # from aistudio.google.com/apikey, needed at query time
   ```
2. **Deps** — `pip install chromadb sentence-transformers rank-bm25 openai python-dotenv pydantic notion-client`
   (Ollama is no longer required. Query-time LLM calls go through Gemini's
   OpenAI-compatible endpoint using `gemini-flash-latest`. The `openai` package
   is the client; no `google-genai` package needed.)
3. **Build the index** (first time only):
   `python ingest.py && python chunk.py && python database.py && python add_date_int.py`
4. **Chat:** `python main.py`

### Demo mode (no Notion, no personal data)

The repo ships a fictional 72-entry corpus (`demo/`) so anyone can run the full
system — same pipeline, same agent, same eval harness — without private data:

```
python demo/generate_demo_corpus.py     # write the synthetic entries (deterministic)
JOURNAL_DEMO=1 python chunk.py          # chunk them          (PowerShell: $env:JOURNAL_DEMO='1')
JOURNAL_DEMO=1 python database.py       # build the demo ChromaDB index (local, no API)
JOURNAL_DEMO=1 python main.py           # chat with the demo journal
JOURNAL_DEMO=1 python -m evals.harness  # score it against evals/golden_set_demo.py
```

`JOURNAL_DEMO=1` flips every path (corpus, index, golden set, baseline file) via
`config.py`; without it, everything uses the private `data/` corpus. Try asking:
*"When did I first hang out with Sam?"*, *"How many pottery classes have I been
to?"*, or the trap question *"Tell me about my trip to Iceland."* (there is no
trip — only a documentary — and it should say so).

Drive it programmatically (for tests / eval):
```python
from agent import answer_journal
r = answer_journal("How many gym visits in May 2026?", verbose=False)
r.answer        # the text answer
r.tool_calls    # [{"name","input"}, ...] — which tools ran with what args
r.sources       # [{"title","date"}, ...] — entries surfaced
```

### Web app (chat UI + refresh)

`api.py` is a thin FastAPI layer over the same engine — no RAG logic is duplicated:

```
python api.py          # serves on http://127.0.0.1:8000 (reads the real corpus)
```

- `POST /chat` — `{message, history}` → `{answer, standalone_question, tool_calls, sources}`.
  Stateless, exactly like `main.py`: the browser owns the history and sends it each
  turn; the server rewrites follow-ups (`router.py`) then runs the agent.
- `POST /refresh` + `GET /refresh/status` — re-run the offline pipeline
  (`ingest → chunk → database → add_date_int`) in the background to pull new Notion
  entries into the index. Refuses to run in demo mode (it rebuilds the real corpus).
- `GET /health` — liveness + whether the API key is set.

A `web/` directory, when present, is served from the same origin, so one command
runs both API and UI.

**Front-end** (React + Vite, ChatGPT-style: past chats in the sidebar, source-cited
answers, a Refresh-journal button). Source in `frontend/`:

```
# Dev (two terminals, hot reload):
python api.py                       # API on :8000
cd frontend && npm install && npm run dev   # UI on :5173 (proxies API calls to :8000)

# Or build once and serve everything from api.py on :8000:
cd frontend && npm run build        # emits ../web
python api.py                       # now serves API + UI together
```

Past chats persist in the browser (localStorage) — no database. Follow-ups are sent
with the conversation history so `router.py` can resolve “what did we eat then?”.

## Capabilities & known limits

- ✅ Temporal questions ("after Oct 9th", "last time", "first time", date ranges)
- ✅ Conceptual questions (hybrid vector + keyword search)
- ✅ Self-correcting re-search (handles misspellings/nicknames, empty results)
- ✅ Exact counting ("how many times…") via the deterministic count tool
- ✅ Honest failure — says "couldn't find it" instead of inventing
- ⚠️ Counts only what's *recorded* in the journal; "every session" isn't guaranteed
  if an activity wasn't written down.

## Legacy files (Phase 1, superseded — kept for reference)

`embed.py`, `search.py`, `generate.py`, `hybrid_search.py`, `data/vector_store.json`
were the original local-JSON vector store + Ollama/Llama3 pipeline, before the move
to ChromaDB and (at the time) Claude. Not used by the current query path, which has
since moved off Claude too — through `o4-mini` via GitHub Models, then
`llama-3.3-70b-versatile` via Groq, to Gemini now.

## Docs

- [BUILD_LOG.md](BUILD_LOG.md) — the full build history and design decisions (the *story*).
- [evals/EVAL_HARNESS.md](evals/EVAL_HARNESS.md) — how answer quality is measured:
  the five metrics, the golden set, variance, judge calibration, reproducibility.
- [evals/BASELINE_REPORT.md](evals/BASELINE_REPORT.md) — the current scoreboard and
  what the 2026-07-12 baseline run proved (Phase 5 fail→pass, faithfulness clean).
- [PHASE_5.md](PHASE_5.md) — design for the next capability: retrospective aggregation
  (the `insight` tier — per-day stats and recaps over a complete date range).
- [PHASE_6.md](PHASE_6.md) — the synthetic demo corpus: why it's hand-authored,
  the self-verifying ground truths, and the harness bug it caught on day one.
- [ROADMAP.md](ROADMAP.md) — beyond RAG: CI gate, structured-data layer, productionization.
