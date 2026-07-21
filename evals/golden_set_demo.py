# DEMO GOLDEN SET — the public, synthetic twin of golden_set.py.
#
# Runs against the committed demo corpus (demo/ — see demo/generate_demo_corpus.py)
# when JOURNAL_DEMO=1. Every known answer here is true BY CONSTRUCTION: the corpus
# generator asserts these exact facts before writing a single file, so this set is
# fully reproducible by anyone who clones the repo — no private data, no trust
# required. Same check fields and tiers as golden_set.py (see that file's header).
#
# The cases deliberately mirror the real set's failure taxonomy, one per shape:
# recency (last/first), bounded range, exact counts, honest failure on a trap,
# misspelling recovery, conceptual+judge, empty-window decline, completeness,
# and a summarize recap.

EVAL_DATE = "2026-06-30"  # corpus ends 2026-06-05 -> "the last week" is empty

GOLDEN = [
    # ---------------- CURRENT TIER ----------------
    {
        "tier": "current",
        "q": "When was the last time I hung out with Sam?",
        "expect_tool": "search_journal",
        "source_date": "2026-06-05",
        "answer_contains": ["2026"],
    },
    {
        "tier": "current",
        "q": "When did I first hang out with Sam?",
        "expect_tool": "search_journal",
        "source_date": "2025-09-14",
        "answer_contains": ["2025"],
    },
    {
        "tier": "current",
        "q": "What did I do with Sam after March 1st, 2026?",
        # hiking 03-14, botanical gardens 05-16, lake day 06-05
        "expect_tool": "search_journal",
        "sources_after": "2026-03-01",
    },
    {
        "tier": "current",
        "q": "How many journal entries did I write in May 2026?",
        "expect_tool": "count_entries",
        "expect_count": 18,
    },
    {
        "tier": "current",
        "q": "How many times did I go to the gym in May 2026?",
        "expect_tool": "count_entries",
        "expect_count": 6,
    },
    {
        "tier": "current",
        "q": "How many pottery classes have I been to?",
        "expect_tool": "count_entries",
        "expect_count": 4,
    },
    {
        "tier": "current",
        # The trap: Iceland exists in the corpus ONLY as a documentary (2026-02-11).
        # Must decline the trip, not invent one from the mention.
        "q": "Tell me about my trip to Iceland.",
        "honest_fail": True,
    },
    {
        "tier": "current",
        # Misspelling recovery ("Mayya" does not contain the substring "Maya",
        # so retrieval must actually self-correct, and the assert can't pass by echo).
        "q": "What did I do with Mayya recently?",
        "answer_contains": ["Maya"],
    },
    {
        "tier": "current",
        "q": "How have I been coping with stress lately?",
        "expect_tool": "search_journal",
        "sources_any_after": "2026-04-30",
        "judge": (
            "A good answer identifies coping strategies actually recorded in "
            "recent entries — running to clear the head, journaling before bed, "
            "gym sessions, and social breaks (movie night with Maya) — and cites "
            "the entries or dates they come from. It must not invent strategies "
            "that never appear in the journal."
        ),
    },
    # ---------------- INSIGHT TIER ----------------
    {
        "tier": "insight",
        # No entries exist after 2026-06-05, so the week before EVAL_DATE is empty.
        "q": "Rate my productivity over the last week.",
        "honest_fail": True,
    },
    {
        "tier": "insight",
        "q": "For every day in May 2026, what percentage of days did I go to the gym?",
        # completeness: the aggregate tool must cover ALL 18 May entries
        "sources_count": 18,
        "judge": (
            "The answer must be grounded in the 18 journaled days of May 2026: "
            "6 of them were gym days (5/2, 5/6, 5/11, 5/15, 5/22, 5/29), which is "
            "about 33%. A good answer reports roughly that percentage, is explicit "
            "that it can only speak to journaled days, and does not invent data "
            "for days with no entry."
        ),
    },
    {
        "tier": "insight",
        "q": "Tell me about how my midterm season went.",
        "judge": (
            "A good answer recaps the April 2026 midterm arc from the entries: "
            "stress building beforehand (practice exam trouble, rotational "
            "dynamics worries around April 19-21), the coping (study plan, a run), "
            "and the outcome (the April 22 physics midterm went well — the feared "
            "rotational dynamics problem was nailed). It must be grounded in "
            "those entries, not a generic story."
        ),
    },
]
