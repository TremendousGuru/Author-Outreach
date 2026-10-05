"""Public romance and science-fiction/fantasy reviews from The Book Commentary."""
import html
import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pipeline import db, scoring

BASE = "https://www.thebookcommentary.com"
CATEGORY_URLS = {
    "Romance": f"{BASE}/featured-category/romance",
    "Sci-Fi & Fantasy": f"{BASE}/featured-category/top-sci-fi-and-fantasy",
}
UA = {
    "User-Agent": "Mozilla/5.0 (compatible; AuthorOutreach/1.0; public research)",
    "Accept": "text/html,application/xhtml+xml",
}


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def review_urls(page, page_url):
    parser = _LinkParser()
    parser.feed(page)
    urls = []
    for href in parser.hrefs:
        candidate = urljoin(page_url, html.unescape(href).strip())
        parsed = urlparse(candidate)
        if (parsed.scheme == "https" and parsed.netloc.lower() == "www.thebookcommentary.com"
                and re.match(r"^/review-preview/\d+/?", parsed.path)
                and candidate not in urls):
            urls.append(candidate)
    return urls


def _cell_value(page, label):
    match = re.search(
        rf"<th\b[^>]*>\s*{re.escape(label)}\s*:?[\s]*</th>\s*<td\b[^>]*>(.*?)</td>",
        page, re.I | re.S)
    if not match:
        return ""
    value = re.sub(r"<[^>]+>", " ", match.group(1))
    return html.unescape(re.sub(r"\s+", " ", value)).strip()


def _meta_content(page, key):
    for tag in re.findall(r"<meta\b[^>]*>", page, re.I):
        key_match = re.search(r"(?:name|property)=[\"']([^\"']+)[\"']", tag, re.I)
        content_match = re.search(r"content=[\"']([^\"']*)[\"']", tag, re.I)
        if key_match and content_match and key_match.group(1).lower() == key.lower():
            return html.unescape(content_match.group(1)).strip()
    return ""


def parse_review(page, url, category=""):
    title_match = re.search(r"<h1\b[^>]*>(.*?)</h1>", page, re.I | re.S)
    title = ""
    if title_match:
        title = re.sub(r"<[^>]+>", " ", title_match.group(1))
        title = html.unescape(re.sub(r"\s+", " ", title)).strip()
    author = _cell_value(page, "Author")
    genre = _cell_value(page, "Genre") or category
    description = _meta_content(page, "og:description")
    review_date = ""
    date_match = re.search(r"<h4>\s*Date:\s*<strong[^>]*>(.*?)</strong>", page, re.I | re.S)
    if date_match:
        review_date = html.unescape(re.sub(r"<[^>]+>", " ", date_match.group(1))).strip()
    if not title or not author:
        return None
    return {
        "title": title,
        "author": author,
        "genre": genre,
        "description": description[:500],
        "review_date": review_date,
        "url": url,
    }


def _get(session, url):
    response = session.get(url, timeout=25)
    response.raise_for_status()
    return response.text


def crawl(cfg, emit, conn):
    source_cfg = cfg.get("sources", {}).get("bookcommentary", {})
    max_reviews = max(1, int(source_cfg.get("max_reviews", 12)))
    delay = max(1.0, float(source_cfg.get("delay_seconds", 1.2)))
    retry = Retry(total=3, connect=3, read=2, backoff_factor=0.5,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",))
    session = requests.Session()
    session.headers.update(UA)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    seen_urls = set()
    touched = []
    count = 0

    for category, listing_url in CATEGORY_URLS.items():
        if count >= max_reviews:
            break
        try:
            listing = _get(session, listing_url)
        except requests.RequestException as exc:
            emit("log", f"  ! Book Commentary category failed ({category}): {exc}")
            continue
        time.sleep(delay)
        for review_url in review_urls(listing, listing_url):
            if review_url in seen_urls:
                continue
            seen_urls.add(review_url)
            if count >= max_reviews:
                break
            try:
                page = _get(session, review_url)
            except requests.RequestException as exc:
                emit("log", f"  ! Book Commentary review failed: {exc}")
                continue
            review = parse_review(page, review_url, category)
            if not review:
                emit("log", f"  ! Could not read book title and author: {review_url}")
                time.sleep(delay)
                continue
            searchable = " ".join((review["title"], review["genre"],
                                   review["description"])).lower()
            if scoring.matches(searchable, cfg["scoring"]["exclude_keywords"]):
                time.sleep(delay)
                continue

            author_id, _, is_new = db.upsert_identity(
                conn, "bookcommentary", review["author"], review_url,
                review["author"],
                f"Public book review on The Book Commentary. {review['genre']}. {review['description']}"[:500],
                f"category:{category.lower()}")
            db.upsert_book(
                conn, author_id, review["title"], "bookcommentary",
                book_url=review_url, genre=review["genre"])
            db.add_signal(conn, author_id, "discovered", "bookcommentary:review",
                          review["title"])
            conn.commit()
            emit("author", (author_id, is_new))
            emit("log", f"  + {review['author']} — {review['title']} ({category})")
            touched.append(author_id)
            count += 1
            time.sleep(delay)

    emit("log", f"  ✔ The Book Commentary: {count} public review(s) processed")
    return {"touched": touched}