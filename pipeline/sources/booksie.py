"""Booksie source — writing community where members post novels, stories
and poems. The newest postings are listed (newest-first) in the highest
content sub-sitemap, and every posting URL contains the author's username.
"""
import html
import re
import time
import xml.etree.ElementTree as ET

import requests

from pipeline import db, scoring

BASE = "https://www.booksie.com"
SM_INDEX = f"{BASE}/sitemap-content-all.xml"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# strong genre words in the URL slug — filters out the flood of love-poems
SLUG_HINTS = ["romance", "romantic", "fantasy", "fae", "fairy", "dragon",
              "vampire", "magic", "magik", "paranormal", "witch", "wizard",
              "shifter", "fated", "wolf", "werewolf", "elf", "dwarf",
              "kingdom", "realm", "sorcer", "necro", "paladin", "huntress"]


def _get(url, timeout=25):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.text


def genre_posting_urls(limit):
    """Return newest posting URLs whose slug hints at romance/fantasy."""
    idx = _get(SM_INDEX)
    subs = re.findall(r"<loc>(https://www\.booksie\.com/sitemap-content-\d+\.xml)</loc>", idx)
    if not subs:
        raise RuntimeError("no content sitemaps found")
    subs.sort(key=lambda u: int(re.search(r"(\d+)\.xml", u).group(1)))
    urls = []
    for sm in reversed(subs[-2:]):          # newest two sub-sitemaps
        xml = _get(sm)
        found = re.findall(r"<loc>(https://www\.booksie\.com/posting/[^<]+)</loc>", xml)
        urls += [u for u in found
                 if any(h in u.rsplit("/", 1)[-1].lower() for h in SLUG_HINTS)]
        urls = list(dict.fromkeys(urls))
        if len(urls) >= limit * 6:
            break
    return urls[:limit * 6]


def parse_posting(page, url):
    title = ""
    m = re.search(r"<title>([^<]+)</title>", page)
    if m:
        raw = html.unescape(m.group(1))
        # format: "Celebration Dance, poem by leesah"
        pm = re.match(r"^(.*?),\s*(poem|story|novel|chapter|prose|essay)s?\s+by\s+(.+)$", raw)
        if pm:
            title, ctype, username = pm.group(1).strip(), pm.group(2), pm.group(3).strip()
        else:
            title, ctype, username = raw.strip(), "", ""
    else:
        ctype, username = "", ""

    if not username:
        m = re.search(r"/posting/([a-zA-Z0-9_-]+)/", url)
        username = m.group(1) if m else ""

    portfolio = ""
    m = re.search(r'href="(https://www\.booksie\.com/portfolio-view/[^"]+)"', page)
    if m:
        portfolio = m.group(1)

    def count(label):
        m = re.search(label + r":\s*</span>\s*(?:<[^>]*>\s*)?([\d,]+)", page)
        if not m:
            m = re.search(label + r":\s*([\d,]+)", page)
        return int(m.group(1).replace(",", "")) if m else None

    reads = count("Reads")
    likes = count("Likes")
    comments = count("Comments")

    desc = ""
    m = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', page)
    if m:
        desc = m.group(1)[:300]

    return {
        "title": title or (url.rsplit("/", 1)[-1] or "untitled"),
        "content_type": ctype,
        "username": username,
        "portfolio": portfolio,
        "reads": reads, "likes": likes, "comments": comments,
        "description": desc, "url": url,
    }


def crawl(cfg, emit, conn):
    scfg = cfg["sources"].get("booksie", {})
    max_postings = scfg.get("max_postings", 12)
    touched = []
    try:
        urls = genre_posting_urls(max_postings)
    except Exception as e:
        emit("log", f"  ! sitemap failed: {e}")
        return {"touched": touched}
    emit("log", f"  ✔ sitemap ok — {len(urls)} genre-hinted postings available")

    done = 0
    for url in urls:
        if done >= max_postings:
            break
        try:
            p = parse_posting(_get(url), url)
        except Exception as e:
            emit("log", f"  ! posting failed: {e}")
            continue
        text = " ".join(filter(None, [p["title"], p["content_type"],
                                      p["description"]]))
        low = text.lower()
        genre_hit = (scoring.matches(low, cfg["scoring"]["genre_specific"])
                     or scoring.matches(low, cfg["scoring"]["genre_broad"]))
        is_fiction = p["content_type"] in ("novel", "chapter", "story")
        if not (genre_hit or is_fiction):
            continue  # keep genre fiction, skip poems/essays without genre words
        if scoring.matches(text.lower(), cfg["scoring"]["exclude_keywords"]):
            continue
        if not p["username"]:
            continue
        platform_url = p["portfolio"] or f"{BASE}/portfolio-view/{p['username']}"
        bio = f"Booksie writer — {p['content_type'] or 'posting'}: “{p['title']}”. {p['description']}"[:400]
        author_id, ident_id, is_new = db.upsert_identity(
            conn, "booksie", p["username"], platform_url,
            p["username"], bio, "sitemap:newest")
        pop = []
        if p["reads"] is not None:
            pop.append(f"{p['reads']:,} reads")
        if p["likes"] is not None:
            pop.append(f"{p['likes']:,} likes")
        db.upsert_book(
            conn, author_id, p["title"], "booksie", book_url=p["url"],
            genre=p["content_type"], ratings_count=p["comments"],
            popularity=" · ".join(pop))
        db.add_signal(conn, author_id, "discovered", "booksie:newest",
                      p["title"])
        db.replace_posts(conn, ident_id, "booksie", [{
            "post_url": p["url"], "posted_at": db.now_iso(),
            "text": f"Posted “{p['title']}” ({p['content_type'] or 'writing'}) on Booksie. {p['description']}",
        }])
        emit("author", (author_id, is_new))
        emit("log", f"  + {p['username']} — “{p['title']}” "
                    f"({p['reads'] if p['reads'] is not None else '?'} reads)")
        touched.append(author_id)
        done += 1
        conn.commit()
        time.sleep(1.2)
    emit("log", f"  ✔ Booksie: {done} authors profiled")
    return {"touched": touched}
