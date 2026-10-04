"""My Book Cave source — book promo/deals site (WordPress).

Structure (verified):
  /sitemap.xml            -> index incl. wp-sitemap-posts-rated-book-N.xml
  rated-book sub-sitemaps -> every promo-listed book /book/{slug}/
  book pages              -> og:book:tag metas: author, series, genre,
                             content rating, retailer; plus /profile/ links.
"""
import html
import re
import time
import urllib.parse

import requests

from pipeline import db, scoring

BASE = "https://mybookcave.com"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

GENRE_HINTS = ("romance", "fantasy", "paranormal", "mystery", "thriller",
               "science fiction", "scifi", "historical", "young adult",
               "horror", "contemporary")
RETAILERS = ("kindle", "amazon", "kobo", "apple", "barnes", "nook", "google",
             "smashwords", "audible", "audiobook")
RATINGS = ("mild", "moderate", "hot", "steamy", "all-ages", "older teen",
           "mature")


def _get(url):
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    return r.text


def book_urls_from_sitemap(max_books):
    """Newest rated-book URLs (with lastmod dates) from the sitemap index."""
    idx = _get(f"{BASE}/sitemap.xml")
    subs = re.findall(
        r"<loc>(https://mybookcave\.com/wp-sitemap-posts-rated-book-\d+\.xml)</loc>", idx)
    if not subs:
        raise RuntimeError("no rated-book sitemaps found")
    subs.sort(key=lambda u: int(re.search(r"(\d+)\.xml", u).group(1)))
    # last sub-sitemap = newest books
    newest = _get(subs[-1])
    entries = re.findall(
        r"<loc>(https://mybookcave\.com/(?:mybookratings/)?rated-book/[^<]+)</loc>"
        r"(?:<lastmod>([^<]+)</lastmod>)?", newest)
    out = [{"url": u, "lastmod": (lm or "")[:10]} for u, lm in entries]
    return out[:max_books * 4]


def parse_book_page(page, url):
    title = ""
    m = re.search(r'property="og:title"\s+content="([^"]+)"', page)
    if m:
        title = re.sub(r"\s*[–-]\s*Book Cave\s*$", "",
                       html.unescape(m.group(1))).strip()

    tags = [html.unescape(t) for t in re.findall(
        r'property="og:book:tag"\s+content="([^"]+)"', page)]
    author, retailer, rating = "", "", ""
    genres = []
    for t in tags:
        tl = t.lower()
        if not author and not any(h in tl for h in GENRE_HINTS + RETAILERS + RATINGS):
            author = t          # first tag that isn't genre/retailer/rating
        elif any(h in tl for h in GENRE_HINTS):
            genres.append(t)
        elif any(h in tl for h in RETAILERS) and not retailer:
            retailer = t
        elif any(h in tl for h in RATINGS) and not rating:
            rating = t

    profile = ""
    m = re.search(r'href="(https://mybookcave\.com/profile/[a-z0-9-]+/)"', page)
    if m:
        profile = m.group(1)

    desc = ""
    m = re.search(r'property="og:description"\s+content="([^"]*)"', page)
    if m:
        desc = m.group(1)[:300]

    return {"title": title, "author": author,
            "genre": " | ".join(dict.fromkeys(genres))[:120],
            "retailer": retailer, "rating": rating, "profile": profile,
            "description": desc, "url": url}


def crawl(cfg, emit, conn):
    scfg = cfg["sources"].get("mybookcave", {})
    max_books = scfg.get("max_books", 12)
    touched = []
    try:
        urls = book_urls_from_sitemap(max_books)
    except Exception as e:
        emit("log", f"  ! sitemap failed: {e}")
        return {"touched": touched}
    emit("log", f"  ✔ sitemap ok — {len(urls)} newest promo books available")

    genre_kw = cfg["scoring"]["genre_specific"] + cfg["scoring"]["genre_broad"]
    done = 0
    for entry in urls:
        if done >= max_books:
            break
        url = entry["url"]
        try:
            b = parse_book_page(_get(url), url)
        except Exception as e:
            emit("log", f"  ! book page failed: {e}")
            continue
        text = " ".join(filter(None, [b["title"], b["genre"], b["description"]]))
        if not scoring.matches(text.lower(), genre_kw):
            continue  # keep only romance/fantasy-adjacent books
        if scoring.matches(text.lower(), cfg["scoring"]["exclude_keywords"]):
            continue
        if not b["author"] or not b["title"]:
            continue
        slug = (b["profile"].rstrip("/").split("/")[-1]
                if b["profile"]
                else re.sub(r"[^a-z0-9]+", "-", b["author"].lower()).strip("-"))
        platform_url = b["profile"] or (
            f"{BASE}/?s=" + urllib.parse.quote_plus(b["author"]))
        bio = (f"My Book Cave listed author — “{b['title']}”"
               + (f" ({b['genre']})" if b["genre"] else "")
               + f". {b['description']}")[:400]
        author_id, ident_id, is_new = db.upsert_identity(
            conn, "mybookcave", slug, platform_url, b["author"], bio,
            "sitemap:newest")
        pop = " · ".join(x for x in [b["rating"], b["retailer"]] if x)
        db.upsert_book(conn, author_id, b["title"], "mybookcave",
                       book_url=b["url"], genre=b["genre"], popularity=pop,
                       pub_date=entry.get("lastmod", ""))
        db.add_signal(conn, author_id, "discovered", "mybookcave:newest",
                      b["title"])
        emit("author", (author_id, is_new))
        emit("log", f"  + {b['author']} — “{b['title']}”"
                    + (f" [{b['genre']}]" if b["genre"] else ""))
        touched.append(author_id)
        done += 1
        conn.commit()
        time.sleep(1.2)
    emit("log", f"  ✔ My Book Cave: {done} authors profiled")
    return {"touched": touched}
