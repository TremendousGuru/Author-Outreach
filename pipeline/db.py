"""SQLite storage: authors, per-platform identities, books, posts, signals,
gaps, suggested matches, crawl runs — everything source-tagged.

Cross-platform dedup happens here:
- same platform+handle seen again  -> spotted_count + 1, last_seen updated
- same normalized handle elsewhere -> merged into the same author
- same pen name on two platforms   -> queued as a *suggested* match (matching.py)

Multi-user support:
- users: login + approval state
- user_credentials: per-user source credentials (encrypted in production)
- every major record can optionally be scoped to a user_id
"""
import base64
import hashlib
import hmac
import datetime
import os
import re
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "prospects.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  email TEXT DEFAULT '',
  password_hash TEXT NOT NULL,
  full_name TEXT DEFAULT '',
  role TEXT NOT NULL DEFAULT 'user',
  status TEXT NOT NULL DEFAULT 'pending',
  approved_by TEXT DEFAULT '',
  approved_at TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_credentials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  platform TEXT NOT NULL,
  username TEXT DEFAULT '',
  password TEXT DEFAULT '',
  api_key TEXT DEFAULT '',
  token TEXT DEFAULT '',
  metadata TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(user_id, platform)
);
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  token TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS authors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER DEFAULT NULL REFERENCES users(id),
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
  user_id INTEGER DEFAULT NULL REFERENCES users(id),
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
    user_id INTEGER DEFAULT NULL REFERENCES users(id),
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
  user_id INTEGER DEFAULT NULL REFERENCES users(id),
  author_id INTEGER REFERENCES authors(id),
  signal TEXT,
  source TEXT,
  detail TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER DEFAULT NULL REFERENCES users(id),
  identity_id INTEGER REFERENCES identities(id),
  platform TEXT,
  post_url TEXT,
  posted_at TEXT,
  text TEXT,
  UNIQUE(post_url)
);
CREATE TABLE IF NOT EXISTS gaps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER DEFAULT NULL REFERENCES users(id),
  author_id INTEGER REFERENCES authors(id),
  gap TEXT,
  created_at TEXT,
  UNIQUE(author_id, gap)
);
CREATE TABLE IF NOT EXISTS books (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER DEFAULT NULL REFERENCES users(id),
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
  user_id INTEGER DEFAULT NULL REFERENCES users(id),
  author_a INTEGER NOT NULL,
  author_b INTEGER NOT NULL,
  reason TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',
  created_at TEXT,
  UNIQUE(author_a, author_b)
);
CREATE TABLE IF NOT EXISTS crawl_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER DEFAULT NULL REFERENCES users(id),
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
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    # migrations for databases created before these columns existed
    _ensure_column(conn, "authors", "notes", "TEXT DEFAULT ''")
    _ensure_column(conn, "users", "username", "TEXT DEFAULT ''")
    _ensure_column(conn, "users", "email", "TEXT DEFAULT ''")
    _ensure_column(conn, "users", "role", "TEXT DEFAULT 'user'")
    _ensure_column(conn, "users", "status", "TEXT DEFAULT 'pending'")
    _ensure_column(conn, "users", "approved_by", "TEXT DEFAULT ''")
    _ensure_column(conn, "users", "approved_at", "TEXT DEFAULT ''")
    _ensure_column(conn, "users", "created_at", "TEXT DEFAULT ''")
    _ensure_column(conn, "users", "updated_at", "TEXT DEFAULT ''")
    for table in ["authors", "identities", "contacts", "signals", "posts", "gaps", "books", "suggested_matches", "crawl_runs"]:
        _ensure_column(conn, table, "user_id", "INTEGER DEFAULT NULL")
    ensure_default_admin(conn)
    return conn


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, 310000)
    salt_text = base64.b64encode(salt).decode("ascii")
    digest_text = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256$310000${salt_text}${digest_text}"


def create_user(conn, email, password, username=None, full_name="", role="user", status="pending"):
    email = (email or "").strip().lower()
    username = (username or "").strip()
    if not username:
        username = (email or "").split("@", 1)[0].strip() or "user"
    if not password:
        raise ValueError("password is required")
    if conn.execute("SELECT 1 FROM users WHERE username=? OR email=?", (username, email)).fetchone():
        raise ValueError("user already exists")
    n = now_iso()
    cur = conn.execute(
        "INSERT INTO users(username, email, password_hash, full_name, role, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (username, email, _hash_password(password), full_name or "", role, status, n, n),
    )
    conn.commit()
    return conn.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()


def get_user_by_email(conn, email):
    return conn.execute("SELECT * FROM users WHERE email=?", ((email or "").strip().lower(),)).fetchone()


def get_user_by_username(conn, username):
    return conn.execute("SELECT * FROM users WHERE username=?", ((username or "").strip(),)).fetchone()


def get_user_by_login(conn, username_or_email):
    value = (username_or_email or "").strip()
    if not value:
        return None
    return conn.execute(
        "SELECT * FROM users WHERE username=? OR email=? LIMIT 1",
        (value, value.lower()),
    ).fetchone()


def verify_password(conn, user_id, password):
    row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        return False
    stored = row["password_hash"]
    if stored.startswith("pbkdf2_sha256$"):
        _, iterations, salt, expected = stored.split("$", 3)
        actual = hashlib.pbkdf2_hmac(
            "sha256", (password or "").encode("utf-8"),
            base64.b64decode(salt), int(iterations),
        )
        return hmac.compare_digest(base64.b64decode(expected), actual)
    if stored == hashlib.sha256((password or "").encode("utf-8")).hexdigest():
        conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                     (_hash_password(password), user_id))
        conn.commit()
        return True
    return False


def approve_user(conn, user_id, approved_by="admin"):
    conn.execute(
        "UPDATE users SET status='approved', approved_by=?, approved_at=?, updated_at=? WHERE id=?",
        (approved_by, now_iso(), now_iso(), user_id),
    )
    conn.commit()


def list_users(conn):
    return conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()


def create_session(conn, user_id, expires_hours=24):
    token = hashlib.sha256(f"{user_id}:{now_iso()}:{os.urandom(8)}".encode("utf-8")).hexdigest()
    expires_at = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=expires_hours)).isoformat(timespec="seconds")
    conn.execute("INSERT INTO sessions(user_id, token, created_at, expires_at) VALUES (?,?,?,?)",
                 (user_id, token, now_iso(), expires_at))
    conn.commit()
    return token


def get_session_user(conn, token):
    row = conn.execute("SELECT user_id FROM sessions WHERE token=? AND expires_at > ?", (token, now_iso())).fetchone()
    if not row:
        return None
    return conn.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()


def end_session(conn, token):
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()


def ensure_default_admin(conn):
    admin_username = os.environ.get("AUTHOR_OUTREACH_ADMIN_USERNAME", "Tremendous")
    admin = conn.execute(
        "SELECT * FROM users WHERE username=? LIMIT 1", (admin_username,)).fetchone()
    if not admin:
        password = os.environ.get("AUTHOR_OUTREACH_ADMIN_PASSWORD", "")
        if not password:
            return None
        admin = create_user(
            conn,
            email=os.environ.get("AUTHOR_OUTREACH_ADMIN_EMAIL",
                                 "admin@authoroutreach.local"),
            password=password,
            username=admin_username,
            full_name=admin_username,
            role="admin",
            status="approved",
        )
        conn.execute("UPDATE users SET approved_by='system', approved_at=? WHERE id=?",
                     (now_iso(), admin["id"]))
    if not admin:
        return None

    # Existing single-user records belong to the admin who owns this database.
    conn.execute("UPDATE authors SET user_id=? WHERE user_id IS NULL", (admin["id"],))
    for table in ("identities", "contacts", "signals", "gaps", "books"):
        conn.execute(
            f"""UPDATE {table} SET user_id=(
                    SELECT user_id FROM authors WHERE authors.id={table}.author_id)
                WHERE user_id IS NULL AND author_id IS NOT NULL"""
        )
    conn.execute(
        """UPDATE posts SET user_id=(
               SELECT authors.user_id FROM identities
               JOIN authors ON authors.id=identities.author_id
               WHERE identities.id=posts.identity_id)
           WHERE user_id IS NULL AND identity_id IS NOT NULL"""
    )
    conn.execute("UPDATE suggested_matches SET user_id=? WHERE user_id IS NULL",
                 (admin["id"],))
    conn.execute("UPDATE crawl_runs SET user_id=? WHERE user_id IS NULL",
                 (admin["id"],))
    conn.commit()
    return conn.execute("SELECT * FROM users WHERE id=?", (admin["id"],)).fetchone()


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


def get_leads(conn, user_id=None, search="", platform="Any", status="Any",
              include_all=False):
    if user_id is None and not include_all:
        return []
    sql = "SELECT a.* FROM authors a WHERE 1=1"
    args = []
    if not include_all:
        sql += " AND a.user_id=?"
        args.append(user_id)
    if search:
        sql += " AND LOWER(a.display_name) LIKE ?"
        args.append(f"%{search.lower()}%")
    if status != "Any":
        sql += " AND a.status=?"
        args.append(status)
    if platform != "Any":
        sql += " AND EXISTS (SELECT 1 FROM identities i WHERE i.author_id=a.id AND i.platform=?)"
        args.append(platform)
    sql += " ORDER BY a.heat_score DESC, a.last_seen DESC"
    return conn.execute(sql, args).fetchall()


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
