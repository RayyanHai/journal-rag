# generate embeddings for every chunk and build the vector store database

import os
import json
import glob
import numpy as np
from sentence_transformers import SentenceTransformer

def generate_vector_store():
    print("Initializing local embedding model (all-MiniLM-L6-v2)...")
    # small model, runs fine on a normal laptop CPU
    model = SentenceTransformer("all-MiniLM-L6-v2")

    chunk_files = glob.glob("data/chunks/*.json")
    if not chunk_files:
        print("No chunks found in data/chunks/. Did you run chunk.py?")
        return

    print(f"Found {len(chunk_files)} chunks. Generating embeddings...")

    vector_store = []

    for i, file_path in enumerate(chunk_files):
        with open(file_path, "r", encoding="utf-8") as f:
            chunk_data = json.load(f)

        text_to_embed = chunk_data["text"]

        # generate the embedding
        embedding = model.encode(text_to_embed)

        # numpy array -> plain list so it can be dumped to JSON
        vector_list = embedding.tolist()

        # build the vector store record
        record = {
            "chunk_id": chunk_data["chunk_id"],
            "parent_page_id": chunk_data["parent_page_id"],
            "text": text_to_embed,
            "metadata": chunk_data["metadata"],
            "embedding": vector_list
        }

        vector_store.append(record)

        if (i + 1) % 10 == 0 or (i + 1) == len(chunk_files):
            print(f"       Processed {i + 1}/{len(chunk_files)} chunks...")

    # save the vector store to disk
    output_path = "data/vector_store.json"
    os.makedirs("data", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as out_f:
        json.dump(vector_store, out_f, ensure_ascii=False)

    print(f"\nCompiled vector store with embeddings at: {output_path}")

if __name__ == "__main__":
    generate_vector_store()
