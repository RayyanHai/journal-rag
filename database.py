# initialize a local ChromaDB instance and migrate all created chunks into a journal_entries collection

import os
import json
import glob
from chromadb import PersistentClient
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

import config

def migrate_to_chromadb():
    print(f"Initializing persistent ChromaDB client at {config.CHROMA_PATH}...")

    # persistent db folder, acts like a real local sql/nosql store
    client = PersistentClient(path=config.CHROMA_PATH)

    # same embedding model chroma will use internally
    embedding_function = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

    # create or fetch the collection
    collection = client.get_or_create_collection(
        name=config.COLLECTION_NAME,
        embedding_function=embedding_function
    )

    chunk_files = glob.glob(os.path.join(config.CHUNKS_DIR, "*.json"))
    if not chunk_files:
        print(f"No chunks found in {config.CHUNKS_DIR}/. Run chunk.py first.")
        return

    print(f"Found {len(chunk_files)} local chunks. Migrating to ChromaDB...")

    # chroma expects lists of ids, texts, metadatas, and optional embeddings
    ids = []
    documents = []
    metadatas = []

    for file_path in chunk_files:
        with open(file_path, "r", encoding="utf-8") as f:
            chunk_data = json.load(f)

        ids.append(chunk_data["chunk_id"])
        documents.append(chunk_data["text"])

        # chroma only allows simple metadata types (str/int/float/bool) - ours already qualifies
        metadatas.append(chunk_data["metadata"])

    # upsert in batches
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        end_idx = min(i + batch_size, len(ids))

        collection.upsert(
            ids=ids[i:end_idx],
            documents=documents[i:end_idx],
            metadatas=metadatas[i:end_idx]
        )
        print(f"   Indexed chunks {i} to {end_idx}...")

    print(f"ChromaDB populated. Total vectors in collection: {collection.count()}")

if __name__ == "__main__":
    migrate_to_chromadb()
