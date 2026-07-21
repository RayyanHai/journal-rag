# temporal-aware hybrid retrieval
#
# the old version just embedded the whole question, pulled the 15 nearest
# vectors, ran BM25 + RRF, and returned the top 3. No concept of dates or
# "most recent", so "what did I do with Alex after Oct 9th?" could return a
# July 2024 entry.
#
# this version takes a structured query (from query_constructor.py) and
# picks the right strategy for the question being asked:
#
#   1. recency queries ("when was the last time...") are a sort, not a search.
#      filter by date + keyword, then sort by date - deterministic, correct.
#
#   2. conceptual queries ("how have I been coping with stress?") stay hybrid:
#      dense vectors for vibes + BM25 for keywords, fused with RRF - but the
#      candidate pool is restricted to the date range the user actually asked for.

import chromadb
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi

import config

# candidates pulled into the hybrid fusion pool. The old value (15) was way
# too small for a 3,500-chunk store - the right entry was often ranked 20th
# and never seen. 60 gives BM25 + RRF enough to actually work with.
CANDIDATE_POOL = 60


class SafeEmbeddingFunction:
    """Wrapper so we embed queries with the exact same model the DB used."""

    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def __call__(self, input_texts):
        return self.model.encode(input_texts).tolist()


def _build_date_where(date_after, date_before):
    """Turn date bounds into a ChromaDB metadata filter on the numeric date_int."""
    conditions = []
    if date_after is not None:
        conditions.append({"date_int": {"$gte": date_after}})
    if date_before is not None:
        conditions.append({"date_int": {"$lte": date_before}})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _keyword_match(text, keywords):
    """Case-insensitive check that a chunk mentions at least one keyword."""
    if not keywords:
        return True
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords)


def _print_results(query_label, matches):
    print(f"\nRetrieval results for: '{query_label}'")
    print("=" * 60)
    for rank, data in enumerate(matches, start=1):
        meta = data["meta"]
        print(f"Rank {rank} | {data.get('reason', '')}")
        print(f"Source: {meta['source_title']} ({meta['date_string']})")
        print(f"Text:\n\"{data['text']}\"")
        print("-" * 60)


def run_chroma_hybrid_search(query, top_k=5, verbose=True):
    """
    query: a JournalQuery (from query_constructor) OR a plain string.
    Returns a list of {"text", "meta"} dicts, best first.
    verbose=False silences all prints (used by the eval harness / quiet agent mode).
    """
    # accept a plain string too, for quick testing
    if isinstance(query, str):
        from query_constructor import JournalQuery
        query = JournalQuery(search_text=query)

    client = chromadb.PersistentClient(path=config.CHROMA_PATH)
    collection = client.get_collection(name=config.COLLECTION_NAME)

    where = _build_date_where(query.date_after, query.date_before)
    if where and verbose:
        print(f"Date filter active: {where}")

    # recency path: "the last / most recent / first time ..."
    # this is deterministic - pull everything in the date range, keep only
    # chunks that mention the keyword(s), and sort by actual date.
    if query.recency in ("latest", "earliest"):
        data = collection.get(where=where, include=["documents", "metadatas"])
        candidates = []
        for doc, meta in zip(data["documents"], data["metadatas"]):
            if _keyword_match(doc, query.keywords):
                candidates.append({"text": doc, "meta": meta})

        if not candidates:
            if verbose:
                print("No entries matched those keywords / dates.")
            return []

        reverse = query.recency == "latest"
        candidates.sort(key=lambda c: c["meta"].get("date_int", 0), reverse=reverse)
        top = candidates[:top_k]
        for c in top:
            c["reason"] = f"{query.recency} match by date"
        if verbose:
            _print_results(query.search_text, top)
        return top

    # conceptual path: hybrid dense (vector) + sparse (BM25), fused by RRF,
    # with the date range applied to the candidate pool.
    embedder = SafeEmbeddingFunction()
    # fold keywords into the embedded text so the dense side leans on them too
    dense_text = " ".join([query.search_text] + query.keywords).strip()
    query_embedding = embedder([dense_text])

    pool_size = min(CANDIDATE_POOL, collection.count())
    vector_results = collection.query(
        query_embeddings=query_embedding,
        n_results=pool_size,
        where=where,
    )

    if not vector_results["ids"] or not vector_results["ids"][0]:
        if verbose:
            print("No matching entries found with current filters.")
        return []

    ids = vector_results["ids"][0]
    documents = vector_results["documents"][0]
    metadatas = vector_results["metadatas"][0]

    # soft keyword focus: if the user named specific entities, prefer pool
    # members that actually mention them, but only if that still leaves
    # enough to work with, so a slightly-off keyword can't wipe out the pool
    if query.keywords:
        focused = [
            (i, d, m)
            for i, d, m in zip(ids, documents, metadatas)
            if _keyword_match(d, query.keywords)
        ]
        if len(focused) >= 3:
            ids, documents, metadatas = map(list, zip(*focused))

    # dense ranking (by vector order, already nearest-first from Chroma)
    dense_order = list(ids)

    # sparse ranking via BM25 over the candidate pool
    corpus = [doc.lower().split() for doc in documents]
    bm25 = BM25Okapi(corpus)
    tokenized_query = dense_text.lower().split()
    bm25_scores = bm25.get_scores(tokenized_query)
    sparse_order = [
        doc_id
        for doc_id, _ in sorted(
            zip(ids, bm25_scores), key=lambda x: x[1], reverse=True
        )
    ]

    # reciprocal rank fusion: blend the two rankings into one score
    k_constant = 60
    rrf_scores = {}
    for rank, doc_id in enumerate(dense_order, start=1):
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k_constant + rank)
    for rank, doc_id in enumerate(sparse_order, start=1):
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k_constant + rank)

    id_to_data = {
        doc_id: {"text": text, "meta": meta}
        for doc_id, text, meta in zip(ids, documents, metadatas)
    }
    final_sorted = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

    matches = []
    for doc_id, score in final_sorted[:top_k]:
        data = id_to_data[doc_id]
        data["reason"] = f"Fused RRF score: {score:.5f}"
        matches.append(data)

    if verbose:
        _print_results(dense_text, matches)
    return matches


def count_journal_entries(keywords, date_after=None, date_before=None, verbose=True):
    """
    DETERMINISTIC count - the fix for "how many times did I...".

    A vector search can only tally a top_k-capped SAMPLE, so it can't reliably
    count. This pulls EVERY chunk in the date range (no top_k), keeps the ones
    that mention the keyword(s), and counts DISTINCT ENTRIES (not chunks: an
    entry split into 8 chunks is still one occurrence). Counting is a database
    job, not a search job.

    Returns {"count": int, "entries": [{"date","title"}, ...]} sorted by date.
    """
    client = chromadb.PersistentClient(path=config.CHROMA_PATH)
    collection = client.get_collection(name=config.COLLECTION_NAME)

    where = _build_date_where(date_after, date_before)
    if where and verbose:
        print(f"Counting with date filter: {where}")

    data = collection.get(where=where, include=["documents", "metadatas"])

    # collapse chunks to their parent entry. chunk ids are "{page_id}_chunk_{n}",
    # so everything before "_chunk_" identifies the entry.
    seen_entries = {}
    for chunk_id, doc, meta in zip(data["ids"], data["documents"], data["metadatas"]):
        if not _keyword_match(doc, keywords):
            continue
        parent_id = chunk_id.split("_chunk_")[0]
        if parent_id not in seen_entries:
            seen_entries[parent_id] = {
                "date": meta.get("date_string", "unknown"),
                "title": meta.get("source_title", "Untitled"),
            }

    entries = sorted(seen_entries.values(), key=lambda e: e["date"])
    result = {"count": len(entries), "entries": entries}

    if verbose:
        print(f"Exact count for {keywords or 'all entries'}: {result['count']}")
        for e in entries:
            print(f"  {e['date']} - {e['title']}")

    return result


if __name__ == "__main__":
    from query_constructor import construct_query

    q = input("Ask your journal: ").strip()
    if q:
        structured = construct_query(q)
        print(f"Parsed: {structured.model_dump()}")
        run_chroma_hybrid_search(structured)
