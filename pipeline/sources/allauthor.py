"""AllAuthor adapter.

The site exposes public author and book listings. The crawl is intentionally
conservative: it only keeps pages that clearly look like romance/fantasy.
"""
import html
import re
from urllib.parse import urljoin

import requests

from pipeline import db

BASE = "https://allauthor.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
SEARCH_URLS = [
    "https://allauthor.com/",
    "https://allauthor.com/?s=romance",
    "https://allauthor.com/?s=fantasy",
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
        if not candidate or candidate.startswith("javascript:"):
            continue
        if candidate.startswith("/"):
            candidate = urljoin(BASE, candidate)
        if "allauthor.com" not in candidate:
            continue
        if any(token in candidate.lower() for token in ("/author/", "/authors/", "/profile/", "/book/")):
            if candidate not in seen:
                seen.append(candidate)
    return seen


def crawl(cfg, emit, conn):
    touched = []
    max_items = max(1, int(cfg.get("sources", {}).get("allauthor", {}).get("max_authors", 6)))
    seen = set()
    for url in SEARCH_URLS:
        try:
            page = _get(url)
        except Exception as exc:
            emit("log", f"  ! AllAuthor search failed: {exc}")
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
            title = _clean(title.group(1)) if title else "AllAuthor profile"
            author = re.search(r'author[^>]*>([^<]+)</', item_page, re.I) or re.search(r'property="og:title"[^>]*content="([^"]+)"', item_page, re.I)
            author_name = _clean(author.group(1)) if author else "AllAuthor author"
            if not _score_target_text(f"{title} {author_name} {item_page}"):
                continue
            handle = re.sub(r"[^a-z0-9]+", "-", author_name.lower()).strip("-") or "allauthor-author"
            author_id, _, is_new = db.upsert_identity(conn, "allauthor", handle, candidate, author_name, f"AllAuthor profile: {title}", "search:allauthor")
            db.upsert_book(conn, author_id, title, "allauthor", book_url=candidate, genre="romance/fantasy")
            db.add_signal(conn, author_id, "discovered", "allauthor:search", title)
            emit("author", (author_id, is_new))
            emit("log", f"  + {author_name} — “{title}”")
            touched.append(author_id)
            conn.commit()
            if len(touched) >= max_items:
                return {"touched": touched}
    emit("log", f"  ✔ AllAuthor: {len(touched)} author(s) discovered")
    return {"touched": touched}
