# Agentic journal retrieval.
#
# The model searches the journal, reviews the results, and can adjust its query
# when the first search is too narrow or does not answer the question. It returns
# an answer once it has enough context or reaches the search limit.
#
# Responses are not streamed because tool-call arguments must be accumulated
# before each search can run. Verbose mode prints each tool call and the final
# answer after the request completes.

import os
import sys
import json
import datetime
from dataclasses import dataclass, field

# Use UTF-8 so verbose output renders correctly in Windows terminals.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from query_constructor import JournalQuery
from chroma_search import run_chroma_hybrid_search, count_journal_entries
from period_analysis import (
    analyze_period,
    format_analysis,
    summarize_period,
    fetch_entries_in_range,
    cap_recent,
)
from llm_client import get_client, GEMINI_MODEL, create_completion

AGENT_MODEL = GEMINI_MODEL
# Hard cap on searches so a confused model can't loop forever.
MAX_SEARCHES = 4

# The tool's input schema mirrors JournalQuery (the structured plan from
# query_constructor.py) plus top_k. The model fills these in itself now — and can
# change them between calls, which is the whole point.
SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_journal",
        "description": (
            "Search the user's personal journal and return matching entry chunks, each "
            "with its source title and date. ALWAYS call this before answering. If the "
            "results are empty or don't actually address the question, call it again "
            "with adjusted parameters: widen the date range, drop or change a keyword "
            "(the user often uses nicknames or misspellings), or change the recency "
            "setting."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "search_text": {
                    "type": "string",
                    "description": "Conceptual core of what to find, stripped of date "
                    "phrases. E.g. 'hanging out with Alex'.",
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific proper nouns to keyword-match: people, "
                    "places, projects. Empty list if purely conceptual.",
                },
                "date_after": {
                    "type": "integer",
                    "description": "Inclusive lower date bound as a YYYYMMDD integer. "
                    "OMIT this field entirely if there's no lower bound - do not pass null. "
                    "'after October 9th 2025' -> 20251009. For 'lately'/'recently', set "
                    "this to ~60 days before today (today's date is in the system prompt) "
                    "and keep recency='none'.",
                },
                "date_before": {
                    "type": "integer",
                    "description": "Inclusive upper date bound as a YYYYMMDD integer. "
                    "OMIT this field entirely if there's no upper bound - do not pass null.",
                },
                "recency": {
                    "type": "string",
                    "enum": ["latest", "earliest", "none"],
                    "description": "Sort mode. 'latest' sorts purely by date (newest "
                    "first) and IGNORES relevance — use ONLY for 'when was the last "
                    "time' questions. 'earliest' is the same for 'when did I first'. "
                    "'none' ranks by relevance — use it for everything else, INCLUDING "
                    "'lately/recently' questions (pair those with date_after).",
                },
                "top_k": {
                    "type": "integer",
                    "description": "How many chunks to return. Use 5 unless you need more.",
                },
            },
            "required": ["search_text", "keywords", "recency", "top_k"],
        },
    },
}

# Second tool: deterministic counting. The model picks this for "how many / how
# often" questions, where a search would only tally a capped sample.
COUNT_TOOL = {
    "type": "function",
    "function": {
        "name": "count_entries",
        "description": (
            "Return the EXACT number of journal entries matching keywords and/or a date "
            "range, plus the list of matching entries (date + title). Use this for "
            "'how many times', 'how often', 'how many days' questions — it counts the "
            "complete set, not a sample. For describing or finding content, use "
            "search_journal instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Words an entry must contain to count (e.g. ['gym']). "
                    "Case-insensitive. Empty list counts every entry in the date range.",
                },
                "date_after": {
                    "type": "integer",
                    "description": "Inclusive lower date bound as YYYYMMDD. OMIT this "
                    "field entirely if there's no lower bound - do not pass null.",
                },
                "date_before": {
                    "type": "integer",
                    "description": "Inclusive upper date bound as YYYYMMDD. OMIT this "
                    "field entirely if there's no upper bound - do not pass null.",
                },
            },
            "required": ["keywords"],
        },
    },
}

# Third tool (Phase 5): CLASSIFY-then-aggregate over a COMPLETE date range. For
# "what % of days" / "how many days did I [fuzzy criterion]" questions where no single
# keyword captures the criterion, so count_entries can't help. It labels every entry in
# the range and computes the ratio/count in Python.
ANALYZE_TOOL = {
    "type": "function",
    "function": {
        "name": "analyze_period",
        "description": (
            "Classify EVERY journal entry in a date range against a fuzzy yes/no criterion, "
            "then return exact counts and a percentage plus per-day labels. Use this for "
            "'what percentage of days...', 'how many days did I [do nothing / stay home / go "
            "outside / have a good day]...' — questions that need a judgment call on each day "
            "over the WHOLE range, not a keyword match. For keyword counts ('how many times "
            "did I go to the gym') use count_entries instead; for finding specific entries use "
            "search_journal."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date_after": {
                    "type": "integer",
                    "description": "Inclusive lower date bound as YYYYMMDD. OMIT if there's "
                    "no lower bound - do not pass null.",
                },
                "date_before": {
                    "type": "integer",
                    "description": "Inclusive upper date bound as YYYYMMDD. OMIT if there's "
                    "no upper bound - do not pass null.",
                },
                "dimension": {
                    "type": "string",
                    "description": "The yes/no classification criterion, stated as a clear "
                    "condition on a single day's entry. E.g. 'the writer went outside or had a "
                    "real outing (not just working or staying at home)'.",
                },
            },
            "required": ["dimension"],
        },
    },
}

# Fourth tool (Phase 5): SYNTHESIZE a grounded recap over a COMPLETE date range. For
# "tell me how [period] went" / "recap my..." questions that must read every entry in a
# window, not a top-k sample.
SUMMARIZE_TOOL = {
    "type": "function",
    "function": {
        "name": "summarize_period",
        "description": (
            "Read EVERY journal entry in a date range and return a grounded recap of that "
            "period. Use this for 'tell me about how [period] went', 'recap my [week/month/exam "
            "season]', 'rate my [period]' — questions that synthesize a whole stretch of time "
            "rather than looking up one entry. Returns 'nothing recorded' if the range is empty. "
            "ALWAYS bound it: pass date_after AND date_before around the specific period asked "
            "about (e.g. an exam season is a few weeks, not the whole journal) — leaving the "
            "range open pulls hundreds of entries and gets capped."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date_after": {
                    "type": "integer",
                    "description": "Inclusive lower date bound as YYYYMMDD. OMIT if there's "
                    "no lower bound - do not pass null.",
                },
                "date_before": {
                    "type": "integer",
                    "description": "Inclusive upper date bound as YYYYMMDD. OMIT if there's "
                    "no upper bound - do not pass null.",
                },
                "focus": {
                    "type": "string",
                    "description": "What the recap should center on, e.g. 'how final exam "
                    "season went' or 'overall productivity and mood'.",
                },
            },
            "required": ["focus"],
        },
    },
}

def build_system_prompt(today):
    """
    Build the agent system prompt with `today` (a datetime.date) injected.

    Taking the date as an argument instead of calling datetime.date.today()
    inline is what lets the eval harness FREEZE THE CLOCK: the golden set's known
    answers were written relative to a fixed date, so if 'today' drifted with the
    wall clock, "the last week" would silently point at a different span every run
    and the same question could pass one day and fail the next. Pinning it keeps
    the eval reproducible; production just passes the real date.
    """
    return (
        f"Today's date is {today.isoformat()}. Resolve relative dates "
        "(today, last week, recently, this year) against it.\n\n"
        "You are an expert personal-journal research assistant. You answer questions by "
        "searching the user's journal and synthesizing ONLY from what you retrieve.\n\n"
        "Pick the right tool:\n"
        "- count_entries for 'how many times / how often' questions answerable by a "
        "KEYWORD match (e.g. gym visits) — it gives an EXACT count; never eyeball a number.\n"
        "- analyze_period for 'what percentage of days' or 'how many days did I [fuzzy "
        "criterion like did-nothing / stayed-home / went-outside / had-a-good-day]' — it "
        "classifies EVERY day in the range and computes the ratio for you. Use this, not "
        "count_entries, when no single keyword captures the criterion.\n"
        "- summarize_period for 'tell me how [period] went', 'recap my...', 'rate my "
        "[week/month]' — it reads the WHOLE period and synthesizes a grounded recap.\n"
        "- search_journal for 'what / when / describe / why' point lookups.\n\n"
        "How to work:\n"
        "1. ALWAYS call a tool before answering.\n"
        "2. Read the returned chunks. If they are empty or don't actually address the "
        "question, search AGAIN with adjusted parameters — widen the date range, drop or "
        "change a keyword (the user may use nicknames or misspellings), or change the "
        "recency setting — before giving up.\n"
        "3. Once you have enough evidence, answer concisely.\n\n"
        "GROUNDING RULES (these override everything else):\n"
        "- Every concrete detail you state — names, places, activities, media titles, "
        "apps, errands, feelings — MUST appear verbatim in a retrieved chunk. If it is "
        "not in the chunks, you do NOT know it. Do not add plausible-sounding detail, "
        "do not fill gaps from general knowledge, do not smooth the story with invented "
        "specifics. A sparse, partial answer that is fully grounded beats a rich one "
        "that is partly made up.\n"
        "- If the retrieved chunks only partially answer the question, answer only the "
        "part they support and say plainly what the journal does not cover.\n"
        "- If, after searching, the chunks do not contain the answer, say clearly that "
        "you couldn't find it in the journal. Never invent an answer to seem helpful.\n"
        "- Cite the source title and date for facts you state. But when a tool hands back "
        "an ALREADY-SYNTHESIZED recap (summarize_period), cite the DATE RANGE it covers; "
        "never cite a tool name or today's date as if it were a journal source.\n"
        "- For 'most recent / last time' questions, the chunks are ordered newest-first, "
        "so the FIRST chunk is the most recent match."
    )


# Default prompt for the interactive CLI path uses the real wall-clock date.
SYSTEM_PROMPT = build_system_prompt(datetime.date.today())


def format_chunks(chunks):
    """Render retrieved chunks into the text block the model reads as a tool result."""
    if not chunks:
        return "No matching journal entries were found for those parameters."
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk["meta"]
        parts.append(
            f"[Chunk {i} | Source: {meta['source_title']} | Date: {meta['date_string']}]\n"
            f"{chunk['text']}"
        )
    return "\n\n".join(parts)


@dataclass
class AgentResult:
    """What one agent run produced. The eval harness reads tool_calls + sources to
    check WHY an answer was right/wrong, not just the answer text."""

    answer: str
    tool_calls: list = field(default_factory=list)   # [{"name", "input"}, ...]
    # search/analyze/summarize sources carry the entry "text" too, so the faithfulness
    # judge can ground the answer against what the model ACTUALLY read (not just titles+
    # dates). count-derived sources have no text. [{"title", "date", "text"?}, ...]
    sources: list = field(default_factory=list)


def _run_search(args, n, verbose):
    """Run one search_journal call. Returns (result_text, sources)."""
    if verbose:
        print(f"\n🔁 [Search {n}]: {args}")
    query = JournalQuery(
        search_text=args.get("search_text") or "",
        keywords=args.get("keywords") or [],
        date_after=args.get("date_after"),
        date_before=args.get("date_before"),
        recency=args.get("recency") or "none",
    )
    chunks = run_chroma_hybrid_search(query, top_k=args.get("top_k") or 5, verbose=verbose)
    sources = [
        {
            "title": c["meta"]["source_title"],
            "date": c["meta"]["date_string"],
            "text": c["text"],
        }
        for c in chunks
    ]
    return format_chunks(chunks), sources


def _run_count(args, n, verbose):
    """Run one count_entries call. Returns (result_text, sources)."""
    if verbose:
        print(f"\n🔢 [Count {n}]: {args}")
    result = count_journal_entries(
        keywords=args.get("keywords") or [],
        date_after=args.get("date_after"),
        date_before=args.get("date_before"),
        verbose=verbose,
    )
    lines = [f"Exact count: {result['count']} matching entries."]
    for e in result["entries"]:
        lines.append(f"- {e['date']} — {e['title']}")
    return "\n".join(lines), result["entries"]


def _run_analyze(args, n, verbose):
    """Run one analyze_period call. Returns (result_text, sources).

    Sources are the analyzed entries (date + title) so the harness can check
    completeness — that the analysis covered the entries it should have."""
    if verbose:
        print(f"\n📊 [Analyze {n}]: {args}")
    result = analyze_period(
        date_after=args.get("date_after"),
        date_before=args.get("date_before"),
        dimension=args.get("dimension") or "",
        verbose=verbose,
    )
    sources = [
        {"date": d["date"], "title": d["title"], "text": d.get("text")}
        for d in result["per_day"]
    ]
    return format_analysis(result), sources


def _run_summarize(args, n, verbose):
    """Run one summarize_period call. Returns (result_text, sources).

    The recap is produced inside the tool over the COMPLETE set; sources carry the
    entries that fed it (date + title) for grounding/completeness checks."""
    if verbose:
        print(f"\n📝 [Summarize {n}]: {args}")
    entries = fetch_entries_in_range(args.get("date_after"), args.get("date_before"), verbose=verbose)
    recap = summarize_period(
        date_after=args.get("date_after"),
        date_before=args.get("date_before"),
        focus=args.get("focus") or "",
        entries=entries,
        verbose=verbose,
    )
    # sources must describe the SAME set the recap covered (summarize_period caps a
    # too-wide window to the most-recent N), so cap here identically.
    used, _ = cap_recent(entries)
    sources = [{"date": e["date"], "title": e["title"], "text": e["text"]} for e in used]
    return recap, sources


def answer_journal(question, verbose=True, today=None):
    """
    Run the agentic loop for one question. Returns an AgentResult.

    verbose=True (CLI): stream the answer + print tool activity.
    verbose=False (eval harness): run silently, just collect the result.
    today: optional datetime.date to pin the agent's notion of "now" — the eval
    harness passes a fixed date so relative-time questions stay reproducible; the
    CLI leaves it None to use the real wall-clock date.
    Stateless by design — one question in, one answer out. Multi-turn follow-ups
    are resolved upstream by router.rewrite_query (see main.py).
    """
    system_prompt = SYSTEM_PROMPT if today is None else build_system_prompt(today)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    tool_runs = 0
    tool_calls = []
    sources = []
    client = None

    while True:
        if tool_runs >= MAX_SEARCHES:
            tool_choice = "none"      # budget spent — force an answer
        elif tool_runs == 0:
            tool_choice = "required"  # must use a tool, model picks which
        else:
            tool_choice = "auto"

        try:
            if client is None:
                client = get_client()
            response = create_completion(
                client,
                model=AGENT_MODEL,
                max_tokens=1500,
                messages=messages,
                tools=[SEARCH_TOOL, COUNT_TOOL, ANALYZE_TOOL, SUMMARIZE_TOOL],
                tool_choice=tool_choice,
            )
        except Exception as e:
            # create_completion already retried what it could (rate limits, malformed
            # tool calls) - if it still failed, don't take the whole caller down with
            # it (the eval harness runs 18+ of these back to back). Surface a clear,
            # honest technical-failure answer instead of a stack trace mid-batch.
            if verbose:
                print(f"\n⚠️ Request failed after retries: {e}")
            return AgentResult(
                answer=f"[technical error - could not complete this request: {e}]",
                tool_calls=tool_calls,
                sources=sources,
            )
        message = response.choices[0].message

        if message.tool_calls:
            # Round-trip the message exactly as the API returned it (not a hand-picked
            # subset of fields) - Gemini 3's function calling attaches a
            # `thought_signature` to each tool-call part that MUST be echoed back on
            # the next turn or it 400s ("missing a thought_signature"). Rebuilding the
            # dict from scratch silently dropped that field; model_dump() keeps it
            # since the SDK's models allow/preserve unknown extra fields.
            messages.append(message.model_dump(exclude_none=True))

            for tc in message.tool_calls:
                tool_runs += 1
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({"name": tc.function.name, "input": args})
                try:
                    if tc.function.name == "count_entries":
                        result_text, found = _run_count(args, tool_runs, verbose)
                    elif tc.function.name == "analyze_period":
                        result_text, found = _run_analyze(args, tool_runs, verbose)
                    elif tc.function.name == "summarize_period":
                        result_text, found = _run_summarize(args, tool_runs, verbose)
                    else:
                        result_text, found = _run_search(args, tool_runs, verbose)
                except Exception as e:
                    # A single tool handler blowing up (a bad DB read, a classify parse
                    # failure that slipped through, a rate-limited sub-call) must not take
                    # down the whole run — the eval batches many questions. Report the
                    # failure back to the model as the tool result and let it recover.
                    if verbose:
                        print(f"\n⚠️ Tool '{tc.function.name}' failed: {e}")
                    result_text = f"[tool error: {type(e).__name__}: {str(e)[:150]}]"
                    found = []
                sources.extend(found)
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result_text}
                )
            continue

        # no tool call (or forced answer) — message.content is the final answer.
        assistant_text = message.content or ""
        if verbose:
            print(assistant_text)
        return AgentResult(answer=assistant_text, tool_calls=tool_calls, sources=sources)


if __name__ == "__main__":
    if "GEMINI_API_KEY" not in os.environ:
        print("❌ Set GEMINI_API_KEY (in .env) to run the agent.")
        sys.exit(1)

    tests = [
        "When was the last time I hung out with Alex?",
        "How many times did I go to the gym in May 2026?",  # should route to count_entries
        "What did I do with Alex in October 2023?",  # likely needs a 2nd, widened search
    ]
    for q in tests:
        print("\n" + "#" * 72)
        print("QUESTION:", q)
        print("#" * 72)
        result = answer_journal(q)
        print(f"\n[tools used: {[t['name'] for t in result.tool_calls]}]")
