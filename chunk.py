# step 2 after ingesting: read the raw entries and output clean chunks into a new folder

import os
import json
import glob
import re

import config

def native_text_splitter(text, chunk_size=600, chunk_overlap=120):
    """
    Pure Python text splitter that mimics a recursive character splitter.
    Splits on paragraphs/sentences so it doesn't break thoughts in half.
    """
    # clean up spacing
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if not text:
        return []

    # split into rough sentences/clauses
    sentences = re.split(r'(?<=[.!?])\s+|\n', text)

    chunks = []
    current_chunk = []
    current_length = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        sentence_length = len(sentence)

        # if this sentence would push us past the max chunk size, lock in the current chunk
        if current_length + sentence_length > chunk_size and current_chunk:
            combined_text = " ".join(current_chunk)
            chunks.append(combined_text)

            # keep the most recent sentences as overlap for context continuity
            overlap_chunk = []
            overlap_len = 0
            for s in reversed(current_chunk):
                if overlap_len + len(s) < chunk_overlap:
                    overlap_chunk.insert(0, s)
                    overlap_len += len(s) + 1
                else:
                    break
            current_chunk = overlap_chunk
            current_length = overlap_len

        current_chunk.append(sentence)
        current_length += sentence_length + 1 # +1 for space

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks

def process_and_chunk_journals():
    print("Starting native journal chunking pipeline...")

    # setup paths (config points at data/ or demo/data/ depending on JOURNAL_DEMO)
    raw_files = glob.glob(os.path.join(config.RAW_DIR, "*.json"))
    output_dir = config.CHUNKS_DIR
    os.makedirs(output_dir, exist_ok=True)

    if not raw_files:
        print(f"No raw JSON files found in {config.RAW_DIR}/. Did you run ingest.py?")
        return

    total_chunks_created = 0

    for file_path in raw_files:
        with open(file_path, "r", encoding="utf-8") as f:
            entry = json.load(f)

        page_id = entry.get("page_id")
        title = entry.get("title")
        created_time = entry.get("created_time")
        content = entry.get("content", "").strip()

        if not content:
            continue # skip empty journal entries

        # generate the splits
        chunks = native_text_splitter(content, chunk_size=600, chunk_overlap=120)

        # save each chunk with enriched metadata
        for index, chunk_text in enumerate(chunks):
            chunk_id = f"{page_id}_chunk_{index}"

            chunk_payload = {
                "chunk_id": chunk_id,
                "parent_page_id": page_id,
                "text": chunk_text,
                "metadata": {
                    "source_title": title,
                    "created_time": created_time,
                    "date_string": created_time[:10] if created_time else "unknown",
                    # numeric YYYYMMDD so ChromaDB can do real range filters ($gte/$lte) -
                    # its comparison operators only work on numbers, not date strings
                    "date_int": int(created_time[:10].replace("-", "")) if created_time else 0
                }
            }

            # save the processed chunk as a JSON file
            output_file = os.path.join(output_dir, f"{chunk_id}.json")
            with open(output_file, "w", encoding="utf-8") as out_f:
                json.dump(chunk_payload, out_f, indent=2, ensure_ascii=False)

            total_chunks_created += 1

    print(f"Generated {total_chunks_created} metadata-enriched chunks inside {output_dir}/")

if __name__ == "__main__":
    process_and_chunk_journals()
