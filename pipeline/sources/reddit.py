"""Reddit source — public RSS mode (no login), optional OAuth upgrade."""
import datetime
import html
import os
import re
import time
import xml.etree.ElementTree as ET

import requests

from pipeline import db, scoring

NS = {"a": "http://www.w3.org/2005/Atom"}
UA = {"User-Agent": "Mozilla/5.0 (compatible; author-outreach-mvp/0.1; research)"}


def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), ".env")
    creds = {}
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip()
    return creds


def _oauth_token(creds):
    r = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(creds["REDDIT_CLIENT_ID"], creds["REDDIT_CLIENT_SECRET"]),
        data={"grant_type": "password",
              "username": creds["REDDIT_USERNAME"],
              "password": creds["REDDIT_PASSWORD"]},
        headers=UA, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def _parse_rss(content, sub, lookback_days):
    root = ET.fromstring(content)
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=lookback_days))
    entries = []
    for e in root.findall("a:entry", NS):
        title = (e.findtext("a:title", "", NS) or "").strip()
        link_el = e.find("a:link", NS)
        link = link_el.get("href", "") if link_el is not None else ""
        updated = e.findtext("a:updated", "", NS) or ""
        author_el = e.find("a:author/a:name", NS)
        author = (author_el.text if author_el is not None else "") or ""
        author = re.sub(r"^/?u/", "", author).strip()
        content_html = e.findtext("a:content", "", NS) or ""
        content = html.unescape(re.sub(r"<[^>]+>", " ", content_html))
        content = re.sub(r"\s+", " ", content).strip()
        dt = None
        try:
            dt = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            pass
        if dt and dt < cutoff:
            continue
        entries.append({
            "sub": sub, "title": title, "url": link, "author": author,
            "posted_at": updated, "text": (title + " " + content)[:2000],
        })
    return entries


def fetch_subreddit(sub, limit=50, lookback_days=60, max_retries=3):
    url = f"https://www.reddit.com/r/{sub}/new/.rss?limit={min(100, limit)}"
    for attempt in range(max_retries):
        r = requests.get(url, headers=UA, timeout=25)
        if r.status_code == 200:
            return _parse_rss(r.content, sub, lookback_days)
        if r.status_code == 429 and attempt < max_retries - 1:
            time.sleep(20 * (attempt + 1))
            continue
        r.raise_for_status()
    raise RuntimeError(f"r/{sub}: rate-limited after {max_retries} tries")


def fetch_subreddit_oauth(sub, limit=100, token=None):
    hdr = dict(UA, Authorization=f"bearer {token}")
    r = requests.get(f"https://oauth.reddit.com/r/{sub}/new",
                     params={"limit": min(100, limit)}, headers=hdr, timeout=20)
    r.raise_for_status()
    entries = []
    for c in r.json().get("data", {}).get("children", []):
        d = c["data"]
        entries.append({
            "sub": sub,
            "title": d.get("title", ""),
            "url": "https://www.reddit.com" + d.get("permalink", ""),
            "author": d.get("author", ""),
            "posted_at": datetime.datetime.fromtimestamp(
                d.get("created_utc", 0), datetime.timezone.utc).isoformat(),
            "text": (d.get("title", "") + " " + (d.get("selftext") or ""))[:2000],
        })
    return entries


def fetch_subreddit_smart(sub, limit=50, lookback_days=60):
    creds = _load_env()
    if all(creds.get(k) for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
                                  "REDDIT_USERNAME", "REDDIT_PASSWORD")):
        try:
            token = _oauth_token(creds)
            return fetch_subreddit_oauth(sub, limit, token)
        except Exception:
            pass
    return fetch_subreddit(sub, limit, lookback_days)


def crawl(cfg, emit, conn):
    scfg = cfg["sources"]["reddit"]
    kw = cfg["scoring"]
    touched = []
    for sub in scfg.get("subreddits", []):
        try:
            entries = fetch_subreddit_smart(
                sub, scfg.get("posts_per_subreddit", 50),
                scfg.get("lookback_days", 60))
        except Exception as e:
            emit("log", f"  ! r/{sub} failed: {e}")
            continue
        kept = 0
        for e in entries:
            if not e["author"] or e["author"].lower() in (
                    "[deleted]", "automoderator", "moderator"):
                continue
            low = e["text"].lower()
            genre = (scoring.matches(low, kw["genre_specific"])
                     or scoring.matches(low, kw["genre_broad"]))
            writer = (scoring.matches(low, kw["author_keywords"])
                      or scoring.matches(low, kw["debut_keywords"])
                      or scoring.matches(low, kw["pain_keywords"]))
            if not (genre and writer):
                continue
            if scoring.matches(low, kw["exclude_keywords"]):
                continue
            url = f"https://www.reddit.com/user/{e['author']}"
            author_id, ident_id, is_new = db.upsert_identity(
                conn, "reddit", e["author"], url, e["author"],
                e["title"][:300], f"r/{e['sub']}")
            db.add_signal(conn, author_id, "reddit_post", f"r/{e['sub']}",
                          e["title"][:150])
            db.replace_posts(conn, ident_id, "reddit", [{
                "post_url": e["url"], "posted_at": e["posted_at"],
                "text": e["text"],
            }])
            emit("author", (author_id, is_new))
            touched.append(author_id)
            kept += 1
        emit("log", f"  ✔ r/{sub}: {len(entries)} posts scanned, {kept} author prospects")
        conn.commit()
        time.sleep(3)
    return {"touched": touched}
