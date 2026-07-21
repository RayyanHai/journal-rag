# hybrid search combining dense vectors and BM25 keyword search

import os
import json
import glob
import numpy as np
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi

def cosine_similarity(v1, v2):
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    return float(dot_product / (norm_v1 * norm_v2)) if norm_v1 and norm_v2 else 0.0

def run_hybrid_search(query_text, top_k=3, k_constant=60):
    vector_store_path = "data/vector_store.json"
    if not os.path.exists(vector_store_path):
        print("Vector store not found. Run embed.py first.")
        return

    with open(vector_store_path, "r", encoding="utf-8") as f:
        vector_store = json.load(f)

    print(f"\nTotal chunks loaded in memory: {len(vector_store)}")

    # dense vector search
    model = SentenceTransformer("all-MiniLM-L6-v2")
    query_vector = model.encode(query_text).tolist()

    dense_results = []
    for record in vector_store:
        score = cosine_similarity(query_vector, record["embedding"])
        dense_results.append((record["chunk_id"], score, record))

    dense_results.sort(key=lambda x: x[1], reverse=True)
    print(f"Dense vector search finished. Top match score: {dense_results[0][1]:.4f}")

    # sparse bm25 search
    corpus = [record["text"].lower().split() for record in vector_store]
    bm25 = BM25Okapi(corpus)

    tokenized_query = query_text.lower().split()
    bm25_scores = bm25.get_scores(tokenized_query)

    sparse_results = []
    for idx, score in enumerate(bm25_scores):
        sparse_results.append((vector_store[idx]["chunk_id"], score, vector_store[idx]))

    sparse_results.sort(key=lambda x: x[1], reverse=True)
    print(f"Sparse BM25 search finished. Top match score: {sparse_results[0][1]:.4f}")

    # reciprocal rank fusion (rrf)
    rrf_scores = {}
    id_to_record = {r["chunk_id"]: r for r in vector_store}

    # score by dense rank
    for rank, (chunk_id, _, _) in enumerate(dense_results, start=1):
        if chunk_id not in rrf_scores:
            rrf_scores[chunk_id] = 0.0
        rrf_scores[chunk_id] += 1.0 / (k_constant + rank)

    # score by sparse rank, only counting real keyword matches
    for rank, (chunk_id, score, _) in enumerate(sparse_results, start=1):
        if score > 0:
            if chunk_id not in rrf_scores:
                rrf_scores[chunk_id] = 0.0
            rrf_scores[chunk_id] += 1.0 / (k_constant + rank)

    sorted_rrf = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

    if not sorted_rrf:
        print("No matching results could be fused.")
        return

    print(f"\nHybrid search results for: '{query_text}'")
    print("=" * 60)
    for rank, (chunk_id, rrf_score) in enumerate(sorted_rrf[:top_k], start=1):
        record = id_to_record[chunk_id]
        meta = record["metadata"]
        print(f"Rank {rank} | Fused RRF Score: {rrf_score:.5f}")
        print(f"Source: {meta['source_title']} ({meta['date_string']})")
        print(f"Text:\n\"{record['text']}\"")
        print("-" * 60)

if __name__ == "__main__":
    query = input("Test hybrid keyword + vector search: ")
    if query.strip():
        run_hybrid_search(query)
