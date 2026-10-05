"""Reedsy Discovery adapter.

This keeps the source in the active crawl set without requiring a custom
browser stack. It handles the public discovery pages and filters to the
romance/fantasy results the app cares about.
"""
import html
import re
from urllib.parse import urljoin

import requests

from pipeline import db

BASE = "https://reedsy.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
SEARCH_URLS = [
    "https://reedsy.com/discovery",
    "https://reedsy.com/discovery?genre=romance",
    "https://reedsy.com/discovery?genre=fantasy",
]
TARGET_WORDS = ["romance", "fantasy", "paranormal", "fae", "dragon", "magic", "vampire", "dark romance"]


def _get(url):
    r = requests.get(url, headers=UA, timeout=25, allow_redirects=True)
    r.raise_for_status()
    return r.text


def _clean(v):
    return html.unescape(re.sub(r"\s+", " ", (v or "").strip()))


def _score_target_text(text):
    low = (text or "").lower()
    return any(word in low for word in TARGET_WORDS)


def _candidate_pages(page):
    seen = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', page, re.I):
        candidate = href.strip()
        if candidate.startswith("javascript:"):
            continue
        if candidate.startswith("/"):
            candidate = urljoin(BASE, candidate)
        if "reedsy.com" not in candidate:
            continue
        if any(token in candidate.lower() for token in ("/books/", "/book/", "/authors/", "/author/")):
            if candidate not in seen:
                seen.append(candidate)
    return seen


def crawl(cfg, emit, conn):
    touched = []
    max_items = max(1, int(cfg.get("sources", {}).get("reedsy", {}).get("max_books", 6)))
    seen = set()
    for url in SEARCH_URLS:
        try:
            page = _get(url)
        except Exception as exc:
            emit("log", f"  ! Reedsy search failed: {exc}")
            continue
        for candidate in _candidate_pages(page):
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                item_page = _get(candidate)
            except Exception:
                continue
            title = re.search(r'<title>([^<]+)</title>', item_page, re.I)
            title = _clean(title.group(1)) if title else "Reedsy title"
            author = re.search(r'author[^>]*>([^<]+)</', item_page, re.I) or re.search(r'property="og:title"[^>]*content="([^"]+)"', item_page, re.I)
            author_name = _clean(author.group(1)) if author else "Reedsy author"
            text = f"{title} {author_name} {item_page}"
            if not _score_target_text(text):
                continue
            handle = re.sub(r"[^a-z0-9]+", "-", author_name.lower()).strip("-") or "reedsy-author"
            author_id, _, is_new = db.upsert_identity(conn, "reedsy", handle, candidate, author_name, f"Reedsy discovery: {title}", "search:reedsy")
            db.upsert_book(conn, author_id, title, "reedsy", book_url=candidate, genre="romance/fantasy")
            db.add_signal(conn, author_id, "discovered", "reedsy:search", title)
            emit("author", (author_id, is_new))
            emit("log", f"  + {author_name} — “{title}”")
            touched.append(author_id)
            conn.commit()
            if len(touched) >= max_items:
                return {"touched": touched}
    emit("log", f"  ✔ Reedsy: {len(touched)} author(s) discovered")
    return {"touched": touched}
