# Journal RAG

[![quality](https://github.com/RayyanHai/journal-rag/actions/workflows/quality.yml/badge.svg)](https://github.com/RayyanHai/journal-rag/actions/workflows/quality.yml)
[![eval harness](https://github.com/RayyanHai/journal-rag/actions/workflows/eval-harness.yml/badge.svg)](https://github.com/RayyanHai/journal-rag/actions/workflows/eval-harness.yml)

A personal RAG system built for years of Notion journal entries and thousands of chunks. 
I use it to ask things like:

- "when was the last time I hung out with ___"
- "what did I do last week?"
- "how many times did I go to the gym last month?"

And it answers from my entries with dates cited.

I created this project to gain hands-on experience with the fundamentals of how RAG works and to explore more complex parts. It started as a simple system, and as I encountered problems with answer generation, I implemented additional features and capabilities, such as temporally aware retrieval, agentic loops, deterministic counts, and eventually an eval-harness.

I built the ingestion, chunking, indexing, retrieval, agent workflow, evaluation harness, API, and chat UI end-to-end.

**Stack:** Python, FastAPI, React, Vite, ChromaDB, BM25, Gemini API, Notion API

<img width="1512" height="929" alt="Screenshot 2026-07-28 013253" src="https://github.com/user-attachments/assets/39b69f63-a79f-4ee3-b9a3-22c58d4b079c" />





## How to use it

I use the system through a simple chat interface frontend. I ask a question as I would to a chatbot, and the system retrieves relevant journal entries to generate an answer.

It can also answer follow-up questions. For example, after asking about a dinner with someone, I can ask, “what did we eat then?” The system uses the conversation history to rewrite that into a standalone search query before retrieving evidence.

For privacy, the public repository includes a fictional demo journal with the same pipeline and evaluation workflow, so anyone can run the project without access to my real entries.



## System design
<img width="1138" height="1533" alt="image" src="https://github.com/user-attachments/assets/e9aad2af-ff8a-4ca6-8869-0b0378d358bb" />


## My engineering focus

This was my exploration of the difference between an LLM answering a question and a system that can answer reliably from evidence. 

Key decisions I made:

- I stored a numeric `date_int` alongside each chunk so temporal questions can use deterministic range filters instead of hoping semantic search understands dates.
- I used hybrid retrieval: vector similarity for meaning, BM25 for exact terms, and reciprocal-rank fusion to combine the two.
- I separated counting into a deterministic tool. Search results are capped, so asking an LLM to count retrieved results would produce unreliable totals.
- I added a query-rewriting step for conversational follow-ups, allowing questions like “what did we eat then?” to be resolved using prior chat context.
- I designed the agent to re-search when results are weak or incomplete, while requiring answers to stay grounded in retrieved entries.
- I created a synthetic corpus and a golden-set evaluation harness so I could test retrieval and answer quality without committing sensitive personal data.


## How the project evolved

<p align="center">
  <img width="350" alt="Journal RAG evolution from basic retrieval to an evaluated full-stack application" src="https://github.com/user-attachments/assets/46eda57e-862d-4735-8438-cef6640d127b" />
</p>


## What I learned

This project helped reshape my original ideas about RAG systems. I learned that retrieval quality matters more than generation that merely looks good. A fluent answer can still be wrong or unsupported when retrieval fails.

I learned that you can't have a retrieval strategy for all types of questions. As I tested more questions I wanted to ask my system, I uncovered more flaws. Date lookup, broad reflection, and exact counting could not all be handled by the same prompt or search path.

I also learned when and when not to use LLMs. An LLM is good for interpreting language, choosing tools, and synthesizing evidence, but using deterministic code is better for filtering dates, counting, and enforcing constraints. 


## Evaluation

Alongside the demo corpus, I also built a golden-set eval harness to test the system without using my personal entries. This set covers the kinds of questions most likely to fail in a simple RAG implementation. 

Each test runs through the same `answer_journal` entry point used by the app and evaluates five separate layers:

- **Routing:** Did the agent choose the appropriate search or count tool?
- **Retrieval:** Did it return the required entries and dates?
- **Answer correctness:** Did the response contain the expected answer, count, or honest refusal?
- **Faithfulness:** Are the answer’s concrete claims supported by the retrieved sources?
- **Rubric quality:** For open-ended questions, does the answer fully address the expected evidence?

The cases cover temporal lookups, date ranges, exact counts, misspellings, conceptual reflection, follow-up behavior, incomplete-data handling, and trap questions where the correct answer is to decline rather than invent information.

To make the results reproducible, relative-time questions use a fixed evaluation date. The harness can run cases multiple times to surface LLM variance, and a GitHub Actions regression gate fails only when a previously passing check fails.


## Next improvements

If I continued this project, I would add retrieval observability (query traces and ranked-result inspection), stronger automated tests for temporal edge cases, entry-level deduplication across chunks, and a more formal evaluation set based on real but anonymized query patterns.



## Running locally

Use Python 3.11 or 3.12. Node.js 22+ is needed only for the web interface.

Clone the repository and install the Python dependencies:

```bash
git clone https://github.com/RayyanHai/journal-rag.git
cd journal-rag
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then add the credentials you need:

```env
GEMINI_API_KEY=your_key
NOTION_TOKEN=your_token
NOTION_DATABASE_ID=your_database_id
```

To run the demo:

```powershell
python demo/generate_demo_corpus.py
$env:JOURNAL_DEMO="1"
python chunk.py
python database.py
python main.py
```

The demo still needs a Gemini API key for query rewriting and answer generation.
It does not need Notion credentials and never reads `data/`.

To run with your own journal:

```bash
python ingest.py
python chunk.py
python database.py
python add_date_int.py
python main.py
```

For the web app:

```powershell
cd frontend
npm ci
npm run build
cd ..
$env:JOURNAL_DEMO="1"  # omit this line to use your private journal
python api.py
```

Open <http://127.0.0.1:8000>. For front-end development, run `npm run dev`
inside `frontend/` while `python api.py` runs in a second terminal.


## Privacy and security

- `.env`, the real `data/` corpus, generated indexes, and personal eval artifacts
  are excluded from Git.
- The committed `demo/` journal is fictional and is the only corpus used by public CI.
- The API binds to `127.0.0.1` and accepts browser requests only from its own origin
  or the local Vite development server.
- Do not bind the API to a public interface or deploy it without adding authentication,
  rate limits, and a deployment-specific origin policy.

See [SECURITY.md](SECURITY.md) for the supported deployment boundary and private
vulnerability-reporting process.
