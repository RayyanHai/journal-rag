# Phase 5 — Retrospective Aggregation (the `insight` tier)

**Status:** IMPLEMENTED (2026-07-10). `analyze_period` and `summarize_period` are built
(`period_analysis.py`) and wired into the agent as tools. The `insight` tier went from
all-fail to: **routing 3/3, retrieval 1/1 (Q4 completeness = all 32 May entries), answer
1/1 (empty-week decline), judge 3/3** on a full `--tier insight --judge` run. Two
faithfulness misses remain and are understood: Q4 is a judge limitation (it can't verify
the deterministically-correct count of 32 and trips on metadata-vs-title date skew); Q3
was a minor real blemish (the recap fabricated a citation from the tool name + today's
date) — a grounding-rule tweak addresses it (unverified pending quota). Still to do:
refresh `evals/baseline.json` via a full 18-case `--judge --save` on quota reset. See §8.

---

## 1. The gap this closes

Every capability so far — temporal search, recency sort, exact counting, self-correcting
re-search — answers questions of the form *"find me the entry / entries that match."*
The system **retrieves a relevant sample** and answers from it.

The `insight` questions are a different shape entirely. Look at what they need:

| Question | What it actually requires |
|---|---|
| "Rate my productivity over the last week." | look at **every day** in a window (here: none exist) and report honestly |
| "What % of days this summer did I go outside / have a real outing?" | classify **every day** in a range, then compute a ratio |
| "How many days last month did I do nothing or just work at home?" | classify **every day** in a range, then count |
| "Tell me about how my final exam season went." | read **every entry** in a window and synthesize one coherent recap |

The common thread: they operate over the **complete set** of entries in a date range,
not a top-k relevant sample. RAG retrieves a sample — it literally cannot answer
"what fraction of all days" because it never sees all the days.

This is the **same lesson as the counting weakness** (Phase 3.5): "how many gym visits"
failed because the model tallied a `top_k`-capped retrieval instead of the full set,
and the fix was `count_entries` doing `collection.get` over the whole range. **Phase 5
generalizes that fix** — from *count* to *classify-then-aggregate* and *summarize* over
a complete range.

> The fundamental: retrieval answers "what / when"; it cannot answer "how many" or
> "what fraction" or "recap the whole period." Those are **dataset operations**, not
> search operations.

---

## 2. Two capability shapes

The four questions split into two shapes that share one primitive ("operate over the
complete set in a range"):

**A. Aggregate (map → reduce)** — Q2, Q4, and the empty case Q1.
Classify each entry/day over a full range on some dimension, then count or ratio.

**B. Summarize (reduce)** — Q3.
Read the full bounded range and synthesize a grounded recap.

---

## 3. Design

### 3.1 New tool: `analyze_period` (the aggregate shape)

```
analyze_period(date_after, date_before, dimension) -> structured stats
```

`dimension` is a natural-language classification criterion, e.g. *"the writer went
outside or had a real outing (not just working/being at home)"* or *"the writer did
nothing productive / only worked at home."*

Mechanics, in three deliberately separated stages:

1. **Fetch the complete set.** `collection.get` over the `date_int` range (no `top_k`
   cap), collapse chunks to distinct entries — reuse the exact distinct-parent logic
   already in `count_journal_entries` (`chunk_id.split("_chunk_")[0]`). → `[(date, title, text), ...]`.

2. **Map (classify).** For each entry, produce a boolean label on `dimension`, plus a
   one-clause justification. **Batched**: send ~10–15 entries per LLM call and get back
   a structured list `[{date, label, why}, ...]` via JSON mode (`parse_structured` with
   a list schema). Batching is not optional — see §5, quota.

3. **Reduce (aggregate).** Compute the stats **in Python, not the LLM**: total days,
   matched days, percentage, and the labeled list. Same principle as `count_entries` —
   never ask the model to do arithmetic it can get wrong.

Returns a structured object the agent narrates:

```json
{
  "total": 61,
  "matched": 22,
  "percentage": 36.1,
  "per_day": [{"date": "2026-06-05", "label": true, "why": "went to the lake with the tribe"}, ...]
}
```

### 3.2 New tool: `summarize_period` (the reduce shape)

```
summarize_period(date_after, date_before, focus) -> grounded recap text
```

1. Fetch the complete set in range (as above).
2. If it fits in context, one synthesis call over all entries. If the window is large,
   **hierarchical summarization**: summarize batches, then summarize the summaries
   (map-reduce summarization). Exam season is bounded (~2 weeks), so single-pass is
   likely fine; the hierarchical path is the safety valve for wider windows.
3. Same grounding rules as the answer agent — recap only what's in the entries.

### 3.3 Routing

The agent gains two tools and a routing rule:

- `analyze_period` → "what % of days…", "how many days did I [fuzzy criterion]…"
  (classification over a range).
- `summarize_period` → "tell me about / how did [period] go", "recap my…".
- `count_entries` stays for **keyword** counts ("how many times did I go to the gym");
  `analyze_period` is for **classification** counts where no single keyword captures it
  ("days I did nothing").
- `search_journal` stays for point lookups.

---

## 4. Why this design (decisions + rationale)

- **Deterministic reduce.** Counts and percentages computed in code. Continues the
  count-tool lesson: routing "how many / what fraction" to arithmetic-in-Python removes
  a whole class of hallucinated numbers.
- **Batched map.** Classifying entries one-by-one over a summer (~60 entries) would be
  ~60 calls and instantly blow the free tier. Batching 10–15 per call cuts it to ~4–6.
  Given the entire provider-migration saga was about quota, this constraint drives the
  design, not the other way around.
- **Structured intermediate (per-day labels).** The `per_day` list is not just for the
  answer — it lets the **eval harness score the classification step separately from the
  final number**, exactly the map/reduce separation the harness already rewards
  (retrieval vs generation). Phase 5 extends the "measure each step apart" philosophy
  into the new capability instead of bolting on an opaque black box.
- **Honest empty.** An empty range (Q1: the last 7 days from `EVAL_DATE` have no
  entries) must return "nothing recorded," never an invented recap. The grounding rules
  from the hallucination fix carry straight over.
- **Subjectivity is surfaced, not hidden.** "An interesting day" is fuzzy. The
  classifier applies a **stated, consistent definition**, and the answer states that
  definition so the percentage is interpretable rather than a magic number.

---

## 5. Risks / threats

- **Quota / cost.** Even batched, a wide range is many calls. Mitigations: batch size
  tuning, a hard cap on entries per analysis, and the option to run the *map* step on a
  cheaper/faster model than the *narrate* step.
- **Classification consistency.** The same day could be labeled differently across runs
  (stochastic). The harness's `--runs N` variance mode is exactly how we'll measure how
  flaky the classifier is, and the stated definition is how we reduce it.
- **Context limits for summarize.** Wide windows overflow context → hierarchical
  summarization is the fallback.
- **Latency.** Many sequential calls is slow. Acceptable for a personal research tool;
  a concern only if this ever goes interactive at scale.

---

## 6. How the eval harness measures Phase 5

The `insight` tier already encodes these four questions with judge rubrics, sitting at
expected-fail. Phase 5 is "done" when they climb to pass — provably, via the harness,
without regressing the `current` tier.

As the structured `per_day` output becomes available, upgrade the insight cases from
judge-only toward **deterministic** checks (more trustworthy than an LLM judge):

- Q1 (empty week) → `honest_fail` / decline check (should already be close with the
  frozen clock + existing tools; verify first — it may not even need new code).
- Q4 (days doing nothing) → `expect_count` once the true number is hand-verified.
- Q2 (% outside) → percentage within a tolerance band once hand-verified.
- **New failure mode to add: completeness.** Did `analyze_period` actually pull *every*
  entry in the range rather than a truncated set? Add a check that the analyzed count
  equals the known entry count for the window.

---

## 7. Build order (each step shippable and measurable)

1. **`analyze_period`** — fetch-complete + batched classify + deterministic reduce; wire
   as a tool; route Q4 and Q2. Run the harness, watch those two cases.
2. **Q1 (empty week)** — verify it passes with existing tools + frozen clock; add a
   deterministic decline check. (May need no new code — confirm before building.)
3. **`summarize_period`** — hierarchical summarization for Q3. Run the harness.
4. **Harden the golden set** — add completeness + per-day deterministic checks; convert
   insight cases off judge-only where a hand-verified truth exists.

Start at step 1 only after the current-tier baseline is green — you don't build a new
floor on an unmeasured foundation.

---

## 8. Build notes (what actually shipped, and deviations)

Implemented in [`period_analysis.py`](period_analysis.py), wired in [`agent.py`](agent.py):

- **`fetch_entries_in_range`** — the shared complete-set primitive: `collection.get` over
  the date range (no `top_k`), collapse chunks to distinct parents (`_chunk_` split, reused
  from `count_journal_entries`), and **reconstruct each entry's full text** by re-joining its
  chunks in order. Zero-LLM; validated (May 2026 → 32 entries, matching the known count).
- **`analyze_period`** — batched classify (`_BatchLabels` via `parse_structured`, ~12/call)
  + **deterministic Python reduce**. `per_day` carries the entry text so the faithfulness
  judge can ground against it (consistent with the task-#24 fix). Guarded by `MAX_ENTRIES`.
- **`summarize_period`** — single-pass synthesis, hierarchical (map-reduce) fallback for
  wide windows. **Capped at `SUMMARIZE_MAX_ENTRIES=60` most-recent** after a model
  over-scoped "exam season" to 800+ entries (a ~50-call quota bomb); `cap_recent` is shared
  with the agent's source list so both describe the same set.
- **Routing** — two new tool descriptions + a system-prompt rule; `count_entries` stays for
  keyword counts, `analyze_period` for classification counts, `summarize_period` for recaps.

Robustness fixes made while building (all quota-free, unit-verified):
- `llm_client._loads_lenient` — tolerate a trailing-prose / code-fence JSON response from
  the beta OpenAI-compat layer (a real `Extra data` crash surfaced from the classifier).
- `_classify_batch` degrades gracefully on a failed batch (leaves it unlabeled, keeps the
  deterministic total correct) instead of crashing.
- `answer_journal` now wraps tool-handler execution so one failing tool call can't crash a
  whole eval batch.

Golden-set hardening (§6, done): Q1 → deterministic `honest_fail` (judge dropped — it
false-alarmed on a decline that restates the empty window); Q4 → `sources_count: 32`
completeness; Q2/Q3 → `expect_tool` routing + rubrics rewritten to match reality (data ends
2026-06-10; denominator = journaled days). New `sources_count` check added to the harness.

**Deferred:** the full `--tier insight --judge` scoreboard + `--save` baseline refresh (quota
reset needed); a cheaper/faster model for the `map` step; hand-verified `expect_count` /
percentage-tolerance checks for Q4/Q2 to retire more judge reliance.

---

*See [`evals/EVAL_HARNESS.md`](evals/EVAL_HARNESS.md) for how the tiers and metrics
work, and [`ROADMAP.md`](ROADMAP.md) for what comes after Phase 5 (CI, going beyond
retrieval, productionization).*
