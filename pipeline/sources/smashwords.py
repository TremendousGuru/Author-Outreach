"""Smashwords adapter.

This site is public and indexable by search URLs; the goal here is to allow the
app to reach it even when the original implementation had it marked deferred.
We keep the crawler polite and only process pages that clearly match romance or
fantasy-related search terms.
"""
import html
import re
from urllib.parse import urljoin, urlparse

import requests

from pipeline import db, scoring

BASE = "https://www.smashwords.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
TARGET_WORDS = [
    "romance", "romantic", "fantasy", "paranormal", "fae", "dragon",
    "magical", "sapphic", "vampire", "witch", "dark romance"
]
SEARCH_URLS = [
    "https://www.smashwords.com/books/search?query=romance+fantasy",
    "https://www.smashwords.com/books/search?query=romantic+fantasy",
    "https://www.smashwords.com/books/search?query=romance+novel",
]


def _get(url):
    r = requests.get(url, headers=UA, timeout=25, allow_redirects=True)
    r.raise_for_status()
    return r.text


def _clean_text(v):
    return html.unescape(re.sub(r"\s+", " ", (v or "").strip()))


def _score_target_text(text):
    low = (text or "").lower()
    return any(word in low for word in TARGET_WORDS)


def _candidate_pages(page):
    urls = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', page, re.I):
        if href.startswith("javascript:"):
            continue
        candidate = href.strip()
        if candidate.startswith("/"):
            candidate = urljoin(BASE, candidate)
        if "smashwords.com" not in candidate:
            continue
        if any(token in candidate.lower() for token in ("/book/", "/author/", "/profile/")):
            urls.append(candidate)
    seen = []
    for item in urls:
        if item not in seen:
            seen.append(item)
    return seen


def _extract_meta(page, names):
    for name in names:
        m = re.search(rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']', page, re.I)
        if m:
            return _clean_text(m.group(1))
    return ""


def crawl(cfg, emit, conn):
    touched = []
    seen = set()
    max_books = max(1, int(cfg.get("sources", {}).get("smashwords", {}).get("max_books", 6)))

    for url in SEARCH_URLS:
        try:
            page = _get(url)
        except Exception as exc:
            emit("log", f"  ! Smashwords search failed: {exc}")
            continue
        for candidate in _candidate_pages(page)[:max_books * 3]:
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                book_page = _get(candidate)
            except Exception:
                continue
            title = _extract_meta(book_page, ["twitter:title", "og:title", "title"]) or re.search(r'<h1[^>]*>([^<]+)</h1>', book_page, re.I)
            if title and hasattr(title, "group"):
                title = _clean_text(title.group(1))
            else:
                title = _clean_text(title) if title else ""
            author = _extract_meta(book_page, ["author", "book:author", "twitter:creator", "og:site_name"]) or "Smashwords author"
            bio = f"Smashwords listing for {title or 'title'}"
            if not title or not _score_target_text(f"{title} {author} {book_page}"):
                continue
            norm_handle = re.sub(r"[^a-z0-9]+", "-", (author or "smashwords-author").lower()).strip("-") or "smashwords-author"
            author_id, ident_id, is_new = db.upsert_identity(
                conn, "smashwords", norm_handle, candidate, author or "Smashwords author", bio, "search:smashwords")
            rating_match = re.search(r'(\d+(?:,\d{3})*\s*(?:ratings?|reviews?))', book_page, re.I)
            ratings = None
            if rating_match:
                raw = rating_match.group(1).split()[0].replace(",", "")
                try:
                    ratings = int(raw)
                except ValueError:
                    ratings = None
            pop = "smashwords profile" if ratings is None else f"{ratings} ratings"
            db.upsert_book(conn, author_id, title, "smashwords", book_url=candidate, genre="romance/fantasy", popularity=pop, ratings_count=ratings)
            db.add_signal(conn, author_id, "discovered", "smashwords:search", title)
            emit("author", (author_id, is_new))
            emit("log", f"  + {author} — “{title}”")
            touched.append(author_id)
            conn.commit()
            if len(touched) >= max_books:
                return {"touched": touched}
    emit("log", f"  ✔ Smashwords: {len(touched)} author(s) discovered")
    return {"touched": touched}
