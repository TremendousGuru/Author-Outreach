"""Cross-platform suggested matches (Phase C).

Rule agreed in the scope:
- same handle on two platforms  -> merged automatically (db.upsert_identity)
- same pen name on two platforms -> SUGGESTED match, confirmed by a human.
  A suggestion is strengthened when both authors share a book title.

Never merged blindly: everything here goes to the Matches page for
confirm / reject.
"""
import itertools

from pipeline import db


def norm_name(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def scan(conn, max_new=100):
    """Find same-name authors across different platforms -> pending matches."""
    authors = {}
    for ident in conn.execute(
            "SELECT author_id, platform, display_name, handle FROM identities").fetchall():
        a = authors.setdefault(ident["author_id"], {"names": set(), "titles": set()})
        nm = norm_name(ident["display_name"]) or norm_name(ident["handle"])
        if nm:
            a["names"].add(nm)
    for b in conn.execute("SELECT author_id, norm_title FROM books").fetchall():
        if b["norm_title"]:
            authors.setdefault(b["author_id"], {"names": set(), "titles": set()})["titles"].add(b["norm_title"])

    by_name = {}
    for aid, data in authors.items():
        for nm in data["names"]:
            by_name.setdefault(nm, set()).add(aid)

    added = 0
    for nm, ids in by_name.items():
        if len(ids) < 2:
            continue
        for a, b in itertools.combinations(sorted(ids), 2):
            existing = conn.execute(
                "SELECT id FROM suggested_matches WHERE (author_a=? AND author_b=?)",
                (a, b)).fetchone()
            if existing:
                continue
            shared = authors[a]["titles"] & authors[b]["titles"]
            if shared:
                reason = (f"Same pen name '{nm}' + same book title "
                          f"'{list(shared)[0][:60]}' on two platforms")
            elif not authors[a]["titles"] or not authors[b]["titles"]:
                reason = (f"Same pen name '{nm}' on two platforms "
                          f"(no conflicting book data)")
            else:
                continue  # same name but different books -> probably 2 people
            conn.execute(
                "INSERT OR IGNORE INTO suggested_matches(author_a, author_b, reason, status, created_at) VALUES (?,?,?,'pending',?)",
                (a, b, reason, db.now_iso()))
            added += 1
            if added >= max_new:
                conn.commit()
                return added
    conn.commit()
    return added


def pending(conn):
    rows = conn.execute(
        """SELECT m.*, a.display_name AS name_a, b.display_name AS name_b
           FROM suggested_matches m
           JOIN authors a ON m.author_a = a.id
           JOIN authors b ON m.author_b = b.id
           WHERE m.status='pending' ORDER BY m.created_at DESC""").fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "author_a": r["author_a"], "author_b": r["author_b"],
            "name_a": r["name_a"], "name_b": r["name_b"], "reason": r["reason"],
        })
    return out


def confirm(conn, match_id):
    m = conn.execute("SELECT * FROM suggested_matches WHERE id=?", (match_id,)).fetchone()
    if not m or m["status"] != "pending":
        return None
    keep = db.merge_authors(conn, m["author_a"], m["author_b"])
    conn.execute("UPDATE suggested_matches SET status='confirmed' WHERE id=?",
                 (match_id,))
    conn.commit()
    return keep


def reject(conn, match_id):
    conn.execute("UPDATE suggested_matches SET status='rejected' WHERE id=?",
                 (match_id,))
    conn.commit()
