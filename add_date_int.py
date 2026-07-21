# one-time migration: backfill a numeric date_int (YYYYMMDD) onto every chunk
# already stored in ChromaDB, so we can run real temporal range filters.
#
# the original metadata only had date_string ("2025-10-09"), but Chroma's
# $gte/$lte only compare numbers, so "after Oct 9th" could never be a hard
# filter. This adds the numeric field without touching embeddings, metadata only.

import chromadb


def backfill_date_int():
    client = chromadb.PersistentClient(path="data/chroma_db")
    collection = client.get_collection(name="journal_entries")

    total = collection.count()
    print(f"Found {total} chunks. Backfilling date_int...")

    # pull everything, ids + metadatas only, no documents/embeddings needed
    data = collection.get(include=["metadatas"])
    ids = data["ids"]
    metadatas = data["metadatas"]

    updated_ids = []
    updated_metas = []
    skipped = 0

    for doc_id, meta in zip(ids, metadatas):
        if meta.get("date_int") is not None:
            skipped += 1
            continue

        date_string = meta.get("date_string", "")
        if date_string and date_string != "unknown" and len(date_string) >= 10:
            date_int = int(date_string[:10].replace("-", ""))
        else:
            date_int = 0

        new_meta = dict(meta)
        new_meta["date_int"] = date_int
        updated_ids.append(doc_id)
        updated_metas.append(new_meta)

    if not updated_ids:
        print(f"Nothing to do, all {skipped} chunks already have date_int.")
        return

    # update metadata in batches (metadata-only update, embeddings untouched)
    batch_size = 200
    for i in range(0, len(updated_ids), batch_size):
        end = min(i + batch_size, len(updated_ids))
        collection.update(ids=updated_ids[i:end], metadatas=updated_metas[i:end])
        print(f"   Updated chunks {i} to {end}...")

    print(f"Done. Backfilled {len(updated_ids)} chunks ({skipped} already had it).")

    # quick sanity check that range filtering now works
    sample = collection.get(where={"date_int": {"$gte": 20251009}}, limit=1, include=["metadatas"])
    if sample["ids"]:
        print(f"Range filter test OK, found a chunk dated {sample['metadatas'][0]['date_string']}")


if __name__ == "__main__":
    backfill_date_int()
