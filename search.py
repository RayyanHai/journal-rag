# search the local vector store with plain cosine similarity

import json
import os
import numpy as np
from sentence_transformers import SentenceTransformer

def cosine_similarity(v1, v2):
    """Cosine similarity between two vectors."""
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)

    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return float(dot_product / (norm_v1 * norm_v2))

def query_vector_store(query_text, top_k=3):
    vector_store_path = "data/vector_store.json"

    if not os.path.exists(vector_store_path):
        print("Vector store not found. Run embed.py first.")
        return

    # load the vector store
    with open(vector_store_path, "r", encoding="utf-8") as f:
        vector_store = json.load(f)

    # load the same embedding model used to build the store
    model = SentenceTransformer("all-MiniLM-L6-v2")

    # embed the query
    print(f"\nEmbedding query: '{query_text}'")
    query_vector = model.encode(query_text).tolist()

    # score every chunk
    scored_chunks = []
    for record in vector_store:
        score = cosine_similarity(query_vector, record["embedding"])

        scored_chunks.append({
            "chunk_id": record["chunk_id"],
            "text": record["text"],
            "score": score,
            "metadata": record["metadata"]
        })

    # sort descending and keep the top_k
    scored_chunks.sort(key=lambda x: x["score"], reverse=True)
    top_matches = scored_chunks[:top_k]

    # print results
    print(f"\nTop {top_k} matches:")
    print("=" * 60)

    for rank, match in enumerate(top_matches, start=1):
        meta = match["metadata"]
        print(f"Rank {rank} | Match Score: {match['score']:.4f}")
        print(f"Source Entry: {meta['source_title']} ({meta['date_string']})")
        print(f"Text Context:\n\"{match['text']}\"")
        print("-" * 60)

if __name__ == "__main__":
    # quick manual test
    user_query = input("Ask your journal a question: ")
    if user_query.strip():
        query_vector_store(user_query, top_k=3)
