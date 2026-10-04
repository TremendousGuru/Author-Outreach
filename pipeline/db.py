"""SQLite storage: authors, per-platform identities, books, posts, signals,
gaps, suggested matches, crawl runs — everything source-tagged.

Cross-platform dedup happens here:
- same platform+handle seen again  -> spotted_count + 1, last_seen updated
- same normalized handle elsewhere -> merged into the same author
- same pen name on two platforms   -> queued as a *suggested* match (matching.py)
"""
import datetime
import os
import re
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "prospects.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS authors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  display_name TEXT DEFAULT '',
  heat_score INTEGER DEFAULT 0,
  status TEXT DEFAULT 'new',
  suggested_angle TEXT DEFAULT '',
  last_post_days REAL,
  posts_per_month REAL,
  notes TEXT DEFAULT '',
  first_seen TEXT,
  last_seen TEXT
);
CREATE TABLE IF NOT EXISTS identities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author_id INTEGER NOT NULL REFERENCES authors(id),
  platform TEXT NOT NULL,
  handle TEXT NOT NULL,
  norm TEXT NOT NULL,
  platform_url TEXT DEFAULT '',
  display_name TEXT DEFAULT '',
  bio TEXT DEFAULT '',
  discovered_query TEXT DEFAULT '',
  spotted_count INTEGER DEFAULT 1,
  first_seen TEXT,
  last_seen TEXT,
  UNIQUE(platform, handle)
);
CREATE INDEX IF NOT EXISTS idx_ident_norm ON identities(norm);
CREATE INDEX IF NOT EXISTS idx_ident_author ON identities(author_id);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id INTEGER NOT NULL REFERENCES authors(id),
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    source_url TEXT DEFAULT '',
    source_platform TEXT DEFAULT '',
    first_seen TEXT,
    last_seen TEXT,
    UNIQUE(author_id, kind, value)
);
CREATE INDEX IF NOT EXISTS idx_contacts_author ON contacts(author_id);
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author_id INTEGER REFERENCES authors(id),
  signal TEXT,
  source TEXT,
  detail TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  identity_id INTEGER REFERENCES identities(id),
  platform TEXT,
  post_url TEXT,
  posted_at TEXT,
  text TEXT,
  UNIQUE(post_url)
);
CREATE TABLE IF NOT EXISTS gaps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author_id INTEGER REFERENCES authors(id),
  gap TEXT,
  created_at TEXT,
  UNIQUE(author_id, gap)
);
CREATE TABLE IF NOT EXISTS books (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author_id INTEGER NOT NULL REFERENCES authors(id),
  title TEXT NOT NULL,
  norm_title TEXT NOT NULL,
  platform TEXT NOT NULL,
  book_url TEXT DEFAULT '',
  genre TEXT DEFAULT '',
  price TEXT DEFAULT '',
  ratings_count INTEGER,
  popularity TEXT DEFAULT '',
  pub_date TEXT DEFAULT '',
  amazon_reviews INTEGER,
  goodreads_ratings INTEGER,
  manual_checked_at TEXT,
  first_seen TEXT,
  last_seen TEXT
);
CREATE INDEX IF NOT EXISTS idx_books_author ON books(author_id);
CREATE TABLE IF NOT EXISTS suggested_matches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author_a INTEGER NOT NULL,
  author_b INTEGER NOT NULL,
  reason TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',
  created_at TEXT,
  UNIQUE(author_a, author_b)
);
CREATE TABLE IF NOT EXISTS crawl_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT,
  started_at TEXT,
  finished_at TEXT,
  new_authors INTEGER DEFAULT 0,
  updated_authors INTEGER DEFAULT 0,
  status TEXT DEFAULT 'running',
  note TEXT DEFAULT ''
);
"""


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _ensure_column(conn, table, column, decl):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.executescript(SCHEMA)
    # migrations for databases created before these columns existed
    _ensure_column(conn, "authors", "notes", "TEXT DEFAULT ''")
    return conn


def normalize_handle(handle: str) -> str:
    h = (handle or "").lower().strip().lstrip("@")
    if h.startswith("u/"):
        h = h[2:]
    if h.endswith(".bsky.social"):
        h = h[: -len(".bsky.social")]
    return h


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def upsert_identity(conn, platform, handle, platform_url, display_name, bio,
                    discovered_query):
    row = conn.execute(
        "SELECT id, author_id FROM identities WHERE platform=? AND norm=?",
        (platform, normalize_handle(handle))).fetchone()
    n = now_iso()
    if row:
        conn.execute(
            """UPDATE identities SET spotted_count=spotted_count+1, last_seen=?,
               bio=CASE WHEN length(bio) < length(?) THEN ? ELSE bio END,
               platform_url=? WHERE id=?""",
            (n, bio or "", bio or "", platform_url, row["id"]))
        conn.execute("UPDATE authors SET last_seen=? WHERE id=?",
                     (n, row["author_id"]))
        return row["author_id"], row["id"], False

    other = conn.execute("SELECT author_id FROM identities WHERE norm=? LIMIT 1",
                         (normalize_handle(handle),)).fetchone()
    if other:
        author_id = other["author_id"]
    else:
        cur = conn.execute(
            "INSERT INTO authors(display_name, first_seen, last_seen) VALUES (?,?,?)",
            (display_name or handle, n, n))
        author_id = cur.lastrowid

    cur = conn.execute(
        """INSERT INTO identities(author_id, platform, handle, norm, platform_url,
           display_name, bio, discovered_query, first_seen, last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (author_id, platform, handle, normalize_handle(handle), platform_url,
         display_name or "", bio or "", discovered_query, n, n))
    return author_id, cur.lastrowid, True


def upsert_book(conn, author_id, title, platform, book_url="", genre="",
                price="", ratings_count=None, popularity="", pub_date=""):
    nt = norm_title(title)
    if not nt:
        return None
    n = now_iso()
    row = conn.execute(
        "SELECT id FROM books WHERE author_id=? AND platform=? AND norm_title=?",
        (author_id, platform, nt)).fetchone()
    if row:
        conn.execute(
            """UPDATE books SET book_url=?, genre=CASE WHEN ?<>'' THEN ? ELSE genre END,
               price=CASE WHEN ?<>'' THEN ? ELSE price END,
               ratings_count=COALESCE(?, ratings_count),
               popularity=CASE WHEN ?<>'' THEN ? ELSE popularity END,
               pub_date=CASE WHEN ?<>'' THEN ? ELSE pub_date END, last_seen=? WHERE id=?""",
            (book_url, genre, genre, price, price, ratings_count,
             popularity, popularity, pub_date, pub_date, n, row["id"]))
        return row["id"]
    cur = conn.execute(
        """INSERT INTO books(author_id, title, norm_title, platform, book_url, genre,
           price, ratings_count, popularity, pub_date, first_seen, last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (author_id, title, nt, platform, book_url, genre, price, ratings_count,
         popularity, pub_date, n, n))
    return cur.lastrowid


def get_books(conn, author_id):
    return conn.execute(
        "SELECT * FROM books WHERE author_id=? ORDER BY last_seen DESC",
        (author_id,)).fetchall()


def upsert_contact(conn, author_id, kind, value, source_url="",
                   source_platform=""):
    value = (value or "").strip()
    if not value:
        return False
    n = now_iso()
    row = conn.execute(
        "SELECT id FROM contacts WHERE author_id=? AND kind=? AND value=?",
        (author_id, kind, value)).fetchone()
    if row:
        conn.execute(
            """UPDATE contacts SET source_url=CASE WHEN ?<>'' THEN ? ELSE source_url END,
               source_platform=CASE WHEN ?<>'' THEN ? ELSE source_platform END,
               last_seen=? WHERE id=?""",
            (source_url, source_url, source_platform, source_platform, n, row["id"]))
        return False
    conn.execute(
        """INSERT INTO contacts(author_id, kind, value, source_url, source_platform,
           first_seen, last_seen) VALUES (?,?,?,?,?,?,?)""",
        (author_id, kind, value, source_url, source_platform, n, n))
    return True


def get_contacts(conn, author_id):
    return conn.execute(
        """SELECT * FROM contacts WHERE author_id=?
           ORDER BY CASE kind WHEN 'email' THEN 0 WHEN 'website' THEN 1 ELSE 2 END,
           value""", (author_id,)).fetchall()


def update_book_manual(conn, book_id, amazon_reviews=None, goodreads_ratings=None):
    conn.execute(
        """UPDATE books SET amazon_reviews=?, goodreads_ratings=?, manual_checked_at=?
           WHERE id=?""",
        (amazon_reviews, goodreads_ratings, now_iso(), book_id))


def add_signal(conn, author_id, signal, source, detail=""):
    conn.execute(
        "INSERT INTO signals(author_id, signal, source, detail, created_at) VALUES (?,?,?,?,?)",
        (author_id, signal, source, str(detail)[:500], now_iso()))


def replace_posts(conn, identity_id, platform, posts):
    for p in posts or []:
        if not p.get("post_url"):
            continue
        conn.execute(
            "INSERT OR IGNORE INTO posts(identity_id, platform, post_url, posted_at, text) VALUES (?,?,?,?,?)",
            (identity_id, platform, p["post_url"], p.get("posted_at", ""),
             (p.get("text") or "")[:2000]))


def get_author_text(conn, author_id):
    rows = conn.execute(
        "SELECT display_name, bio FROM identities WHERE author_id=?",
        (author_id,)).fetchall()
    bks = conn.execute(
        "SELECT title, genre FROM books WHERE author_id=?", (author_id,)).fetchall()
    return " ".join(filter(None,
                           [r["display_name"] for r in rows] +
                           [r["bio"] for r in rows] +
                           [f"{b['title']} {b['genre'] or ''}" for b in bks]))


def get_posts(conn, author_id):
    rows = conn.execute(
        """SELECT p.posted_at, p.text, p.post_url, p.platform FROM posts p
           JOIN identities i ON p.identity_id = i.id
           WHERE i.author_id=? ORDER BY p.posted_at DESC""",
        (author_id,)).fetchall()
    return [dict(r) for r in rows]


def save_analysis(conn, author_id, analysis):
    conn.execute(
        """UPDATE authors SET heat_score=?, suggested_angle=?, last_post_days=?,
           posts_per_month=? WHERE id=?""",
        (analysis["score"], analysis["angle"],
         analysis.get("last_post_days"), analysis.get("posts_per_month"),
         author_id))
    conn.execute("DELETE FROM gaps WHERE author_id=?", (author_id,))
    for g in analysis["gaps"]:
        conn.execute("INSERT OR IGNORE INTO gaps(author_id, gap, created_at) VALUES (?,?,?)",
                     (author_id, g, now_iso()))


def set_author_fields(conn, author_id, status=None, notes=None):
    if status is not None and status in (
            "new", "reviewing", "messaged", "replied", "won", "lost", "skip"):
        conn.execute("UPDATE authors SET status=? WHERE id=?", (status, author_id))
    if notes is not None:
        conn.execute("UPDATE authors SET notes=? WHERE id=?", (notes, author_id))


def merge_authors(conn, keep_id, merge_id):
    """Move everything from merge_id into keep_id, then delete merge_id."""
    if keep_id == merge_id:
        return keep_id
    # books: avoid duplicates on (norm_title, platform)
    for b in conn.execute("SELECT * FROM books WHERE author_id=?",
                          (merge_id,)).fetchall():
        dup = conn.execute(
            "SELECT id FROM books WHERE author_id=? AND norm_title=? AND platform=?",
            (keep_id, b["norm_title"], b["platform"])).fetchone()
        if dup:
            conn.execute("DELETE FROM books WHERE id=?", (b["id"],))
        else:
            conn.execute("UPDATE books SET author_id=? WHERE id=?",
                         (keep_id, b["id"]))
    conn.execute("UPDATE identities SET author_id=? WHERE author_id=?",
                 (keep_id, merge_id))
    for contact in conn.execute("SELECT * FROM contacts WHERE author_id=?",
                                (merge_id,)).fetchall():
        conn.execute(
            """INSERT OR IGNORE INTO contacts(author_id, kind, value, source_url,
               source_platform, first_seen, last_seen) VALUES (?,?,?,?,?,?,?)""",
            (keep_id, contact["kind"], contact["value"], contact["source_url"],
             contact["source_platform"], contact["first_seen"], contact["last_seen"]))
    conn.execute("DELETE FROM contacts WHERE author_id=?", (merge_id,))
    conn.execute("UPDATE signals SET author_id=? WHERE author_id=?",
                 (keep_id, merge_id))
    conn.execute("DELETE FROM gaps WHERE author_id=?", (merge_id,))
    conn.execute("DELETE FROM suggested_matches WHERE author_a=? OR author_b=?",
                 (merge_id, merge_id))
    # prefer a real display name
    if not (conn.execute("SELECT display_name FROM authors WHERE id=?",
                         (keep_id,)).fetchone() or {"display_name": ""})["display_name"]:
        conn.execute(
            "UPDATE authors SET display_name=(SELECT display_name FROM authors WHERE id=?) WHERE id=?",
            (merge_id, keep_id))
    conn.execute("DELETE FROM authors WHERE id=?", (merge_id,))
    return keep_id
