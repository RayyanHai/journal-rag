# PHASE 5 — RETROSPECTIVE AGGREGATION over a COMPLETE date range
#
# search_journal returns a top-k RELEVANT SAMPLE. That's the right primitive for
# "what / when" point lookups, but it structurally cannot answer:
#   - "what % of days this summer did I go outside?"   (needs EVERY day, then a ratio)
#   - "how many days last month did I do nothing?"     (needs EVERY day, then a count)
#   - "tell me how exam season went"                   (needs EVERY entry, synthesized)
# because it never sees the whole set. These are DATASET operations, not searches.
#
# This module adds that missing primitive — fetch the COMPLETE set of entries in a
# date range (no top_k) — and builds two capabilities on it, in two shapes:
#
#   analyze_period   (map -> reduce)  classify each entry on a fuzzy dimension, then
#                                     count/ratio the labels IN PYTHON (never let the
#                                     model do the arithmetic — the count_entries lesson).
#   summarize_period (reduce)         synthesize a grounded recap over the whole range.
#
# QUOTA is the overriding constraint for this whole project (see llm_client.py's
# provider-migration saga). So the classify step is BATCHED (~a dozen entries per LLM
# call, not one call per entry), and the reduce step is pure Python.

from pydantic import BaseModel

import chromadb

from chroma_search import _build_date_where
from llm_client import get_client, parse_structured, create_completion, GEMINI_MODEL

from config import CHROMA_PATH, COLLECTION_NAME as COLLECTION

# entries per LLM call. Classifying one-at-a-time over a ~32-entry month would be 32
# calls and torch the free tier; a dozen per call cuts a month to ~3 calls.
CLASSIFY_BATCH_SIZE = 12
# a summarize window that fits in this many entries is done in a single synthesis
# call; wider windows fall back to hierarchical (map-reduce) summarization.
SUMMARIZE_BATCH_SIZE = 15
# hard cap on entries a single summarize will process. Without this, a model that
# picks too wide a window (we saw it grab 800+ entries for "final exam season") fans
# out into ~50 hierarchical calls — a quota bomb. Cap to the most-recent N and tell
# the model to narrow the window. At batch size 15 this is <=4 batches + 1 fuse.
SUMMARIZE_MAX_ENTRIES = 60
# guard rail: refuse to analyze an unbounded/enormous range rather than fan out into
# dozens of LLM calls and blow the quota. The insight-tier windows are all well under.
MAX_ENTRIES = 120
# entry text is truncated to this many chars per entry when fed to the classifier,
# to keep batch prompts within token budget (full text is used for summarize).
CLASSIFY_TEXT_CAP = 1200

MAP_MODEL = GEMINI_MODEL      # the classify/summarize workhorse


def _batched(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def fetch_entries_in_range(date_after=None, date_before=None, verbose=True):
    """
    Return the COMPLETE set of distinct journal entries in [date_after, date_before],
    each with its FULL reconstructed text (chunks re-joined in order).

    This is count_journal_entries' complete-fetch + distinct-parent collapse, extended
    to also rebuild each entry's full body: chunk ids are "{page_id}_chunk_{n}", so we
    group by page_id and concatenate chunks in n order. Returns
    [{"date", "date_int", "title", "text"}, ...] sorted chronologically.
    """
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_collection(name=COLLECTION)

    where = _build_date_where(date_after, date_before)
    if where and verbose:
        print(f"Fetching complete entry set with date filter: {where}")

    data = collection.get(where=where, include=["documents", "metadatas"])

    entries = {}  # parent_id -> {date, date_int, title, chunks: {n: text}}
    for chunk_id, doc, meta in zip(data["ids"], data["documents"], data["metadatas"]):
        parent_id, _, tail = chunk_id.partition("_chunk_")
        try:
            n = int(tail)
        except ValueError:
            n = 0
        e = entries.setdefault(
            parent_id,
            {
                "date": meta.get("date_string", "unknown"),
                "date_int": meta.get("date_int", 0),
                "title": meta.get("source_title", "Untitled"),
                "chunks": {},
            },
        )
        e["chunks"][n] = doc

    result = []
    for e in entries.values():
        text = " ".join(e["chunks"][k] for k in sorted(e["chunks"]))
        result.append(
            {"date": e["date"], "date_int": e["date_int"], "title": e["title"], "text": text}
        )
    result.sort(key=lambda x: (x["date_int"], x["date"]))
    return result


# ----------------------------- analyze (map -> reduce) -----------------------------

class _DayLabel(BaseModel):
    id: int      # index of the entry within the batch (avoids date-collision ambiguity)
    label: bool
    why: str


class _BatchLabels(BaseModel):
    labels: list[_DayLabel]


def _classify_batch(batch, dimension):
    """Label one batch of entries against `dimension`. Returns a list aligned 1:1 with
    `batch` (every entry gets a label; a model that omits an id defaults to False so the
    deterministic total below always equals the true entry count)."""
    lines = []
    for i, e in enumerate(batch):
        text = e["text"][:CLASSIFY_TEXT_CAP]
        lines.append(f"[{i}] date={e['date']} | title={e['title']}\n{text}")
    user = (
        f"CLASSIFICATION CRITERION:\n{dimension}\n\n"
        "For EACH entry below, decide label=true if the criterion clearly holds based "
        "ONLY on that entry's text, otherwise false. Judge strictly from what the text "
        "says — do not invent or assume. Give a short 'why' (<=12 words) grounded in the "
        "entry. Return one object for EVERY id.\n\n"
        "ENTRIES:\n" + "\n\n".join(lines)
    )
    system = (
        "You are a precise labeler of personal-journal entries against a single yes/no "
        "criterion. You return structured labels only, grounded strictly in each entry's text."
    )
    try:
        result = parse_structured(_BatchLabels, system, user, model=MAP_MODEL, max_tokens=2000)
        by_id = {lbl.id: lbl for lbl in result.labels}
    except Exception as e:
        # A bad/empty/rate-limited classify response must NOT crash the whole analysis
        # (and, upstream, the whole eval run). Degrade: leave this batch unlabeled so
        # the deterministic total still equals the true entry count; the miss is visible
        # in the per-day 'why' rather than hidden behind a stack trace.
        print(f"  [classify batch failed: {type(e).__name__}: {str(e)[:100]}]")
        by_id = {}

    out = []
    for i, e in enumerate(batch):
        lbl = by_id.get(i)
        out.append(
            {
                "date": e["date"],
                "title": e["title"],
                # carry the entry text so the agent's source list can feed the
                # faithfulness judge the actual text it grounded against (same reason
                # search sources carry text) — not just titles+dates.
                "text": e["text"],
                "label": bool(lbl.label) if lbl else False,
                "why": lbl.why if lbl else "(classifier returned no label; defaulted to false)",
            }
        )
    return out


def analyze_period(date_after, date_before, dimension, verbose=True):
    """
    AGGREGATE shape: classify every entry in the range on `dimension`, then count/ratio
    the labels in Python. Returns:
      {"total", "matched", "percentage", "per_day": [{date,title,label,why}], "dimension",
       "truncated": bool}
    The reduce (matched / percentage) is deterministic Python — the model only ever
    produces the per-entry booleans, never the final number.
    """
    entries = fetch_entries_in_range(date_after, date_before, verbose=verbose)
    truncated = len(entries) > MAX_ENTRIES
    if truncated:
        entries = entries[:MAX_ENTRIES]

    if not entries:
        return {"total": 0, "matched": 0, "percentage": 0.0, "per_day": [],
                "dimension": dimension, "truncated": False}

    per_day = []
    for batch in _batched(entries, CLASSIFY_BATCH_SIZE):
        if verbose:
            print(f"  classifying batch of {len(batch)} entries...")
        per_day.extend(_classify_batch(batch, dimension))

    total = len(per_day)
    matched = sum(1 for d in per_day if d["label"])
    percentage = round(100 * matched / total, 1) if total else 0.0
    return {
        "total": total,
        "matched": matched,
        "percentage": percentage,
        "per_day": per_day,
        "dimension": dimension,
        "truncated": truncated,
    }


def format_analysis(result):
    """Render an analyze_period result into the text block the agent reads as a tool
    result — headline stats first (already computed, so the model doesn't recompute),
    then the per-day evidence so the narration stays grounded."""
    if result["total"] == 0:
        return ("No journal entries exist in that date range, so there is nothing to "
                "analyze. Say plainly that nothing is recorded for this period.")
    per_day = result["per_day"]
    span = f"{per_day[0]['date']} to {per_day[-1]['date']}"
    matched_dates = [d["date"] for d in per_day if d["label"]]
    lines = [
        f"Classification criterion: {result['dimension']}",
        f"Journaled days analyzed (complete set that HAS entries): {result['total']} "
        f"(spanning {span})",
        f"Matched the criterion: {result['matched']}",
        f"Percentage (of journaled days): {result['percentage']}%",
    ]
    if result.get("truncated"):
        lines.append(f"(NOTE: range exceeded {MAX_ENTRIES} entries; analysis capped at the "
                     f"first {MAX_ENTRIES}. Tell the user the range was too large to cover fully.)")
    lines.append("\nPer-day labels:")
    for d in per_day:
        mark = "YES" if d["label"] else "no "
        lines.append(f"  [{mark}] {d['date']} — {d['title']}: {d['why']}")
    lines.append(
        "\nHOW TO ANSWER (grounded):\n"
        f"- State the count and percentage above (already computed — do NOT recompute).\n"
        f"- LIST the specific matching dates: {', '.join(matched_dates) if matched_dates else '(none)'}.\n"
        "- Say what definition/criterion was used.\n"
        f"- This covers only the {result['total']} days that HAVE journal entries (spanning "
        f"{span}); do NOT imply every calendar day in the asked period was classified, and do "
        "NOT invent dates outside this span."
    )
    return "\n".join(lines)


# ----------------------------- summarize (reduce) -----------------------------

def cap_recent(entries):
    """Bound a summarize window to the most-recent SUMMARIZE_MAX_ENTRIES entries.
    Returns (capped_entries, was_capped). Shared by the tool and the agent's source
    list so both describe the SAME set of entries."""
    if len(entries) <= SUMMARIZE_MAX_ENTRIES:
        return entries, False
    return entries[-SUMMARIZE_MAX_ENTRIES:], True


def _synthesize(system, user, max_tokens=1200):
    client = get_client()
    response = create_completion(
        client,
        model=MAP_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return (response.choices[0].message.content or "").strip()


def _entries_block(entries):
    return "\n\n".join(f"[{e['date']} — {e['title']}]\n{e['text']}" for e in entries)


_SUMMARIZE_SYSTEM = (
    "You write a concise, grounded recap of a period of someone's personal journal. "
    "Use ONLY what the entries state — no invented events, feelings, or specifics. "
    "Cite dates for the beats you mention. If the entries are thin, say so rather than "
    "padding. A short faithful recap beats a rich embellished one."
)


def summarize_period(date_after, date_before, focus, entries=None, verbose=True):
    """
    REDUCE shape: synthesize a grounded recap over the COMPLETE set of entries in range.
    Single synthesis pass when the window fits; hierarchical (summarize batches, then
    summarize the summaries) as the safety valve for windows too wide for one context.
    Empty range returns an explicit 'nothing recorded' — never an invented recap.

    `entries` may be passed in pre-fetched (the agent handler already needs them for
    source tracking) to avoid a redundant Chroma read; None means fetch here.
    """
    if entries is None:
        entries = fetch_entries_in_range(date_after, date_before, verbose=verbose)
    if not entries:
        return ("No journal entries are recorded in that period. There is nothing to "
                "summarize — say so plainly and do not invent a recap.")

    entries, was_capped = cap_recent(entries)
    note = ""
    if was_capped:
        note = (f"(NOTE: the requested range held more than {SUMMARIZE_MAX_ENTRIES} entries; "
                f"this recap covers only the {SUMMARIZE_MAX_ENTRIES} most recent of them. Tell "
                f"the user the window was broad and suggest narrowing it for a tighter recap.)\n\n")

    span = f"{entries[0]['date']} to {entries[-1]['date']}"

    if len(entries) <= SUMMARIZE_BATCH_SIZE:
        user = (f"FOCUS: {focus}\nPERIOD: {span} ({len(entries)} entries)\n\n"
                f"ENTRIES:\n{_entries_block(entries)}\n\n"
                "Write the grounded recap now.")
        return note + _synthesize(_SUMMARIZE_SYSTEM, user)

    # hierarchical: too many entries for one context — summarize each batch, then fuse.
    partials = []
    for batch in _batched(entries, SUMMARIZE_BATCH_SIZE):
        if verbose:
            print(f"  summarizing batch of {len(batch)} entries...")
        bspan = f"{batch[0]['date']} to {batch[-1]['date']}"
        user = (f"FOCUS: {focus}\nSUB-PERIOD: {bspan}\n\n"
                f"ENTRIES:\n{_entries_block(batch)}\n\n"
                "Summarize just this sub-period, grounded in these entries, citing dates.")
        partials.append(_synthesize(_SUMMARIZE_SYSTEM, user))

    combined = "\n\n".join(f"[sub-summary {i + 1}] {p}" for i, p in enumerate(partials))
    user = (f"FOCUS: {focus}\nPERIOD: {span}\n\n"
            f"These are ordered sub-period summaries of the same journal stretch. Fuse them "
            f"into one coherent recap, preserving dates and not adding anything not present:\n\n"
            f"{combined}")
    return note + _synthesize(_SUMMARIZE_SYSTEM, user, max_tokens=1400)


if __name__ == "__main__":
    import os
    if "GEMINI_API_KEY" not in os.environ:
        raise SystemExit("Set GEMINI_API_KEY (in .env) to run period analysis.")

    # smoke test against May 2026 (a known-populated month, 32 entries)
    print("== analyze_period: 'did nothing / just stayed home', May 2026 ==")
    res = analyze_period(20260501, 20260531,
                         "the writer did nothing productive or just worked/stayed at home all day")
    print(format_analysis(res))
    print("\n== summarize_period: final exam season ==")
    print(summarize_period(20260420, 20260510, "how final exam season went"))
