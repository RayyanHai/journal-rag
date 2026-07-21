import os
import sys
from dotenv import load_dotenv
from router import rewrite_query
from agent import answer_journal

load_dotenv()

# bail early if the key isn't set, rather than failing on the first request
if "GEMINI_API_KEY" not in os.environ:
    print("Error: GEMINI_API_KEY environment variable not found.")
    print("Run: export GEMINI_API_KEY='your_gemini_api_key_here'")
    sys.exit(1)

def chat_loop():
    chat_history = []
    print("Journal RAG Engine Active (Gemini + Chroma DB + Temporal Retrieval).")
    print("Type 'exit' to quit.\n")

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() == 'exit':
            break
        if not user_input:
            continue

        # rewrite follow-ups into standalone questions (router.py, via Gemini),
        # so "what did we eat?" becomes something the retriever can actually search on
        if chat_history:
            search_query = rewrite_query(chat_history, user_input)
            print(f"[Rewriter Output]: {search_query}")
        else:
            search_query = user_input

        # agentic retrieval + answer: the model drives the search_journal / count_entries
        # tools, re-searching with adjusted filters until it can answer
        print("Assistant is researching...")
        result = answer_journal(search_query)

        # save turn so the next loop has history to work with (for the rewriter)
        chat_history.append({"role": "user", "content": user_input})
        chat_history.append({"role": "assistant", "content": result.answer})

if __name__ == "__main__":
    chat_loop()
