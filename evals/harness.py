# EVAL HARNESS
#
# Runs every question in the golden set through the SAME entry point the app uses
# (agent.answer_journal, quiet mode) and scores the AgentResult on five named layers.
# The layers deliberately mirror the standard RAG-evaluation vocabulary so the
# scoreboard is legible to anyone who's read the literature (e.g. RAGAS):
#
#   routing       - did it pick the right tool?                    (result.tool_calls)
#   retrieval     - did the right entry surface? ("hit@k")          (result.sources)
#   answer        - deterministic answer correctness (dates/counts/declines) (result.answer)
#   faithfulness  - is every claim grounded in the retrieved sources? (LLM judge, opt-in)
#   judge         - does the free-text answer satisfy the rubric?    (LLM judge, opt-in)
#
# WHY SPLIT retrieval / faithfulness / judge?
# A bad answer is one of several distinct bugs with distinct fixes, and you can't
# tell which without measuring them apart:
#   - retrieval failed  -> the right chunk never got pulled  (fix: chunking/search/filters)
#   - faithfulness failed -> right chunks pulled, model invented anyway (fix: prompt/model)
#   - judge failed but faithfulness passed -> grounded but incomplete/off-rubric
# Reporting per tier makes the baseline double as a roadmap (CURRENT = regression
# net, INSIGHT = the not-built-yet target we watch go fail -> pass).
#
# REPRODUCIBILITY: the golden set's relative-time answers ("last week") are written
# against a FIXED date (golden_set.EVAL_DATE), passed into answer_journal(today=...)
# so a run's meaning doesn't drift with the wall clock.
#
# VARIANCE: LLM output is stochastic, so a single run is a noisy sample. --runs N
# runs each case N times and reports a pass RATE per layer; a layer that isn't
# unanimous across runs is flagged "flaky" rather than hidden behind one ✓/✗.
#
# Usage:
#   python -m evals.harness                    # deterministic layers only, 1 run
#   python -m evals.harness --judge            # also run the faithfulness + rubric judges
#   python -m evals.harness --judge --runs 3   # 3 runs/case, report variance
#   python -m evals.harness --judge --save     # write the result as the new baseline

import sys
import json
import time
import datetime
from pathlib import Path

from pydantic import BaseModel

# JOURNAL_DEMO=1 flips the ENTIRE harness to the public synthetic corpus: the
# demo golden set here, and the demo ChromaDB index via config (imported by
# chroma_search / period_analysis). Demo runs get their own baseline file so a
# demo run can never clobber or diff against the private-corpus baseline.
from config import DEMO_MODE

if DEMO_MODE:
    from evals.golden_set_demo import GOLDEN, EVAL_DATE
else:
    from evals.golden_set import GOLDEN, EVAL_DATE

from agent import answer_journal
from llm_client import parse_structured, GEMINI_MODEL

JUDGE_MODEL = GEMINI_MODEL
BASELINE_PATH = Path(__file__).with_name(
    "baseline_demo.json" if DEMO_MODE else "baseline.json"
)
LAYERS = ["routing", "retrieval", "answer", "faithfulness", "judge"]
EVAL_DATE_OBJ = datetime.date.fromisoformat(EVAL_DATE)

# decline phrases that count as an honest "I couldn't find it". Only consulted on
# honest_fail cases (which SHOULD decline), so breadth is low-risk; narrowness is
# the real failure mode — "you have not taken a trip to Iceland" is a perfectly
# honest decline that the original list missed (same flake as the Japan case).
DECLINE_PHRASES = [
    "couldn't find", "could not find", "couldn't locate", "no entries", "no journal",
    "didn't find", "did not find", "don't have", "do not have", "no record",
    "not find any", "unable to find", "no mention", "nothing about", "wasn't able to find",
    "no relevant", "not able to find",
    "have not", "haven't", "has not", "hasn't",
    "never went", "never visited", "never took", "no trip",
]


class JudgeVerdict(BaseModel):
    passed: bool
    reason: str


# ----------------------------- deterministic scorers -----------------------------
# Each returns "pass" / "fail" / None (None = check not applicable to this case).

def score_routing(result, case):
    if "expect_tool" not in case:
        return None
    used = [t["name"] for t in result.tool_calls]
    return "pass" if case["expect_tool"] in used else "fail"


def score_retrieval(result, case):
    checks = []
    dates = [s["date"] for s in result.sources]

    if "source_date" in case:
        checks.append(case["source_date"] in dates)
    if "sources_after" in case:
        bound = case["sources_after"]
        checks.append(bool(dates) and all(d > bound for d in dates))
    if "sources_any_after" in case:
        bound = case["sources_any_after"]
        checks.append(any(d > bound for d in dates))
    if "sources_between" in case:
        lo, hi = case["sources_between"]
        checks.append(bool(dates) and all(lo <= d <= hi for d in dates))
    if "sources_count" in case:
        # COMPLETENESS (Phase 5): did an aggregate tool actually cover EVERY entry in
        # the range, not a truncated sample? Count distinct entries in result.sources
        # and require it to equal the known entry count for the window.
        distinct = {(s.get("date"), s.get("title"), s.get("text")) for s in result.sources}
        checks.append(len(distinct) == case["sources_count"])

    if not checks:
        return None
    return "pass" if all(checks) else "fail"


def score_answer(result, case):
    ans = result.answer.lower()
    checks = []

    if "answer_contains" in case:
        checks.append(all(sub.lower() in ans for sub in case["answer_contains"]))
    if "expect_count" in case:
        checks.append(str(case["expect_count"]) in ans)
    if "honest_fail" in case:
        checks.append(any(p in ans for p in DECLINE_PHRASES))

    if not checks:
        return None
    return "pass" if all(checks) else "fail"


# ----------------------------- LLM-judge scorers -----------------------------

def _sources_block(result):
    """Render sources for the judge, INCLUDING chunk text when present.

    Grounding must be judged against what the model actually read. An earlier
    version showed only titles+dates, which made the faithfulness judge flag every
    body-derived specific (a restaurant name, a show title) as invented — false
    hallucination alarms, because the judge never saw the text those came from. So
    search-derived sources now carry their chunk `text` (see agent.AgentResult).
    """
    if not result.sources:
        return "(none)"
    # dedup identical (date, title, text) so repeated searches don't bloat the prompt
    seen = set()
    lines = []
    for s in result.sources:
        key = (s.get("date"), s.get("title"), s.get("text"))
        if key in seen:
            continue
        seen.add(key)
        head = f"- {s.get('date')} {s.get('title')}"
        if s.get("text"):
            head += f"\n    {s['text']}"
        lines.append(head)
    return "\n".join(lines)


def score_faithfulness(result, case, enabled):
    """
    GROUNDING metric, separate from rubric correctness: is every concrete claim in
    the answer supported by the retrieved sources? Catches hallucination even when
    the answer 'sounds' right. Runs for any free-text (judge) case. The sources block
    now includes chunk TEXT, so this is genuine claim-vs-text grounding, not a
    titles-only guess.
    """
    if "judge" not in case:
        return None, None
    if not enabled:
        return None, "skipped (run with --judge)"

    prompt = (
        f"QUESTION:\n{case['q']}\n\n"
        f"RETRIEVED SOURCE ENTRIES (date, title, and the entry text — all the system "
        f"had to work with):\n{_sources_block(result)}\n\n"
        f"SYSTEM ANSWER:\n{result.answer}\n\n"
        "Judge FAITHFULNESS only (not completeness): is every concrete claim in the "
        "answer — names, places, activities, media, dates — supported by the source "
        "entry text above? A claim counts as supported if it appears in or clearly "
        "paraphrases the entry text; do not penalize wording differences. If the answer "
        "introduces specifics that appear nowhere in the source text, that is unfaithful "
        "and fails. An honest 'I couldn't find it' with no invented detail is faithful "
        "and passes. On DATES: each source shows an authoritative leading metadata date AND "
        "a title that may embed its own informally-written date; the two can differ by a day "
        "or two. Treat the metadata date as ground truth. If the answer's date matches a "
        "source's metadata date it is FAITHFUL, even when that source's title embeds a "
        "slightly different date — do NOT flag that skew as unfaithful (an invented date that "
        "matches neither the metadata date nor the title still fails). Give a one-sentence reason."
    )
    return _run_judge(prompt)


def score_judge(result, case, enabled):
    """RUBRIC CORRECTNESS metric: does the answer actually satisfy the case's rubric
    (is it right and complete)? Faithfulness is scored separately above."""
    if "judge" not in case:
        return None, None
    if not enabled:
        return None, "skipped (run with --judge)"

    prompt = (
        f"QUESTION:\n{case['q']}\n\n"
        f"GRADING RUBRIC:\n{case['judge']}\n\n"
        f"RETRIEVED SOURCES (what the system had to work with):\n{_sources_block(result)}\n\n"
        f"SYSTEM ANSWER:\n{result.answer}\n\n"
        "Does the answer satisfy the rubric (correctness and completeness)? "
        "Give a brief one-sentence reason."
    )
    return _run_judge(prompt)


def _run_judge(prompt):
    try:
        verdict = parse_structured(
            JudgeVerdict,
            "You are a strict evaluator. Grade the answer against the instruction.",
            prompt,
            model=JUDGE_MODEL,
            max_tokens=600,
        )
        return ("pass" if verdict.passed else "fail"), verdict.reason
    except Exception as e:
        # A flaky judge call shouldn't crash the whole run — flag it and move on.
        return "fail", f"JUDGE ERROR: {type(e).__name__}: {str(e)[:120]}"


def score_all(result, case, judge_enabled):
    """Score one AgentResult on every layer. Returns (marks, notes)."""
    faith_mark, faith_reason = score_faithfulness(result, case, judge_enabled)
    judge_mark, judge_reason = score_judge(result, case, judge_enabled)
    marks = {
        "routing": score_routing(result, case),
        "retrieval": score_retrieval(result, case),
        "answer": score_answer(result, case),
        "faithfulness": faith_mark,
        "judge": judge_mark,
    }
    notes = {"faithfulness": faith_reason, "judge": judge_reason}
    return marks, notes


# ----------------------------- runner -----------------------------

def _aggregate(marks_per_run):
    """Collapse N per-run mark dicts into a per-layer {"passed", "of"} rate (or None
    when the layer never applied). Applicability is stable per case, so 'of' is the
    number of runs the layer was scored in."""
    rates = {}
    for layer in LAYERS:
        applicable = [m[layer] for m in marks_per_run if m[layer] is not None]
        if not applicable:
            rates[layer] = None
        else:
            rates[layer] = {"passed": sum(1 for x in applicable if x == "pass"), "of": len(applicable)}
    return rates


def run(judge_enabled, runs, delay=3.0, only=None, tier=None):
    results = []
    first = True
    cases = GOLDEN
    if tier:
        cases = [c for c in cases if c["tier"] == tier]
    if only:
        cases = [c for c in cases if only.lower() in c["q"].lower()]
    if tier or only:
        sel = " ".join(filter(None, [f"--tier {tier!r}" if tier else "", f"--filter {only!r}" if only else ""]))
        print(f"({sel}: {len(cases)} of {len(GOLDEN)} cases)\n")
    for i, case in enumerate(cases, start=1):
        marks_per_run = []
        notes = {}
        tools = []
        for r in range(1, runs + 1):
            tag = f" run {r}/{runs}" if runs > 1 else ""
            print(f"[{i}/{len(cases)}] ({case['tier']}){tag} {case['q'][:56]}...", flush=True)
            if not first:
                time.sleep(delay)  # spread requests out - free tiers are rate-limited
            first = False
            result = answer_journal(case["q"], verbose=False, today=EVAL_DATE_OBJ)
            marks, notes = score_all(result, case, judge_enabled)
            marks_per_run.append(marks)
            tools = [t["name"] for t in result.tool_calls]

        results.append(
            {
                "q": case["q"],
                "tier": case["tier"],
                "rates": _aggregate(marks_per_run),
                "tools": tools,
                "notes": notes,
            }
        )
    return results


# ----------------------------- interpreting rates -----------------------------

def rate_mark(rate):
    """Collapse a {"passed","of"} rate into a case-level verdict for a layer."""
    if rate is None:
        return None
    if rate["passed"] == rate["of"]:
        return "pass"
    if rate["passed"] == 0:
        return "fail"
    return "flaky"


def _cell(rate):
    if rate is None:
        return "·"
    if rate["of"] == 1:
        return {"pass": "✓", "fail": "✗", "flaky": "?"}[rate_mark(rate)]
    return f"{rate['passed']}/{rate['of']}"  # variance visible


# ----------------------------- reporting -----------------------------

def report(results, runs):
    width = 6 if runs == 1 else 8
    print("\n" + "=" * 96)
    header = f"{'TIER':<8}{'Q':<40}" + "".join(f"{lyr[:5]:>{width}}" for lyr in LAYERS)
    print(header)
    print("-" * 96)
    for r in results:
        row = f"{r['tier']:<8}{r['q'][:38]:<40}"
        row += "".join(f"{_cell(r['rates'][lyr]):>{width}}" for lyr in LAYERS)
        print(row)

    print("\n" + "=" * 96)
    print(f"SCOREBOARD (per tier — cases fully passing / applicable; flaky counted apart)")
    print("-" * 96)
    for tier in ("current", "insight"):
        tier_rows = [r for r in results if r["tier"] == tier]
        parts = []
        for layer in LAYERS:
            applicable = [r for r in tier_rows if r["rates"][layer] is not None]
            if not applicable:
                continue
            passed = sum(1 for r in applicable if rate_mark(r["rates"][layer]) == "pass")
            flaky = sum(1 for r in applicable if rate_mark(r["rates"][layer]) == "flaky")
            cell = f"{layer} {passed}/{len(applicable)}"
            if flaky:
                cell += f"(+{flaky}?)"
            parts.append(cell)
        tag = "regression net" if tier == "current" else "Phase 5 target"
        print(f"{tier.upper():<9}{'   '.join(parts) if parts else '(no scored layers)'}   <- {tag}")
    print("=" * 96)

    # surface judge/faithfulness reasons for anything that didn't cleanly pass
    notes_shown = False
    for r in results:
        for layer in ("faithfulness", "judge"):
            mark = rate_mark(r["rates"][layer])
            if mark in ("fail", "flaky") and r["notes"].get(layer):
                if not notes_shown:
                    print("\nJUDGE NOTES (non-passing free-text layers):")
                    notes_shown = True
                print(f"  [{layer}/{mark}] {r['q'][:56]}\n    -> {r['notes'][layer]}")


def diff_against_baseline(results):
    if not BASELINE_PATH.exists():
        print("\n(no baseline saved yet — run with --save to record one)")
        return
    base_payload = json.loads(BASELINE_PATH.read_text())
    base_rows = base_payload["results"]
    if base_rows and "rates" not in base_rows[0]:
        print("\n(baseline is in an older format — re-run with --save to record one "
              "in the current variance-aware format before diffing)")
        return
    base = {r["q"]: r["rates"] for r in base_rows}
    changes = []
    for r in results:
        old = base.get(r["q"])
        if old is None:
            continue
        for layer in LAYERS:
            old_mark = rate_mark(old.get(layer))
            new_mark = rate_mark(r["rates"][layer])
            if old_mark != new_mark:
                changes.append(f"  {r['q'][:46]} [{layer}]: {old_mark} -> {new_mark}")
    print("\nDIFF VS BASELINE:")
    print("\n".join(changes) if changes else "  (no changes)")


def save_baseline(results, judge_enabled, runs):
    payload = {
        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "eval_date": EVAL_DATE,
        "judge_enabled": judge_enabled,
        "runs_per_case": runs,
        "results": results,
    }
    BASELINE_PATH.write_text(json.dumps(payload, indent=2))
    print(f"\nSaved baseline -> {BASELINE_PATH.name}")


def _parse_valued(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def _parse_runs(argv):
    val = _parse_valued(argv, "--runs")
    if val is None:
        return 1
    try:
        return max(1, int(val))
    except ValueError:
        print("--runs needs an integer, e.g. --runs 3")
        sys.exit(2)


if __name__ == "__main__":
    judge_enabled = "--judge" in sys.argv
    save = "--save" in sys.argv
    runs = _parse_runs(sys.argv)
    only = _parse_valued(sys.argv, "--filter")  # run only cases whose question contains this
    tier = _parse_valued(sys.argv, "--tier")    # run only cases in this tier (current|insight)

    if save and (only or tier):
        # a filtered/tier run is a subset — saving it would clobber the full baseline
        print("Refusing --save with --filter/--tier: a partial run must not overwrite the full baseline.")
        sys.exit(2)

    results = run(judge_enabled, runs, only=only, tier=tier)
    report(results, runs)
    if not (only or tier):
        diff_against_baseline(results)
    if save:
        save_baseline(results, judge_enabled, runs)
