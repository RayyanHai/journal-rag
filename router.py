# rewrites a follow-up question into a standalone query using chat history.
# needed because users ask follow-ups with pronouns/shorthand ("what did we eat?")
# that don't carry enough context on their own for retrieval.
#
# the agent itself is stateless (one question in / one answer out), so THIS is
# where conversational memory lives: we hand the model the recent history and ask
# it to fold the context into a self-contained question. Was local Llama3, then
# Claude Haiku, then o4-mini/GitHub Models, then Llama 3.3 70B/Groq; now Gemini.

import datetime

from llm_client import get_client, GEMINI_MODEL, DEFAULT_MAX_TOKENS, create_completion

REWRITER_MODEL = GEMINI_MODEL
_client = get_client()


def build_rewriter_prompt(today):
    """Rewriter instructions, with `today` injected.

    Two failure modes this guards against, both seen in the web app:
    1. Over-eager relative-date resolution. The rewriter used to turn "what did I do
       last week" into an INVENTED absolute date (e.g. "the week of May 6-12, 2024"),
       because it had no idea what "today" was. Relative phrases must pass through
       untouched — the agent is grounded in today's date and resolves them correctly.
    2. Losing self-contained questions. A question that doesn't reference the history
       must be returned verbatim, not "helpfully" reworded.
    """
    return (
        "You rewrite a follow-up question into a fully self-contained question using the "
        "chat history, so it can be answered without seeing that history. Resolve ONLY "
        "pronouns and back-references (we, that, there, then, it, him/her) into the "
        "explicit people, places, and dates they point to IN THE HISTORY. "
        "Example: history mentions hanging out with Alex on December 13th 2025, new "
        "question 'What did we eat?' -> 'What did I eat with Alex on December 13th, 2025?'.\n\n"
        f"Today's date is {today.isoformat()}. CRITICAL: do NOT convert relative time "
        "expressions (last week, last month, recently, yesterday, this year, lately, in "
        "May) into absolute calendar dates yourself — leave them EXACTLY as the user wrote "
        "them. A later stage resolves them. Only write an explicit date when that date "
        "literally appears in the chat history.\n\n"
        "If the new question is already self-contained, return it UNCHANGED. "
        "Output ONLY the rewritten question — no explanation, no quotes."
    )


# Built once at import (like agent.SYSTEM_PROMPT). rewrite_query can override per-call.
SYSTEM_PROMPT = build_rewriter_prompt(datetime.date.today())


def rewrite_query(chat_history, new_question):
    """
    Take past chat history + a follow-up question, return a standalone question.
    """
    formatted_history = ""
    for turn in chat_history:
        formatted_history += f"{turn['role'].upper()}: {turn['content']}\n"

    user_prompt = (
        f"Chat History:\n{formatted_history}\nNew Question: {new_question}\n"
        "Standalone question:"
    )

    try:
        response = create_completion(
            _client,
            model=REWRITER_MODEL,
            max_tokens=DEFAULT_MAX_TOKENS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception as e:
        # don't let a rewrite failure break the chat loop - search on the raw
        # follow-up rather than crashing (worse retrieval, but no crash)
        print(f"Query rewrite failed ({e}); using the question as-is.")
        return new_question
    content = response.choices[0].message.content
    return content.strip() if content else new_question

if __name__ == "__main__":

    mock_history = [
        {"role": "user", "content": "When did me and alex last hang?"},
        {"role": "assistant", "content": "You hung out with Alex on December 13th, 2025 at the PCL library."}
    ]
    follow_up = "What did we eat?"

    print("Testing query rewriter...")
    output = rewrite_query(mock_history, follow_up)
    print(f"Original: '{follow_up}'")
    print(f"Rewritten: '{output}'")
