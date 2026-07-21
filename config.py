# Central switch for WHICH corpus the whole stack reads/writes.
#
# The real journal lives in data/ (gitignored — it's private). The committed
# synthetic demo corpus lives in demo/data/, so the public repo is runnable and
# CI can build a real index without ever touching personal data.
#
# Set JOURNAL_DEMO=1 to point the entire pipeline (chunk -> database -> search ->
# period_analysis -> eval harness) at the demo corpus. JOURNAL_DATA_DIR overrides
# the directory outright if you need a third location.

import os

DEMO_MODE = os.getenv("JOURNAL_DEMO", "").strip().lower() in ("1", "true", "yes")

DATA_DIR = os.getenv("JOURNAL_DATA_DIR") or ("demo/data" if DEMO_MODE else "data")

RAW_DIR = os.path.join(DATA_DIR, "raw")
CHUNKS_DIR = os.path.join(DATA_DIR, "chunks")
CHROMA_PATH = os.path.join(DATA_DIR, "chroma_db")
COLLECTION_NAME = "journal_entries"
