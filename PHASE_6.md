# PHASE 6 — SYNTHETIC DEMO CORPUS (build log)

Goal for this step: *make the project publicly runnable without exposing a single
word of the real journal.* The repo's whole value is demonstrable behavior — but the
corpus it behaves ON is private and gitignored. This phase builds the stand-in:
a fictional corpus, indexed by the same pipeline, measured by a twin golden set.

This is the first phase with its own build-log file (one per phase from here on;
Phases 2.5–5 live in [BUILD_LOG.md](BUILD_LOG.md)).

---

## THE PROBLEM

Everything downstream of "make it public" was blocked on the same fact:

- **CI can't run** — GitHub Actions can't build an index from a journal that isn't
  in the repo.
- **Nobody can run the clone** — `pip install` succeeds and then every query dies on
  a missing ChromaDB.
- **A live demo would leak** — deploying the real index publishes my diary.

## DESIGN DECISIONS

- **Hand-authored, not LLM-generated.** Zero API quota spent, and — the real
  reason — every golden-set answer is true **by construction**. I control every
  word, so "how many pottery classes" has exactly one defensible answer. An
  LLM-generated corpus would need its ground truths *discovered*; this one has
  them *declared*.
- **Deterministic, with self-verifying ground truths.** `generate_demo_corpus.py`
  runs `verify_ground_truths()` before writing anything: entry count, date span,
  every load-bearing keyword count. Edit an entry, break an assertion, get told
  immediately — the corpus and its golden set can't silently drift apart.
- **One env var flips the whole stack.** New `config.py` centralizes the corpus
  paths (they were hardcoded in four files). `JOURNAL_DEMO=1` points chunking,
  indexing, retrieval, period analysis, the harness's golden set, AND the
  harness's baseline file (`baseline_demo.json`) at the demo corpus. A demo run
  can't touch — or even diff against — the private baseline.
- **The generator can't touch real data.** It hardcodes its output to
  `demo/data/raw/` relative to its own file, ignoring all env vars. Running it
  wrong is safe.
- **Substring landmines, documented.** Keyword matching is case-insensitive
  *substring* matching (`chroma_search._keyword_match`), so the word "same"
  contains "sam" — one careless filler sentence would corrupt the Sam hangout
  count. The generator's header documents this and the assertions enforce it.
  Flip side: it let me design a better misspelling case — "Mayya" does *not*
  contain "Maya", so that golden case can't pass by the answer merely echoing
  the question.

## THE CORPUS (72 entries, Sep 2025 → Jun 2026)

A fictional college student's journal, engineered so every question shape in the
real golden set has a demo twin with a provable answer:

| Ground truth | Value | Golden case it feeds |
|---|---|---|
| Sam: first / last hangout | 2025-09-14 / 2026-06-05 | "first time" / "last time" recency |
| Sam hangouts after 2026-03-01 | 3 (03-14, 05-16, 06-05) | bounded date-range retrieval |
| May 2026 entries | exactly 18 | exact count + completeness (`sources_count`) |
| May entries mentioning "gym" | exactly 6 → 6/18 ≈ 33% | count tool + insight percentage |
| "pottery" entries ever | exactly 4 | unbounded exact count |
| "Iceland" | 1 mention, a *documentary* | honest-failure trap ("my trip to Iceland") |
| Midterm arc | stress 04-19→21, exam 04-22 | conceptual retrieval + summarize recap |
| Entries after 2026-06-05 | zero | empty-week honest decline (insight) |

`evals/golden_set_demo.py`: 12 cases (9 current + 3 insight), same check fields,
same `EVAL_DATE` freeze (2026-06-30) as the real set.

## VERIFICATION (all zero-LLM except the smoke test)

1. **Generator assertions** — pass at generation time.
2. **Through the real retrieval code** against the built demo index: May total 18 ✓,
   May gym 6 ✓, pottery 4 ✓, Sam 8 entries first/last correct ✓, Iceland 1 ✓,
   last-week-of-June 0 ✓, `fetch_entries_in_range` May = 18 ✓.
3. **Real index untouched by the config refactor**: May 2026 count still 32 ✓.
4. **Agent smoke test** (3 cases, deterministic layers, quota-frugal):
   pottery count ✓, Sam recency ✓ (routing/retrieval/answer all pass), Iceland ✗ →
   which turned out to be a harness bug, below.

## A HARNESS BUG THE DEMO CORPUS CAUGHT ON DAY ONE

The Iceland smoke test failed — but the raw answer was *"you have not taken a trip
to Iceland"*, a perfectly honest, grounded decline. The scorer's `DECLINE_PHRASES`
list simply didn't contain that phrasing. This is the **same flake** that hit the
real baseline's Japan case (documented in
[evals/BASELINE_REPORT.md](evals/BASELINE_REPORT.md) as known-flaky).

Fix: widened `DECLINE_PHRASES` with the negation family ("have not", "haven't",
"never went", "no trip", …). Safe by design — the list is only consulted on
`honest_fail` cases, which *should* decline; the dangerous failure mode for this
scorer is narrowness (honest answers marked as hallucinations), not breadth.
Re-run: Iceland ✓.

The meta-lesson: the demo corpus paid for itself before it ever reached CI — a
second, independent corpus immediately re-triggered a known flake and turned it
from "observed once, shrugged" into a diagnosed-and-fixed scorer gap.

## WHAT THIS UNLOCKS

- **CI (next phase):** `generate → chunk → database → harness` runs entirely from
  the repo with one secret (the API key). Deterministic-layer runs diff against
  `baseline_demo.json`.
- **A deployable demo:** the future web UI can ship the demo index publicly.
- **A runnable README:** clone → `pip install` → build demo index → ask it
  questions, no Notion or personal data required.

## STILL OPEN

- `baseline_demo.json` doesn't exist yet — the full 12-case demo run (with
  `--judge`) should be done on fresh quota and saved, becoming the CI contract.
- `add_date_int.py` still hardcodes the real corpus path; it's a one-time
  migration the demo path never needs (`chunk.py` emits `date_int` now), noted
  here so nobody wonders.
