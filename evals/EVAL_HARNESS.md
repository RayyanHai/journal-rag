# Eval Harness

A test suite for **answer quality**, not code correctness.

Unit tests answer *"does the code run?"* This harness answers *"does the system give
good answers?"* — measured automatically, over a fixed set of questions with known-
correct outcomes, so that a change to chunking, a prompt, `top_k`, or the model can
be **proven** to help instead of eyeballed.

It lives next to the thing it tests: `answer_journal()` in [`../agent.py`](../agent.py)
is the exact entry point both the interactive app and this harness call, so the
harness measures the real system, not a stand-in.

---

## 1. Why an eval harness at all

Hand-testing a RAG system doesn't scale and isn't reproducible. The specific thing
it can't do: when you change chunking / a prompt / `top_k`, you can't tell whether
you fixed one thing but silently broke three others. "Feels better" isn't a number —
you can't prove a gain, and you can't catch a regression. (The old `lately` vs
`latest` recency bug is exactly this shape: a one-word prompt tweak that an eval
would have caught the instant it regressed another case.)

An eval harness turns system development into the scientific method:

> baseline score → change **one** thing → re-run → the number moved up / down /
> fixed-X-but-broke-Y → now you **know**.

It doubles as a **regression net** (did this change break something that worked?)
and a **progress meter** (are the not-yet-built capabilities trending toward pass?).

---

## 2. The core idea: RAG fails in several distinct places

A single "wrong answer" is actually one of several different bugs, and they have
**different fixes**. You cannot tell them apart from the final text alone, so the
harness scores them as separate layers:

| Failure | What went wrong | Where you'd fix it |
|---|---|---|
| **Routing** | Wrong tool (searched when it should have counted) | tool descriptions / system prompt |
| **Retrieval** | The right entry was never pulled | chunking, search, date filters |
| **Faithfulness** | Right entry *was* pulled, model invented anyway | answer prompt / model |
| **Correctness** | Grounded, but doesn't actually satisfy the question | prompt / model / rubric |

This is why `AgentResult` (see `agent.py`) carries `.tool_calls`, `.sources`, and
`.answer` separately: each feeds a different layer. If you only scored the final
string you'd know *that* it failed but never *which half* to fix.

---

## 3. The five metrics

The layer names deliberately mirror the standard RAG-evaluation vocabulary (e.g.
RAGAS) so the scoreboard is legible to anyone who's read the literature.

| Layer | Question it answers | How it's scored | Source of truth |
|---|---|---|---|
| `routing` | Did it pick the right tool? | deterministic | `result.tool_calls` |
| `retrieval` | Did the right entry surface? (**hit@k**) | deterministic | `result.sources` |
| `answer` | Is the concrete answer correct? (dates/counts/declines) | deterministic | `result.answer` |
| `faithfulness` | Is every claim grounded in the sources? | **LLM-as-judge** | answer vs sources |
| `judge` | Does the free-text answer satisfy the rubric? | **LLM-as-judge** | answer vs rubric |

**Deterministic vs. LLM-judged.** The first three are exact string/date/set checks —
cheap, fast, and 100% reproducible. The last two grade free-text, which no substring
match can do, so they use a separate cheap model as a judge (see §8, and calibrate it
via §9). Deterministic checks are preferred wherever a question *has* a checkable
fact; the judge is reserved for genuinely open-ended answers.

**Why faithfulness and correctness (`judge`) are separate.** An answer can be
faithful but wrong (grounded in the sources yet missing what the rubric asked for),
or — worse — plausible but unfaithful (reads well, invents facts). Splitting them
means a failure tells you whether to fix *grounding* or *completeness*.

> **History worth knowing:** the faithfulness judge originally saw only source
> **titles + dates**, not chunk text. On the first full baseline that made it flag
> *every* real grounded specific (a restaurant's name, a show title) as invented — false
> hallucination alarms, because it never saw the text those came from. The judge now
> receives the retrieved chunk **text** too (`AgentResult.sources` carries it), so it
> does genuine claim-vs-text grounding. This is a case study in *fixing the ruler
> before trusting the measurement* — and in how a curated-to-be-easy calibration set
> (§9) can hide a broken metric until a real run exposes it.

---

## 4. The golden set

[`golden_set.py`](golden_set.py) is the list of questions with their known-correct
outcomes. Every "known answer" was verified against the real journal data during
planning (journal date range 2022-08-06 → 2026-06-10).

Each case declares **only** the checks that apply to it; the harness runs whichever
are present. Fields:

| Field | Type | Meaning |
|---|---|---|
| `tier` | str | `current` (ships today) or `insight` (not built yet — see below) |
| `q` | str | the question |
| `expect_tool` | str | which tool must be used (`search_journal` / `count_entries`) |
| `source_date` | str | this `YYYY-MM-DD` entry must appear in `result.sources` |
| `sources_after` | str | **every** source date must be strictly after this date |
| `sources_any_after` | str | **at least one** source date must be after this (soft signal for "lately") |
| `sources_between` | [lo,hi] | every source date must fall in `[lo, hi]` |
| `answer_contains` | [str] | all substrings must appear in the answer (case-insensitive) |
| `expect_count` | int | the count tool must return exactly this many entries |
| `honest_fail` | bool | answer must decline (not invent) for a nonexistent thing |
| `judge` | str | rubric for the LLM judge to grade free-text; also triggers the faithfulness check |

### Tiers = a built-in roadmap

- **`current`** — capability that ships today. This is the **regression net** and the
  baseline. These are expected to pass; a drop is a regression.
- **`insight`** — retrospective summarization (recaps, per-day stats, trends) the
  backend *can't do yet*. These are **expected to fail today**. They define the next
  phase, and we watch them go fail → pass as that capability gets built. Encoding
  known-unsupported questions as expected failures turns the roadmap into something
  measurable instead of a TODO list.

### The frozen clock (reproducibility)

Questions like *"Rate my productivity over the last week"* only have a **stable**
correct answer if *"the last week"* always means the same seven days. If the agent
resolved "today" against the wall clock, the same case could pass one day and fail
the next, and the baseline would rot.

So the golden set fixes a reference date, `EVAL_DATE = "2026-06-30"`, and the harness
passes it into `answer_journal(today=EVAL_DATE)`. The agent's system prompt is built
from that injected date (`build_system_prompt(today)` in `agent.py`), so every run
resolves relative dates identically. Production simply leaves `today=None` and gets
the real date. **Freezing the clock is what makes the eval reproducible.**

---

## 5. Architecture

```
golden_set.py         the fixed questions + known answers + EVAL_DATE
      │
      ▼
harness.run()         for each case (× N runs):
      │                 answer_journal(q, verbose=False, today=EVAL_DATE)
      ▼
scorers               routing / retrieval / answer      (deterministic)
      │               faithfulness / judge              (LLM-as-judge, --judge)
      ▼
_aggregate()          collapse N runs → per-layer pass RATE  {passed, of}
      │
      ▼
report() ─────────────► scoreboard + per-case table + judge notes
diff_against_baseline() ► what changed vs the last saved baseline
save_baseline() ──────► baseline.json   (with --save)
```

Companion module: [`judge_calibration.py`](judge_calibration.py) validates the judge
itself (§9).

---

## 6. Running it

```bash
python -m evals.harness                    # deterministic layers only, 1 run (free, fast)
python -m evals.harness --judge            # also run the faithfulness + rubric judges
python -m evals.harness --judge --runs 3   # 3 runs per case, report variance
python -m evals.harness --judge --save     # write the result as the new baseline

python -m evals.judge_calibration          # check the judge against human labels
```

Flags:

- `--judge` — enable the two LLM-judged layers. Costs a few model calls per free-text
  case; without it those columns show `·` (skipped).
- `--runs N` — run each case `N` times to measure variance (§7). Default `1`.
- `--save` — persist this run to `baseline.json` for future diffs.

> **Free-tier note.** The agentic loop can make several model calls per question
> (up to `MAX_SEARCHES` + a final answer), and `--judge` adds up to two more. A full
> `--judge --runs 3` pass is dozens of calls — mind the provider's daily quota. The
> harness paces requests (a short sleep between calls) and retries rate limits, but
> it will still burn through a stingy free tier fast.

---

## 7. Variance: a single run is a noisy sample

LLM output is **stochastic** — the same question can route differently, retrieve a
slightly different set, or phrase an answer that trips a judge on one run and not the
next. A single ✓/✗ hides that. `--runs N` runs each case `N` times and reports a
**pass rate** per layer:

- In the per-case table, a cell shows `3/3`, `2/3`, `0/3`, etc.
- A layer that passes **every** run is a clean **pass**; **zero** is a clean **fail**;
  anything in between is **flaky** (`?`), surfaced separately in the scoreboard as
  `(+k?)`.

Flakiness is itself a finding: a case that passes 2/3 of the time is not "passing,"
it's *unreliable*, and that's exactly the kind of thing a single-run baseline lulls
you into shipping. Treat a flaky critical case as a bug, not a rounding error.

---

## 8. LLM-as-judge, and scoring free text

Two ways to score a free-text answer, both used here:

- **Deterministic asserts** — the answer contains an expected date / number /
  substring, or a decline phrase. Cheap, exact, brittle. Great for counts, dates, and
  honest-failure checks (`answer_contains`, `expect_count`, `honest_fail`).
- **LLM-as-judge** — a separate cheap model grades the answer and returns
  `{passed, reason}`. Handles paraphrase and open-ended synthesis that no substring
  match can; costs a call and adds a little noise (which §9 measures).

Two named RAG metrics come out of the judge:

- **Faithfulness** — is every claim supported by the retrieved sources? Catches
  hallucination. (`score_faithfulness`)
- **Answer correctness** — does the answer match the known-correct rubric? Catches
  being wrong even when grounded. (`score_judge`)

---

## 9. Calibration: who judges the judge?

If the judge is the measurement instrument, an **uncalibrated instrument produces
numbers you can't trust.** A lenient judge launders hallucinations into passes; an
erratic one makes the whole scoreboard noise.

[`judge_calibration.py`](judge_calibration.py) measures the judge against a small set
of **hand-labeled** examples whose correct verdict is unambiguous — a blatantly
invented answer *must* fail; an exact grounded answer *must* pass. It runs the real
harness scorers over them and reports how often the judge agrees with the human label:

```bash
python -m evals.judge_calibration
# -> AGREEMENT: 7/7 (100%)   ... or lists the disagreements
```

High agreement ⇒ you can believe the harness's judge columns. Low agreement ⇒ fix
the judge prompt **before** trusting a run. The labels are written to be decidable
from the same limited view the judge gets (source titles + dates), so it's graded
fairly on the evidence it actually receives.

---

## 10. Reading a run

- **Per-case table** — one row per question, one column per layer. `✓` pass, `✗`
  fail, `·` not applicable, `?` / `k/n` flaky across runs.
- **Scoreboard** — per tier, per layer: `cases passing / applicable`, with flaky
  counted separately as `(+k?)`. `CURRENT` is the regression net (want all green);
  `INSIGHT` is the Phase-5 target (watch it climb over time).
- **Judge notes** — the one-line reason for every non-passing free-text layer. This
  is the highest-signal output: it tells you *why* an answer failed, which is what
  points you at the fix.
- **Diff vs baseline** — every layer whose case-level verdict changed since the last
  saved baseline. This is the regression net firing: `pass -> fail` is a regression to
  investigate; `fail -> pass` is a win to keep.

### `baseline.json`

`--save` writes the run as the reference point future runs diff against: `saved_at`,
`eval_date`, `judge_enabled`, `runs_per_case`, and per-case per-layer `{passed, of}`
rates. The diff compares **case-level verdicts** (pass/fail/flaky) so a regression is
visible even if the underlying rate wobbled within the same verdict.

---

## 11. Worked example: separating a hallucination from a retrieval miss

The value of separated metrics, on a real bug found by this harness.

Question: *"How have I been coping with stress lately?"* The `judge` layer failed —
the answer invented movies, names, and apps not in the journal. But is that a
**retrieval** bug (bad chunks) or a **generation** bug (good chunks, model made
things up)? From the final answer alone you can't tell.

So the case carries **both** a retrieval check (`sources_any_after: 2026-04-30` — did
we surface any recent material at all?) *and* the judge rubric. Now the two layers
disambiguate:

- retrieval **pass** + faithfulness **fail** ⇒ the chunks were fine, the model
  hallucinated ⇒ fix the **answer prompt** (tighten grounding rules).
- retrieval **fail** ⇒ the model never got good material ⇒ fix **search / filters**.

That's the whole point of the design: the harness doesn't just say "this failed," it
says *which half to go fix.* (The fix here was hardening the grounding rules in
`build_system_prompt` — and the harness is how we'll confirm the number actually
moved without breaking the other cases.)

---

## 12. Threats to validity / known limitations

Naming the weaknesses honestly is part of the method:

- **Judge noise.** LLM-as-judge is not a perfect oracle; §9 bounds how far to trust
  it, but doesn't eliminate the noise. Deterministic checks are preferred wherever a
  question has a checkable fact.
- **Faithfulness is text-aware, but only over *retrieved* chunks.** The judge now sees
  chunk text, so it does real claim-vs-text grounding. But it can only vouch for what
  was retrieved — an answer can be perfectly faithful to a retrieved chunk that was
  itself the *wrong* entry. That's why faithfulness is paired with a retrieval check:
  faithful + retrieval-miss still means a bad answer.
- **Data date-skew is real.** Each entry carries two dates — a metadata date and the
  date in its title — and they routinely differ by a day or two (the title is the day
  written *about*; the metadata is when it was logged). The strict faithfulness judge
  will flag an answer that cites one when the source line shows the other. Calibration
  labels (and answers generally) should avoid hinging on that ambiguous distinction.
- **Small golden set.** ~18 cases. Good coverage-by-failure-mode beats raw count, but
  it's still a sample; a passing baseline is evidence, not proof.
- **Variance vs. cost.** More runs give tighter variance estimates but multiply API
  calls against a free-tier quota, so routine runs use `N=1` and accept the noise.
- **Single grader.** One judge model grades everything; a second independent grader
  (or a human spot-check) would catch systematic judge bias the calibration set
  misses.

---

## 13. Roadmap

- **Fix + re-measure the stress hallucination** (§11): confirm the hardened grounding
  prompt flips faithfulness fail → pass with no regressions elsewhere.
- **Richer faithfulness**: feed chunk text (not just titles) to the faithfulness
  judge for true claim-level entailment.
- **Grow the golden set** by failure taxonomy, not raw count — cover each known
  failure mode with a case rather than piling on redundant ones.
- **CI gate**: run the deterministic layers on every change and fail the build on a
  `pass -> fail` diff, turning the regression net into an automatic guard.
- **Build the `insight` capability** (retrospective summarization / per-day
  aggregation) and watch that tier climb from expected-fail toward pass.
