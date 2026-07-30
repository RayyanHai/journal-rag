# Query construction turns a natural-language question into retrieval filters.
#
# A raw vector search does not understand time or hard constraints. Embedding an
# entire question can return a semantically close result outside the requested
# date range.
#
# This module creates structured retrieval instructions before searching:
#   - search_text: the conceptual part, for the dense/vector side
#   - keywords: proper nouns (people, places, projects) for the keyword side
#   - date_after / date_before: hard numeric (YYYYMMDD) range filters
#   - recency: did the user ask for the latest / earliest mention?
#
# The retriever enforces dates as filters and sorts chronologically when needed.

import datetime
from typing import Optional, List
from typing import Literal

from pydantic import BaseModel, Field

from llm_client import parse_structured, GEMINI_MODEL

# Query construction currently uses the shared model.
CONSTRUCTOR_MODEL = GEMINI_MODEL


class JournalQuery(BaseModel):
    """Structured form of the user's question, used to drive retrieval."""

    search_text: str = Field(
        description="The conceptual core of the question, stripped of date phrases. "
        "Used for semantic/vector matching. E.g. 'hanging out with Alex'."
    )
    keywords: List[str] = Field(
        default_factory=list,
        description="Specific proper nouns to keyword-match: people, places, "
        "projects, events. E.g. ['Alex']. Empty if the query is purely conceptual.",
    )
    date_after: Optional[int] = Field(
        default=None,
        description="Inclusive lower date bound as an integer YYYYMMDD, or null. "
        "'after October 9th 2025' -> 20251009.",
    )
    date_before: Optional[int] = Field(
        default=None,
        description="Inclusive upper date bound as an integer YYYYMMDD, or null.",
    )
    recency: Literal["latest", "earliest", "none"] = Field(
        default="none",
        description="Set 'latest' if the user wants the most recent match "
        "(last time, most recently, etc.), 'earliest' for the first/oldest, "
        "otherwise 'none'.",
    )


def construct_query(user_question: str, today: Optional[datetime.date] = None) -> JournalQuery:
    """Parse a natural-language journal question into structured retrieval params."""
    if today is None:
        today = datetime.date.today()

    system_prompt = (
        "You convert a personal-journal question into structured search parameters. "
        f"Today's date is {today.isoformat()}. Resolve all relative time references "
        "(today, yesterday, last week, recently, this year, a year ago) into concrete "
        "YYYYMMDD integer bounds relative to today.\n"
        "Rules:\n"
        "- 'after X' sets date_after; 'before X' sets date_before; 'in <month/year>' "
        "or 'on <date>' sets BOTH bounds to span that period.\n"
        "- 'recently'/'lately' means roughly the last ~60 days: set date_after accordingly.\n"
        "- Put people/places/projects in keywords; keep search_text conceptual.\n"
        "- If the user asks for the last/most recent/latest time, set recency='latest'. "
        "For the first/oldest time, set recency='earliest'.\n"
        "- If there is no date constraint, leave the date fields null."
    )

    try:
        return parse_structured(JournalQuery, system_prompt, user_question, model=CONSTRUCTOR_MODEL)
    except Exception as e:
        # don't let a parsing failure break retrieval, fall back to plain semantic search
        print(f"Query construction failed ({e}); falling back to raw search.")
        return JournalQuery(search_text=user_question)


if __name__ == "__main__":
    # manual test against the exact query that broke the old system
    import json

    tests = [
        "What else did I do with Alex after October 9th, 2025?",
        "When was the last time I hung out with Alex?",
        "How have I been coping with stress lately?",
        "What did I do on my birthday?",
    ]
    for q in tests:
        result = construct_query(q)
        print(f"\n{q}")
        print(json.dumps(result.model_dump(), indent=2))
