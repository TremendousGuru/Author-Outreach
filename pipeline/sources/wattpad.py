"""Wattpad adapter.

This source is public-only and intentionally does not use login credentials or
crawl private pages. It targets public story search results that match the
romance/fantasy niches the app cares about.
"""
import html
import re
from urllib.parse import urljoin

import requests

from pipeline import db

BASE = "https://www.wattpad.com"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}
TARGET_WORDS = [
    "romance", "romantic", "fantasy", "paranormal", "fae", "dragon",
    "vampire", "magic", "witch", "dark romance", "reverse harem",
    "sapphic", "shifter"
]
SEARCH_URLS = [
    "https://www.wattpad.com/search/romance%20fantasy",
    "https://www.wattpad.com/search/fantasy%20romance",
    "https://www.wattpad.com/search/paranormal%20romance",
]


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
        if "wattpad.com" not in candidate:
            continue
        if "/story/" in candidate.lower() and "/login" not in candidate.lower():
            if candidate not in seen:
                seen.append(candidate)
    return seen


def crawl(cfg, emit, conn):
    touched = []
    max_items = max(1, int(cfg.get("sources", {}).get("wattpad", {}).get("max_stories", 6)))
    seen = set()

    for url in SEARCH_URLS:
        try:
            page = _get(url)
        except Exception as exc:
            emit("log", f"  ! Wattpad search failed: {exc}")
            continue

        for candidate in _candidate_pages(page):
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                story_page = _get(candidate)
            except Exception:
                continue

            title = _clean(re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', story_page, re.I).group(1)) if re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', story_page, re.I) else "Wattpad story"
            author = _clean(re.search(r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']+)["\']', story_page, re.I).group(1)) if re.search(r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']+)["\']', story_page, re.I) else "Wattpad author"
            text = f"{title} {author} {story_page}"
            if not _score_target_text(text):
                continue

            author_handle = re.sub(r"[^a-z0-9]+", "-", author.lower()).strip("-") or "wattpad-author"
            author_id, _, is_new = db.upsert_identity(
                conn,
                "wattpad",
                author_handle,
                candidate,
                author,
                f"Wattpad public story: {title}",
                "search:wattpad",
            )
            db.upsert_book(
                conn,
                author_id,
                title,
                "wattpad",
                book_url=candidate,
                genre="romance/fantasy",
            )
            db.add_signal(conn, author_id, "discovered", "wattpad:search", title)
            emit("author", (author_id, is_new))
            emit("log", f"  + {author} — “{title}”")
            touched.append(author_id)
            conn.commit()
            if len(touched) >= max_items:
                return {"touched": touched}

    emit("log", f"  ✔ Wattpad: {len(touched)} author(s) discovered")
    return {"touched": touched}
