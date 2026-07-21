import os
import json
from dotenv import load_dotenv
from notion_client import Client
from notion_client.errors import APIResponseError

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

if not NOTION_TOKEN or not DATABASE_ID:
    raise ValueError("Missing NOTION_TOKEN or NOTION_DATABASE_ID in .env file")

# pin to a stable API version, the SDK default (2025-09-03) dropped databases.query
notion = Client(auth=NOTION_TOKEN, notion_version="2022-06-28")

def extract_text_from_rich_text(rich_text_array):
    """Pull plain text out of Notion's rich text format."""
    return "".join([obj.get("plain_text", "") for obj in rich_text_array])

def get_page_content(page_id):
    """Fetch all text blocks inside a specific Notion page."""
    blocks = []
    has_more = True
    start_cursor = None

    while has_more:
        try:
            response = notion.blocks.children.list(
                block_id=page_id,
                start_cursor=start_cursor
            )
            blocks.extend(response.get("results", []))
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor", None)
        except APIResponseError as e:
            print(f"Error fetching blocks for page {page_id}: {e}")
            break

    # combine paragraph, heading, and list blocks into a single string
    full_text = []
    for block in blocks:
        block_type = block.get("type")
        if block_type in ["paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item"]:
            rich_text = block.get(block_type, {}).get("rich_text", [])
            text_content = extract_text_from_rich_text(rich_text)
            if text_content:
                full_text.append(text_content)

    return "\n".join(full_text)

def fetch_journal_entries():
    """Query the database and save each entry as a local JSON file."""
    print("Querying Notion database for journal entries...")

    has_more = True
    start_cursor = None
    total_fetched = 0

    os.makedirs("data/raw", exist_ok=True)

    while has_more:
        try:
            # databases.query was removed in newer SDK versions, so hit the
            # underlying HTTP client directly (same path all endpoints use)
            body = {}
            if start_cursor:
                body["start_cursor"] = start_cursor

            response = notion.databases.parent.request(
                path=f"databases/{DATABASE_ID}/query",
                method="POST",
                body=body,
            )

        except APIResponseError as e:
            print(f"Notion API Error: {e} (Status: {e.status})")
            print("Double-check your NOTION_TOKEN and NOTION_DATABASE_ID in .env, and make sure the connection is shared with your database.")
            return
        except Exception as e:
            print(f"Unexpected error querying database: {e}")
            return

        pages = response.get("results", [])
        if not pages and total_fetched == 0:
            print("No pages found. Is your database empty or did you select the wrong database ID?")
            return

        for page in pages:
            page_id = page.get("id")
            created_time = page.get("created_time", "")

            # pull the title out of properties
            properties = page.get("properties", {})
            title_property = []

            # find whichever property has type "title", regardless of its name
            for prop in properties.values():
                if prop.get("type") == "title":
                    title_property = prop["title"]
                    break

            title = extract_text_from_rich_text(title_property).strip() or "Untitled Entry"

            print(f"Fetching content for: {title} ({created_time[:10] if created_time else 'Unknown Date'})")

            # fetch the actual page content
            content = get_page_content(page_id)

            # build the document payload
            document = {
                "page_id": page_id,
                "title": title,
                "created_time": created_time,
                "properties": {},
                "content": content
            }

            # save locally, named after the page ID
            file_path = f"data/raw/{page_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(document, f, indent=2, ensure_ascii=False)

            total_fetched += 1

        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor", None)

    print(f"\nSaved {total_fetched} journal entries to data/raw/")

if __name__ == "__main__":
    fetch_journal_entries()
