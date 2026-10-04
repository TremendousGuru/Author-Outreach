"""Bluesky source — public API (public.api.bsky.app), no credentials."""
import time

import requests

from pipeline import db, scoring

API = "https://public.api.bsky.app/xrpc"
HEADERS = {"User-Agent": "author-outreach-mvp/0.1 (indie author research)"}


def _get(endpoint, params, retries=2):
    for attempt in range(retries + 1):
        r = requests.get(f"{API}/{endpoint}", params=params, headers=HEADERS,
                         timeout=25)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429 and attempt < retries:
            time.sleep(3 * (attempt + 1))
            continue
        r.raise_for_status()
    return {}


def search_actors(query, limit=25):
    out, cursor = [], None
    while len(out) < limit:
        params = {"q": query, "limit": min(25, limit - len(out))}
        if cursor:
            params["cursor"] = cursor
        d = _get("app.bsky.actor.searchActors", params)
        actors = d.get("actors", [])
        out += actors
        cursor = d.get("cursor")
        if not cursor or not actors:
            break
        time.sleep(0.4)
    return out[:limit]


def author_feed(handle, limit=25):
    d = _get("app.bsky.feed.getAuthorFeed",
             {"actor": handle, "limit": min(100, limit)})
    posts = []
    for item in d.get("feed", []):
        try:
            post = item["post"]
            rec = post["record"]
            rkey = post["uri"].split("/")[-1]
            posts.append({
                "post_url": f"https://bsky.app/profile/{handle}/post/{rkey}",
                "posted_at": rec.get("createdAt", ""),
                "text": rec.get("text", ""),
            })
        except (KeyError, TypeError):
            continue
    return posts


def crawl(cfg, emit, conn):
    scfg = cfg["sources"]["bluesky"]
    found = {}
    for q in scfg.get("queries", []):
        try:
            actors = search_actors(q, scfg.get("actors_per_query", 25))
        except Exception as e:
            emit("log", f"  ! query '{q}' failed: {e}")
            continue
        kept = 0
        for a in actors:
            handle = a.get("handle")
            if not handle:
                continue
            name = a.get("displayName") or handle
            bio = a.get("description") or ""
            text = f"{name} {bio}"
            if scoring.matches(text, cfg["scoring"]["exclude_keywords"]):
                continue
            if not scoring.is_prospect(text, cfg):
                continue
            url = f"https://bsky.app/profile/{handle}"
            author_id, ident_id, is_new = db.upsert_identity(
                conn, "bluesky", handle, url, name, bio, q)
            db.add_signal(conn, author_id, "discovered", f"bluesky:{q}", name)
            emit("author", (author_id, is_new))
            found[author_id] = (is_new, ident_id, handle)
            kept += 1
        emit("log", f"  ✔ '{q}': {len(actors)} scanned, {kept} author prospects")
        conn.commit()
        time.sleep(0.5)

    # activity pass — recent posts for the hottest NEW authors
    top_n = scfg.get("check_activity_for_top", 30)
    scored = []
    for author_id, (is_new, ident_id, handle) in found.items():
        prelim = scoring.analyze(db.get_author_text(conn, author_id), None, cfg)
        scored.append((prelim["score"], is_new, author_id, ident_id, handle))
    scored.sort(key=lambda x: (-x[1], -x[0]))
    checked = 0
    for score, is_new, author_id, ident_id, handle in scored:
        if checked >= top_n:
            break
        try:
            posts = author_feed(handle, 25)
        except Exception:
            continue
        if posts:
            db.replace_posts(conn, ident_id, "bluesky", posts)
            checked += 1
        time.sleep(0.4)
    conn.commit()
    emit("log", f"  ✔ activity check (recent posts) for {checked} authors")
    return {"touched": list(found.keys())}
