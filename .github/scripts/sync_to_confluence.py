import os
import sys
import glob
import json
import requests
import frontmatter
import markdown
from pathlib import Path

CONFLUENCE_URL = os.environ["CONFLUENCE_URL"].rstrip("/")
SPACE_KEY = os.environ["CONFLUENCE_SPACE_KEY"]
ROOT_PAGE_ID = os.environ["CONFLUENCE_ROOT_PAGE_ID"]
EMAIL = os.environ["CONFLUENCE_EMAIL"]
API_TOKEN = os.environ["CONFLUENCE_API_TOKEN"]
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

AUTH = (EMAIL, API_TOKEN)
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

BANNER = (
    "<ac:structured-macro ac:name='info'>"
    "<ac:parameter ac:name='title'>Auto-synced from GitHub</ac:parameter>"
    "<ac:rich-text-body>"
    "<p>⚠️ This page is automatically synced from GitHub. "
    "Do not edit directly in Confluence — changes will be overwritten.</p>"
    "</ac:rich-text-body>"
    "</ac:structured-macro>"
)

IGNORE_DIRS = set()
ignore_file = Path(".confluenceignore")
if ignore_file.exists():
    for line in ignore_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            IGNORE_DIRS.add(line.strip("/"))


def md_to_storage(markdown_body):
    """Convert markdown to Confluence storage format (HTML)."""
    return markdown.markdown(
        markdown_body,
        extensions=["tables", "fenced_code", "codehilite", "toc", "nl2br"],
    )


def get_or_create_page(title, parent_id, body, labels=None):
    """Find an existing page by title under parent, or create it."""
    search_url = (
        f"{CONFLUENCE_URL}/rest/api/content"
        f"?spaceKey={SPACE_KEY}&title={requests.utils.quote(title)}"
        f"&expand=version,body.storage,metadata.labels"
    )
    resp = requests.get(search_url, auth=AUTH, headers=HEADERS)
    resp.raise_for_status()
    results = resp.json().get("results", [])

    full_body = BANNER + body

    if results:
        page = results[0]
        page_id = page["id"]
        current_version = page["version"]["number"]
        print(f"  Updating existing page '{title}' (id={page_id})")
        if not DRY_RUN:
            update_url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}"
            requests.put(
                update_url,
                auth=AUTH,
                headers=HEADERS,
                json={
                    "version": {"number": current_version + 1},
                    "title": title,
                    "type": "page",
                    "body": {"storage": {"value": full_body, "representation": "storage"}},
                },
            ).raise_for_status()
            if labels:
                set_labels(page_id, labels)
        return page_id

    print(f"  Creating new page '{title}' under parent {parent_id}")
    if DRY_RUN:
        return None
    create_url = f"{CONFLUENCE_URL}/rest/api/content"
    resp = requests.post(
        create_url,
        auth=AUTH,
        headers=HEADERS,
        json={
            "type": "page",
            "title": title,
            "space": {"key": SPACE_KEY},
            "ancestors": [{"id": parent_id}],
            "body": {"storage": {"value": full_body, "representation": "storage"}},
        },
    )
    resp.raise_for_status()
    page_id = resp.json()["id"]
    if labels:
        set_labels(page_id, labels)
    return page_id


def set_labels(page_id, labels):
    url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}/label"
    payload = [{"prefix": "global", "name": lbl} for lbl in labels]
    requests.post(url, auth=AUTH, headers=HEADERS, json=payload).raise_for_status()


def should_ignore(rel_path):
    parts = Path(rel_path).parts
    for ignored in IGNORE_DIRS:
        if ignored in parts:
            return True
    return False


def process_file(md_path, docs_root):
    rel = Path(md_path).relative_to(docs_root)
    if should_ignore(str(rel)):
        print(f"SKIP (ignored): {rel}")
        return

    post = frontmatter.load(md_path)
    if not post.get("sync_to_confluence", False):
        print(f"SKIP (no sync flag): {rel}")
        return

    title = post.get("title") or rel.stem.replace("-", " ").replace("_", " ").title()
    labels = post.get("confluence-labels", [])

    # All pages go flat under the root page — no sub-pages for directories
    body_html = md_to_storage(post.content)
    print(f"SYNC: {rel} → '{title}'")
    get_or_create_page(title, ROOT_PAGE_ID, body_html, labels=labels)


def main():
    docs_root = Path("docs")
    if not docs_root.exists():
        print("No docs/ directory found.")
        sys.exit(0)

    md_files = sorted(docs_root.rglob("*.md"))
    if not md_files:
        print("No markdown files found in docs/.")
        sys.exit(0)

    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Processing {len(md_files)} file(s)...\n")
    for f in md_files:
        process_file(str(f), docs_root)

    print("\nDone.")


if __name__ == "__main__":
    main()
