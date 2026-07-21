# JOURNAL RAG — BUILD LOG

A running engineering log, kept in my own note format. One section per major step.
Markdown over PDF on purpose — same reasoning as storing entries in JSON over PDF:
a build log gets **incremental updates**, and markdown appends clean where a PDF
re-renders everything. Export to PDF at milestones if a polished artifact is needed.

---

## PHASE 2.5 — TEMPORAL RETRIEVAL FIX

Goal for this step: *reiterate on the design and perfect our search for chunks.*

### THE BUG (what triggered this)
Asked: **"What else did I do with Alex after October 9th, 2025?"**
- System returned a **July 16th, 2024** entry as a top hit.
- Then claimed the most recent Alex mention was **Feb 12th, 2026**.
- I knew that was wrong — I'd mentioned Alex way more recently than that.

### DIAGNOSIS (proved it with the data, not vibes)
Scanned all 3,579 chunks for "Alex":
- **146 chunks** mention Alex.
- **79 of them are AFTER Oct 9th, 2025.**
- Most recent mention = **June 8th, 2026** (two weeks ago).

So the data was there the whole time. Three root causes in the retrieval:
1. **No temporal awareness.** `chroma_search` had a `date_filter` param, but `main.py`
   never passed one. "after October 9th" was treated as fuzzy text, not a constraint.
   The vector search returned whatever was semantically closest, ignoring the date.
2. **No concept of "most recent."** "When was the last time…" is a SORT BY DATE,
   not a similarity search. Vectors have no notion of recency. The real answer
   (June 8th) was never even in the candidate pool.
3. **Candidate pool too small.** Pulled only 15 nearest vectors out of 3,579, then
   returned top 3. The right entry was often ranked ~20th and never seen.

### DESIGN DECISIONS
- **Add a numeric `date_int` (YYYYMMDD) to metadata.** ChromaDB's `$gte`/`$lte`
  range operators only work on NUMBERS, not date strings. This is the one piece
  that makes real date filtering possible. Backfilled onto all 3,579 existing
  chunks *without re-embedding* (metadata-only update — vectors untouched).
- **Add a Query Construction ("self-querying") layer.** A cheap LLM call parses
  the natural-language question into structured retrieval params BEFORE hitting
  the DB. This is the missing brain that the old pipeline never had.
- **Two retrieval strategies, picked by the question type:**
  - *Recency* ("last/most recent/first time") → DETERMINISTIC. Filter by date +
    keyword, sort by date, done. Not every question is a similarity question.
  - *Conceptual* ("how have I been coping with stress?") → HYBRID. Dense vectors
    + BM25 fused with RRF, now with the date range applied to the candidate pool.
- **Use Haiku for the parse, keep Sonnet for the answer.** Query construction is
  a lightweight structured task — Haiku is near-instant and near-free. The final
  synthesis stays on Sonnet 4.6. (Both are one-line constants if I want to bump them.)
- **Fail safe.** If the parse call errors, fall back to a plain semantic search —
  retrieval never breaks because of the LLM step.

### WHAT I BUILT
- `add_date_int.py` — one-time migration, backfilled `date_int` onto all chunks.
- `chunk.py` — now emits `date_int` for all future ingests.
- `query_constructor.py` — `construct_query()` returns a structured `JournalQuery`
  (`search_text`, `keywords`, `date_after`, `date_before`, `recency`) via Claude
  structured outputs (Pydantic-validated). Resolves relative dates ("lately",
  "last year") against today.
- `chroma_search.py` — rewritten. Builds the `date_int` range filter, branches
  into the deterministic recency path vs the hybrid RRF path, widened the pool
  from 15 → 60, soft keyword focusing, case-insensitive keyword matching.
- `main.py` — chat loop now runs: rewrite (multi-turn) → construct → retrieve.

### RESULTS (before → after)
| Question | Old system | New system |
|---|---|---|
| "…with Alex after Oct 9th 2025?" | returned **July 2024** | all hits **post-Oct-9-2025** ✓ |
| "last time I hung out with Alex?" | claimed **Feb 12 2026** | **June 8 2026** (correct) ✓ |

Parser output for the failing query:
`{search_text: 'activities with Alex', keywords: ['Alex'], date_after: 20251009, recency: 'none'}`

### THE FUNDAMENTAL I LEARNED
Vector search is one tool, not the whole toolbox. A journal's most important
dimension is TIME, and time is structured data — you filter and sort it, you
don't embed it and hope. The job of the LLM here isn't to answer; it's to
translate a fuzzy human question into a precise database query.

### NEXT STEP (tee'd up, not done yet)
**Agentic re-search loop.** Let the model judge whether the retrieved chunks
actually answer the question, and if not, re-issue the search with adjusted
filters (widen the date range, drop a keyword, flip recency). This is the
"AI can re-prompt a search and change the filtering" idea. The constructor +
deterministic paths built here are the foundation it plugs into.
Also worth doing: upgrade the multi-turn rewriter off local Llama3 (it's weak)
— likely fold it into the constructor so one call does history + parsing.

---

## PHASE 3 — AGENTIC RE-SEARCH LOOP

Goal for this step: *let the AI re-prompt its own search and change the filtering.*

### THE LIMITATION (what triggered this)
Phase 2.5 made retrieval temporally aware, but it still searched **once** and
answered from whatever it got. If that single plan was wrong — keyword off
("Alex" vs a nickname), date window too tight, wrong recency intent — the answer
was wrong and nothing recovered. No second chance.

### THE FUNDAMENTAL: AGENTIC TOOL USE
Instead of US running retrieval for the model, we hand the model a TOOL and let
it drive. The model: searches → reads what came back → if it's empty or doesn't
answer, searches AGAIN with adjusted filters → answers once satisfied. This is
the canonical Anthropic agentic loop: give a tool, loop while `stop_reason ==
"tool_use"`, read the final text answer.

### DESIGN DECISIONS
- **Reuse, don't rebuild.** The `JournalQuery` schema from Phase 2.5 becomes the
  tool's input schema. `run_chroma_hybrid_search` becomes the tool's executor,
  unchanged. The work already done IS the agent's toolbox.
- **Bound the loop.** `MAX_SEARCHES = 4`. After that, force a final answer
  (`tool_choice="none"`) so a confused model can't loop forever.
- **Force the first search.** First turn uses `tool_choice={"type":"tool"}` so it
  always grounds in the journal before talking; `auto` after that.
- **Make the loop visible.** Every search prints `🔁 [Search N]: {args}` so I can
  literally watch the model change its filters between attempts. (This is the
  feature, and it's also the demo.)
- **Honest failure.** System prompt says: if you still can't find it after
  re-searching, say so — don't invent. (It now asks about nicknames instead.)

### WHAT I BUILT
- `agent.py` — `SEARCH_TOOL` (schema mirrors `JournalQuery` + `top_k`),
  `format_chunks()`, and `answer_journal()` (the manual streaming tool-use loop).
- `main.py` — gutted the single-shot construct→retrieve→answer block; the chat
  loop now just calls `answer_journal(search_query)`. Thinner, logic is testable
  in isolation.

### A BUG I CAUGHT WHILE TESTING
First run of "coping with stress **lately**": the model set `recency='latest'`,
which triggers the deterministic date-SORT path (ignores relevance) — it confused
"lately" with "latest". Two fixes:
1. Clarified the `recency` tool description: 'latest' SORTS by date and ignores
   relevance — only for "when was the last time" questions; "lately/recently"
   should use `date_after` with `recency='none'`.
2. Put **today's date in the agent's system prompt** so it can actually compute a
   "~60 days ago" window. After the fix it correctly used `date_after=20260425,
   recency='none'`.

### RESULTS (the loop actually re-searches)
| Question | Behavior observed |
|---|---|
| "last time I hung out with Alex?" | one-shot (`recency=latest`) → June 10 2026 ✓ |
| "coping with stress lately?" | 4 searches, reformulating the angle each time, hit the cap, answered ✓ |
| "…with Alex in October 2023?" | search empty → **re-searched** → still empty → honestly said "couldn't find it, nickname?" ✓ |

### PRESSURE TEST (adversarial battery)
Threw 6 hostile question shapes at the loop. It self-corrected on every one and
never hallucinated:

| Probe | Behavior |
|---|---|
| Earliest recency ("first hang out with Alex") | one-shot `recency='earliest'` → Jan 26 2023 ✓ |
| Two-bound range (Nov 2025–Jan 2026) | one-shot, both bounds, 5 cited entries ✓ |
| **Misspelled name ("Alxe")** | **3 searches** — tried `Alxe`, then `Alex+Alxe`, then dropped the date filter — then asked "is Alxe a nickname for Alex?" ✓ |
| Nonexistent event ("trip to Japan") | one search, honest "couldn't find it," no invention ✓ |
| Two-hop temporal ("stressed right before my calc exam") | 2 searches, anchored on calc entries, pulled the stress context ✓ |
| **Counting ("how many gym visits last month?")** | ⚠️ see weakness below |

### KNOWN WEAKNESS: COUNTING / AGGREGATION
The gym-count question exposed the inherent ceiling of RAG:
- Model said **"3 confirmed"** in prose, then **listed 4** — internally inconsistent.
- Counted **"inquire about a membership"** as a gym visit (not a workout).
- It tallied a **retrieved sample capped at `top_k`** — if I'd gone 15 times it
  literally cannot know. RAG retrieves a relevant SAMPLE, not a complete SET.

It hedged honestly ("could be higher"), but the number is unreliable by
construction. This is not a loop bug — it's "asking the LLM to count what it
retrieved." The fix is a deterministic path (see Next Step).

### THE FUNDAMENTAL I LEARNED
Single-shot RAG is brittle because it bets everything on one query being right.
Agentic RAG turns retrieval into a feedback loop: the model inspects its own
evidence and self-corrects. The trick is bounding it (`MAX_SEARCHES`) and giving
it honest exits so it self-corrects instead of spiraling or hallucinating.
AND: retrieval answers "what/when," but it can't answer "how many" — counting is
a database job, not a search job.

### NEXT STEP (tee'd up, not done yet)
- **Deterministic count tool** (surfaced by the pressure test). Add a second tool
  `count_entries(keywords, date_after, date_before)` that runs `collection.get`
  and returns the ACTUAL match count — no `top_k` cap, no LLM tallying. Agent
  picks `count_entries` for "how many," `search_journal` for "what/when." Also
  seeds the dashboard metrics from the REDESIGN notes.
- **Fix the multi-turn memory gap.** Sonnet still never sees `chat_history` (the
  Llama3 router compensates by rewriting). Fold history into the agent so it has
  real conversational memory — and probably retire Llama3 while doing it.
- Optional: a `verbose` flag to quiet `run_chroma_hybrid_search`'s per-search
  chunk dump once the loop is trusted.

---

## PHASE 3.5 — BACKEND FINALIZATION (pre-eval)

Goal for this step: *close the retrieval + chat-history gaps and make the backend
drivable by code, so the next phase (an eval harness) has something clean to test.*

### 1. DETERMINISTIC COUNT TOOL (fixes the counting weakness)
- `chroma_search.count_journal_entries(keywords, date_after, date_before)` — pulls
  EVERY chunk in the date range (`collection.get`, no `top_k`), keeps keyword
  matches, and counts **distinct entries** (collapses chunks via
  `chunk_id.split("_chunk_")[0]`). Returns exact count + the entry list.
- `agent.py` now has TWO tools. System prompt routes: `count_entries` for
  "how many", `search_journal` for "what/when". First turn forces `tool_choice="any"`
  (must use a tool, model picks which) instead of forcing search.
- Verified EXACT: `count_journal_entries(['gym'], 20260501, 20260531)` returns 2,
  matching a hand-rolled distinct-parent count. (The old agentic guess was "3–4".)

### 2. CHAT MEMORY — went with Option C (Claude rewriter, stateless agent)
Reminder of the fundamental: LLMs are stateless; "memory" = re-sending context.
- **Chose C over native memory (A):** keep the agent stateless (one question in /
  one answer out) and resolve follow-ups upstream with a cheap **Claude Haiku**
  rewriter. Bonus: a stateless agent is exactly what an eval harness wants.
- `router.py` — swapped local Llama3 → Claude Haiku, same `rewrite_query` signature.
  Llama3 dependency (and `import ollama`) is gone.
- Verified: history "[…last hung with Alex → June 8 2026]" + "what did we eat?" →
  **"What did you eat with Alex on June 8, 2026?"** (Llama3 used to mangle this.)

### 3. EVAL-READY CALLABLE
- `answer_journal(question, verbose=True)`. `verbose=False` runs SILENT (threads the
  flag into search + count) and returns a structured `AgentResult(answer, tool_calls,
  sources)` instead of a bare string — so the harness can check WHICH tool ran and
  WHICH entries were surfaced, not just the final text.
- `main.py` uses `result.answer`.

### 4. README
- Added `README.md`: the cold-open architecture map (offline index build +
  query-time path), how to run, capabilities/limits, and which old files are legacy.
  The build log is the *story*; the README is the *map*.

### THE FUNDAMENTAL I LEARNED
Two tools beat one prompt: routing "how many" to a deterministic DB count and
"what/when" to search removes a whole class of hallucinated numbers. And: design
the backend to be *callable* (quiet mode + structured return), not just
*interactive* — that's the difference between a demo and something you can measure.

### NEXT PHASE: EVAL HARNESS
Backend is now stateless, two-tooled, and drivable. Next: learn what an eval harness
is and build one — a fixed set of questions with known-correct answers/sources, run
`answer_journal(q, verbose=False)` over them, and score retrieval + answer quality so
changes can be proven to help instead of eyeballed.

---

## PHASE 4 — LEARNING NOTES: WHAT IS AN EVAL HARNESS

(Notes from learning the concept before building it.)

### WHAT IT IS
A test suite for ANSWER QUALITY, not code correctness. Unit tests = "does it run."
Eval harness = "does it give good answers," measured automatically over a fixed set
of questions with known-correct outcomes. Three parts: golden dataset (questions +
known answers) → runner (feed each through `answer_journal`) → scorer (output vs
expected → a number) → report.

### WHY EYEBALLING ISN'T ENOUGH
Hand-testing doesn't scale and isn't reproducible. The real killer: when I change
chunking / a prompt / top_k, I can't tell if I fixed one thing but broke three
others. (The "lately/latest" bug is exactly this — an eval would've caught it
instantly.) "Feels better" isn't a number; can't prove a gain or catch a regression.

### THE BIG FUNDAMENTAL: RAG FAILS IN TWO PLACES
A bad answer is ONE of two distinct failures, and they have DIFFERENT fixes:
1. RETRIEVAL failure — the right entry never got pulled. (LLM can't use context it
   never got.) Fix: chunking / search / filters.
2. GENERATION failure — right entry was pulled, but the model misread/ignored/invented.
   Fix: prompt / model.
Must measure SEPARATELY or you can't tell what to fix. This is why AgentResult has
separate fields: `.sources` (retrieval), `.answer` (generation), `.tool_calls`
(routing). I built that struct for exactly this moment.

### THE 3 LAYERS MY HARNESS SCORES
- ROUTING — right tool? (`count_entries` vs `search_journal`) ← `r.tool_calls`, exact.
- RETRIEVAL — did the expected entry surface? ← `r.sources`, "hit@k".
- ANSWER — correct AND not invented? ← `r.answer`, assert (dates/counts) or LLM-judge.

### SCORING FREE-TEXT ANSWERS
- Deterministic asserts: answer contains expected date/number/substring. Cheap, exact,
  brittle. Great for counts + dates.
- LLM-as-judge: a separate cheap Claude call grades correct? yes/no + why. Handles
  paraphrase; costs a bit; slight noise.
- Two named RAG metrics: FAITHFULNESS (is every claim supported by retrieved chunks? —
  catches hallucination) and ANSWER CORRECTNESS (matches known truth — catches being
  wrong even when grounded).
- Plan: deterministic for routing/retrieval/counts/dates; LLM-judge for free-text.

### HOW I'LL USE IT (the payoff)
Scientific method for the system: baseline score → change ONE thing → re-run → number
moved up/down/fixed-X-broke-Y → now I KNOW. Doubles as a regression net + a progress
meter. Building the golden set also forces me to define what "correct" means per
question.

### NEXT: build it
~20–40 golden questions (reuse the pressure-test cases — they already have known
answers), a runner over `answer_journal(q, verbose=False)`, layered scorers, a
scoreboard. Then establish the baseline.

---

## JUDGE FIX (task #24) — the faithfulness ruler was broken, not the model

Running the harness with `--judge`, faithfulness failed EVERYWHERE — flagging hyper-
specific terms (a niche anime title, a hole-in-the-wall restaurant name) as hallucinations.
But a hallucinator invents bland filler; it doesn't invent an oddly specific restaurant name.
Those came straight out of the entries.

### DIAGNOSIS
The bug was in the ruler, not the system. The faithfulness judge only ever saw each
source's **title + date**, never the **chunk text** the model actually read. So every
specific drawn from the chunk body looked "unsourced" — the metric was structurally
incapable of passing any grounded answer, only honest declines. The earlier 100% judge
calibration was falsely reassuring: I'd curated those cases to be decidable from titles
alone, validating the judge only on the inputs it could handle.

### FIX
- `AgentResult.sources` now carry the chunk `text` (search/analyze/summarize alike), and
  `_sources_block` feeds it to the judge — genuine claim-vs-text grounding.
- Rebuilt the calibration set to be decidable from the entry text, with a deliberate
  **false-alarm guard** (idiosyncratic-but-real specifics MUST pass) and a **date-skew
  guard** (metadata date is ground truth even when the title embeds a skewed date).
- Added `--filter` / `--tier` for cheap, targeted re-runs (no full-suite quota burn).

### RESULT
Re-ran the two free-text cases against the fixed ruler: **faithfulness 2/2**. The model
was grounded all along. Calibration 7/8 — the one miss is the cheap judge tripping on a
source that literally shows two different dates (metadata vs title); kept as an honest,
documented residual rather than overfitting the judge to pass it.

---

## PHASE 5 — RETROSPECTIVE AGGREGATION (the `insight` tier)

Goal: answer questions that operate over the **complete set** of entries in a range, not
a top-k relevant sample — "what % of days…", "how many days did I do nothing", "recap
exam season". RAG retrieves a sample; it literally can't answer "what fraction of all
days." Same lesson as the counting fix, generalized from *count* to *classify-then-
aggregate* and *summarize*. Full design in [`PHASE_5.md`](PHASE_5.md).

### WHAT I BUILT ([`period_analysis.py`](period_analysis.py))
- **`fetch_entries_in_range`** — the missing primitive: the whole set in a range (no
  `top_k`), chunks re-joined into full entry text. (Sanity: May 2026 → 32 entries, matches
  the known count.)
- **`analyze_period`** (map→reduce) — batched LLM classify (~12/call, quota-driven) →
  **deterministic Python** count/percentage. Never let the model do the arithmetic.
- **`summarize_period`** (reduce) — grounded recap; single-pass, hierarchical fallback.

### WHAT THE FIRST RUN TAUGHT ME (measure, then fix)
- The LLM judge is the **wrong instrument** for aggregates — it doesn't know the data ends
  2026-06-10 or the true counts, so it *penalized correct answers*. So I did what PHASE_5
  §6 said: moved insight cases toward **deterministic** checks — Q1 → decline, Q4 →
  `sources_count: 32` completeness. Those pass.
- **Range overclaim** (Q2 said "June 1-30" when data ends June 10) and **dropped per-day
  dates** (Q4 said "4 days" with no dates) — fixed in `format_analysis` narration. Q2 now
  reports "80% of the 10 journaled days" and lists them.
- A model over-scoped "exam season" to **807 entries** → a ~50-call hierarchical **quota
  bomb**. Added `SUMMARIZE_MAX_ENTRIES=60` (most-recent), shared with the source list.
- The classifier hit a real `Extra data` JSON crash (beta endpoint appended prose) that
  **crashed the whole eval run**. Fixed at the root (`_loads_lenient`), made
  `_classify_batch` degrade gracefully, and wrapped tool dispatch so one bad call can't
  take down a batch.

### CLOSED (2026-07-12)
Full 18-case `--judge --save` run completed on quota reset: faithfulness 5/5 (zero
hallucination flags), six fail→pass flips vs the pre-Phase-5 baseline, insight tier
routing/retrieval/answer all passing. The official fail→pass is locked into
`evals/baseline.json`; full write-up in [`evals/BASELINE_REPORT.md`](evals/BASELINE_REPORT.md).
