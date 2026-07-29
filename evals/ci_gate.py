# CI GATE — turns the eval harness into a build gate.
#
# The harness itself (evals/harness.py) reports a baseline diff but always exits 0:
# it's a measurement tool, not a gate. This wrapper runs the SAME harness, then
# compares against the committed baseline and sets the process exit code so CI can
# fail a pull request on a regression.
#
# GATE POLICY:
#   - HARD FAIL (exit 1) only on a clean  pass -> fail  on any layer. That is an
#     unambiguous regression: a case the baseline says works, that now doesn't.
#   - WARN (exit 0) on anything involving `flaky`, or a case missing from the
#     baseline. LLM output is stochastic; a single noisy run must not break a build.
#   - NO BASELINE YET (exit 0, warn): before baseline_demo.json is committed there is
#     nothing to diff, so the gate is inert — it still runs the harness for signal.
#   - UNMEASURED LAYERS (silent): a layer scored None in either the baseline or this
#     run wasn't measured, so it is skipped rather than diffed. The PR gate runs
#     without --judge by design, so the judge/faithfulness layers are None on every
#     PR; diffing them against a --judge baseline would emit noise on every build.
#
# Reuses harness internals directly so there is ZERO duplicated scoring/parsing logic.
#
# Usage (demo corpus is selected by JOURNAL_DEMO=1, exactly like the harness):
#   JOURNAL_DEMO=1 python -m evals.ci_gate                 # PR gate: deterministic layers
#   JOURNAL_DEMO=1 python -m evals.ci_gate --judge --runs 3  # nightly: full, variance-aware

import json
import sys

from evals import harness


def main(argv):
    judge_enabled = "--judge" in argv
    runs = harness._parse_runs(argv)

    results = harness.run(judge_enabled, runs)
    harness.report(results, runs)

    if not harness.BASELINE_PATH.exists():
        print(
            f"::warning::No {harness.BASELINE_PATH.name} committed yet — the gate is "
            f"inert (nothing to diff). Record one with "
            f"`JOURNAL_DEMO=1 python -m evals.harness --judge --save`."
        )
        return 0

    baseline = json.loads(harness.BASELINE_PATH.read_text())
    base = {r["q"]: r["rates"] for r in baseline["results"]}

    regressions = []
    warnings = []
    for r in results:
        old = base.get(r["q"])
        if old is None:
            warnings.append(f"case not in baseline (skipped): {r['q'][:60]}")
            continue
        for layer in harness.LAYERS:
            old_mark = harness.rate_mark(old.get(layer))
            new_mark = harness.rate_mark(r["rates"][layer])
            if old_mark == new_mark:
                continue
            # None == "layer not measured in this run", not a verdict. The PR gate runs
            # without --judge on purpose, so the judge/faithfulness layers are always
            # None here while the baseline (recorded with --judge) has real marks.
            # Comparing the two would warn on every PR forever. No measurement, no signal.
            if old_mark is None or new_mark is None:
                continue
            if old_mark == "pass" and new_mark == "fail":
                regressions.append(f"{r['q'][:50]} [{layer}]: pass -> fail")
            else:
                # flaky in either direction, or fail->pass (an improvement) — informational
                warnings.append(f"{r['q'][:50]} [{layer}]: {old_mark} -> {new_mark}")

    for w in warnings:
        print(f"::warning::{w}")

    if regressions:
        print("\n::error::Eval gate FAILED — clean pass -> fail regression(s) vs baseline:")
        for x in regressions:
            print(f"  {x}")
        print(
            "\nIf this behavior change is intentional, re-record the baseline "
            "(`JOURNAL_DEMO=1 python -m evals.harness --judge --save`) in the same PR."
        )
        return 1

    print("\nEval gate PASSED — no pass -> fail regressions vs baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
