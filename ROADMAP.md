# Roadmap — beyond RAG

Where this project goes after the retrieval engine and Phase 5. The organizing idea:

> The eval harness is the backbone. Every item below is only worth doing if you can
> **prove** it helped — and the harness is what turns "I changed something" into "I
> moved this number without breaking that one." So the roadmap isn't a feature list;
> it's a series of measurable deltas.

Ordered roughly by what unlocks the most with the least, but each section stands alone.

---

## 1. Near-term: a CI gate for the harness

Right now the harness is run by hand. The next maturity step is making it **automatic**,
so a regression can't merge silently.

**What it does:** on every change to core files (`agent.py`, `chroma_search.py`,
`query_constructor.py`, prompts), run the harness and **fail the build on a
`pass -> fail` diff** against the committed baseline. The regression net becomes a guard
rail instead of a thing you remember to check.

**The real constraints (and how to handle them):**

- **It costs API calls.** The harness runs the actual agent, so CI needs an API key as a
  secret and burns quota on every run. Mitigation: run the **deterministic layers only**
  (`routing` / `retrieval` / `answer`, no `--judge`) on pull requests — cheaper, faster,
  fully reproducible — and reserve the full `--judge` run for a **nightly** job.
- **Non-determinism.** LLM output varies, so a single CI run can false-alarm. Mitigation:
  run `--runs 3` and hard-fail only on a clean `pass -> fail`; treat `flaky` as a warning,
  not a build break.
- **The baseline is the contract.** `baseline.json` is committed; CI diffs against it.
  Updating it becomes a deliberate, reviewed act ("we intend this behavior change"),
  which is exactly the discipline you want.

**Concrete first step:** a GitHub Actions workflow that runs
`python -m evals.harness` (deterministic only) on PRs touching core files, plus a
scheduled nightly `--judge` run that posts the scoreboard.

---

## 2. Going beyond retrieval

RAG treats the journal as a **text corpus you search**. The more powerful framing is the
journal as a **queryable dataset you compute over**. Phase 5 (`analyze_period`) is the
first step onto that path; these extend it.

- **Structured extraction layer.** Batch-process every entry once into structured fields
  — people present, places, activities, mood, "productive?" — stored alongside the
  chunks. Then "how many days did I do nothing" becomes a **database filter**, not a live
  classification pass: cheaper, faster, deterministic, and reusable across questions.
  This is the natural generalization of `date_int` (Phase 2.5): if a dimension is worth
  filtering on, pre-compute it into metadata instead of inferring it at query time.
- **Proactive insights.** Instead of only answering asked questions, generate scheduled
  digests — a weekly "here's your week" or monthly trend summary. (The scheduling tooling
  to run this on a cron already exists in the environment.) The harness's `insight` tier
  is the same capability, just pushed instead of pulled.
- **Trend / time-series questions.** "Is my mood trending up since May?" needs the
  structured layer above plus a reduce over time. A stretch goal that falls out naturally
  once entries carry structured mood/productivity fields.
- **Conversational memory maturity.** Today `router.py` rewrites follow-ups into
  standalone questions (stateless agent). A real session-memory layer would let the agent
  reference earlier turns directly — worth it only if a golden-set multi-turn case shows
  the rewrite approach failing.
- **Multi-modal.** Entries reference photos; indexing image content would let "show me
  the day at the lake" work. Large scope; only if the text system is solidly measured
  first.

---

## 3. Productionization

Turning a CLI research tool into something usable day-to-day.

- **Web UI.** Replace the `main.py` chat loop with a small web front-end. The backend is
  already `answer_journal(question) -> AgentResult` — a clean callable, so this is a
  presentation layer, not a rewrite.
- **Incremental ingest.** Today the index is a full rebuild (`ingest -> chunk -> database
  -> add_date_int`). Watch Notion for new/edited entries and update only those chunks
  (metadata-only where possible, as `add_date_int` already does). Needed the moment the
  journal is actively growing.
- **Cost / latency controls.** Per-step model choice (cheap model for classify/rewrite,
  stronger for final synthesis), prompt caching for the stable system prompt, and a
  request budget. The provider-migration history is the argument for keeping the model
  choice a single swappable constant — which it already is.
- **Auth / multi-user.** Only if this is ever shared. Out of scope for a personal tool,
  noted for completeness.

---

## 4. Evaluation maturity (the meta-track)

The harness itself keeps improving in parallel with everything above:

- **Grow the golden set by failure taxonomy**, not raw count — one case per known failure
  mode beats fifty redundant ones.
- **Richer faithfulness** — feed chunk text (not just titles+dates) to the faithfulness
  judge for true claim-level entailment. (Noted in `EVAL_HARNESS.md` §12.)
- **A second, independent judge** (or periodic human spot-checks) to catch systematic
  bias the single judge and small calibration set can't see.
- **Baseline history** — keep past baselines and chart metric movement over time, turning
  the scoreboard into a progress graph rather than a single snapshot.

---

## Suggested order if this were the priority

1. **Close the current-tier loop** (run the harness, confirm the hallucination fix, set
   the baseline). — *in progress now.*
2. **Phase 5, step 1** (`analyze_period`) — the highest-value new capability, and the
   harness is already set up to measure it (see [`PHASE_5.md`](PHASE_5.md)).
3. **CI gate (deterministic-only on PRs)** — cheap insurance once there's a stable
   baseline to protect.
4. **Structured extraction layer** — the unlock that makes most future questions cheap
   and deterministic.
5. Everything else, measured against the harness as it comes up.
