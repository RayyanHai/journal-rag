# send retrieved chunks to the llm and get a response back

import os
import json
import numpy as np
import ollama
from sentence_transformers import SentenceTransformer

def cosine_similarity(v1, v2):
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    return float(dot_product / (norm_v1 * norm_v2)) if norm_v1 and norm_v2 else 0.0

def retrieve_context(query_text, top_k=3):
    """Search the local vector store and return a formatted string of context chunks."""
    vector_store_path = "data/vector_store.json"
    if not os.path.exists(vector_store_path):
        raise FileNotFoundError("Vector store not found. Run embed.py first!")

    with open(vector_store_path, "r", encoding="utf-8") as f:
        vector_store = json.load(f)

    model = SentenceTransformer("all-MiniLM-L6-v2")
    query_vector = model.encode(query_text).tolist()

    scored_chunks = []
    for record in vector_store:
        score = cosine_similarity(query_vector, record["embedding"])
        scored_chunks.append({
            "text": record["text"],
            "score": score,
            "metadata": record["metadata"]
        })

    scored_chunks.sort(key=lambda x: x["score"], reverse=True)

    # format the top matches into a block of text for the LLM
    context_str = ""
    for rank, match in enumerate(scored_chunks[:top_k], start=1):
        meta = match["metadata"]
        context_str += f"\n--- CHUNK {rank} (Source: {meta['source_title']} | Date: {meta['date_string']}) ---\n"
        context_str += f"{match['text']}\n"

    return context_str

def ask_journal(query_text):
    # retrieve context from the local db
    print("Searching local vector database...")
    try:
        context = retrieve_context(query_text, top_k=3)
    except Exception as e:
        print(f"Retrieval failed: {e}")
        return

    # system prompt to keep the LLM grounded in the journal data
    system_prompt = (
        "You are a personal journal analysis assistant. Your job is to answer questions about the user's past "
        "based strictly on the provided journal entry chunks. "
        "Be empathetic, grounded, and concise. Always mention the specific dates of the entries you are referencing. "
        "If the context doesn't contain the answer, say honestly that you couldn't find details about it in the logs."
    )

    user_prompt = f"Context from my journal entries:\n{context}\n\nQuestion: {query_text}\nAnswer:"

    print("Querying local Ollama model (llama3)...")

    # stream the response straight to the terminal
    try:
        response = ollama.chat(
            model="llama3",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            stream=True
        )

        print("\nJournal Assistant Response:")
        print("=" * 60)
        for chunk in response:
            print(chunk['message']['content'], end='', flush=True)
        print("\n" + "=" * 60)

    except Exception as e:
        print(f"\nOllama Error: {e}")
        print("Make sure Ollama is running in the background (`ollama run llama3`).")

if __name__ == "__main__":
    query = input("Ask your local RAG system a question: ")
    if query.strip():
        ask_journal(query)
