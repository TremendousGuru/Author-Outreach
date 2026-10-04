"""Royal Road source — serialized fantasy/romantasy platform.

Listing pages (best-rated, rising-stars, latest-updates…) expose fiction
cards: title, tags, followers, rating. Each fiction page gives the author
profile link. New/low-rating fiction = exactly our target profile.
"""
import re
import time

import requests

from pipeline import db, scoring

BASE = "https://www.royalroad.com"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml"}

LISTINGS = {
    "best-rated": "/fictions/best-rated",
    "trending": "/fictions/trending",
    "rising-stars": "/fictions/rising-stars",
    "latest-updates": "/fictions/latest-updates",
    "new": "/fictions/new",
}


def _get(path, retries=2):
    for attempt in range(retries + 1):
        try:
            r = requests.get(BASE + path, headers=UA, timeout=25)
            if r.status_code == 200:
                return r.text
            if r.status_code == 429 and attempt < retries:
                time.sleep(5 * (attempt + 1))
                continue
        except requests.RequestException:
            if attempt >= retries:
                raise
    return ""


def parse_listing(html):
    """Split the page into fiction cards and extract what we need."""
    fictions = []
    chunks = html.split('class="fiction-title"')
    for seg in chunks[1:]:
        m = re.search(r'href="(/fiction/\d+/[a-zA-Z0-9-]+)"[^>]*>([^<]+)</a>', seg)
        if not m:
            continue
        url, title = m.group(1), m.group(2).strip()
        tags = [t for t in re.findall(
            r'class="[^"]*fiction-tag"[^>]*>([^<]+)</a>', seg)][:8]
        followers = None
        fm = re.search(r'([\d,]+)\s*Followers', seg)
        if fm:
            followers = int(fm.group(1).replace(",", ""))
        ratings = None
        rm = re.search(r'([\d,]+)\s*Ratings', seg)
        if rm:
            ratings = int(rm.group(1).replace(",", ""))
        rating_avg = None
        am = re.search(r'Rating:\s*([\d.]+)\s*out of 5', seg)
        if am:
            rating_avg = am.group(1)
        fictions.append({
            "url": url, "title": title, "tags": tags,
            "followers": followers, "ratings": ratings,
            "rating_avg": rating_avg,
        })
    return fictions


def parse_fiction_page(html):
    """Extract author, rating count and dates from a fiction detail page.

    Royal Road embeds JSON-LD structured data — the most reliable source:
      "ratingCount":17576,"author":{"@type":"Person","name":"nobody103"},
      "datePublished":"2018-10-28T21:34:43+00:00"
    The author's profile link comes from the HTML.
    """
    out = {"profile_id": None, "name": None, "profile_url": "",
           "ratings": None, "date_published": ""}
    m = re.search(r'"ratingCount":\s*(\d+)', html)
    if m:
        out["ratings"] = int(m.group(1))
    m = re.search(r'"author":\s*\{[^{}]*"name":\s*"([^"]+)"', html)
    if m:
        out["name"] = m.group(1)
    m = re.search(r'"datePublished":\s*"(\d{4}-\d{2}-\d{2})', html)
    if m:
        out["date_published"] = m.group(1)
    m = re.search(
        r'<a\s+href="/profile/(\d+)"[^>]*>\s*([^<]{2,60}?)\s*</a>', html)
    if m:
        out["profile_id"] = m.group(1)
        out["profile_url"] = f"{BASE}/profile/{m.group(1)}"
        if not out["name"]:
            out["name"] = m.group(2).strip()
    if not out["name"] and not out["profile_id"]:
        return None
    return out


def crawl(cfg, emit, conn):
    scfg = cfg["sources"].get("royalroad", {})
    max_fictions = scfg.get("max_fictions", 12)
    genre_kw = cfg["scoring"]["genre_specific"] + cfg["scoring"]["genre_broad"]
    touched = []

    pool = []
    for listing in scfg.get("listings", ["rising-stars", "latest-updates"]):
        path = LISTINGS.get(listing)
        if not path:
            continue
        try:
            html = _get(path)
        except Exception as e:
            emit("log", f"  ! listing '{listing}' failed: {e}")
            continue
        fics = parse_listing(html)
        emit("log", f"  ✔ {listing}: {len(fics)} fictions found")
        for f in fics:
            f["listing"] = listing
        pool.extend(fics)
        time.sleep(1.2)
        if len(pool) >= max_fictions * 3:
            break

    # prefer fiction with few ratings (our target: not-yet-popular authors)
    pool.sort(key=lambda f: (f["ratings"] is None, f["ratings"] or 0))
    seen_titles = set()
    done = 0
    for f in pool:
        if done >= max_fictions:
            break
        text = f["title"] + " " + " ".join(f["tags"])
        if not scoring.matches(text.lower(), genre_kw):
            continue
        if db.norm_title(f["title"]) in seen_titles:
            continue
        seen_titles.add(db.norm_title(f["title"]))
        try:
            page = _get(f["url"])
        except Exception as e:
            emit("log", f"  ! fiction page failed: {e}")
            continue
        author = parse_fiction_page(page) if page else None
        if not author or not author.get("name"):
            continue
        ratings = author.get("ratings") or f["ratings"]
        profile_url = author.get("profile_url") or (BASE + f["url"])
        pid = author.get("profile_id") or re.sub(r"\D", "", f["url"]) or "0"
        handle = f"{re.sub(r'[^a-z0-9]+', '-', author['name'].lower()).strip('-')}-{pid}"
        bio = (f"Royal Road author of {f['title']}. Tags: "
               + ", ".join(f["tags"]))
        author_id, ident_id, is_new = db.upsert_identity(
            conn, "royalroad", handle, profile_url,
            author["name"], bio, f["listing"])
        popularity = []
        if f["followers"] is not None:
            popularity.append(f"{f['followers']:,} followers")
        if f["rating_avg"]:
            popularity.append(f"rating {f['rating_avg']}/5")
        db.upsert_book(
            conn, author_id, f["title"], "royalroad",
            book_url=BASE + f["url"],
            genre=", ".join(f["tags"][:4]),
            ratings_count=ratings,
            popularity=" · ".join(popularity),
            pub_date=author.get("date_published", ""))
        db.add_signal(conn, author_id, "discovered",
                      f"royalroad:{f['listing']}", f["title"])
        emit("author", (author_id, is_new))
        emit("log", f"  + {author['name']} — “{f['title']}” "
                    f"({ratings if ratings is not None else '?'} ratings)")
        touched.append(author_id)
        done += 1
        conn.commit()
        time.sleep(1.5)
    emit("log", f"  ✔ Royal Road: {done} authors profiled")
    return {"touched": touched}
